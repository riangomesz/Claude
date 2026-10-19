"""Serviço de classificação multimodal (Tarefa 11): camada de APLICAÇÃO sobre o `ii_mm.Classifier`.

Não reimplementa classificador nenhum. Oferece: solicitar (planeja a etapa `classify` e o que faltar antes dela),
acompanhar (estado do job e da referência), consultar (resultado persistido pelo `ii_mm`, já com as decisões
humanas aplicadas) e apresentar as distinções pedidas em facetas separadas:

    assunto · categoria_editorial · ferramenta_mencionada · ferramenta_identificada_visualmente · tecnica_observada ·
    tecnica_hipotetica · estrutura_narrativa · conhecimento_transferivel · promessa_comercial · potencial_criativo

Regras preservadas do núcleo: várias categorias por referência; evidência textual nunca vira confirmação visual
(só nome/logotipo legível identifica ferramenta); apoio é ORDINAL (sem porcentagem de confiança ou precisão).
"""
from __future__ import annotations

import sqlite3
from typing import Any, Dict, List, Optional

from . import _ii_mm  # noqa: F401
from .refscope import RefScopedRepository as Repository
from ii_mm.evidence_rules import SUPPORT_LEVELS
from ii_mm.techniques import LEVEL_PROVES, open_questions
from . import incremental as I
from .knowledge import OBSERVED_LEVELS, WEAK_SUPPORT
from .stages import reviewed

FACET_NAMES = ("assunto", "categoria_editorial", "ferramenta_mencionada", "ferramenta_identificada_visualmente", "tecnica_observada",
               "tecnica_hipotetica", "estrutura_narrativa", "conhecimento_transferivel", "promessa_comercial", "potencial_criativo")


def _short(text: Optional[str], n: int = 200) -> Optional[str]:
    if text is None:
        return None
    t = " ".join(str(text).split())
    return t if len(t) <= n else t[:n] + "…"


def facets(doc: Dict[str, Any]) -> Dict[str, Any]:
    ev = {e["evidence_id"]: e for e in doc.get("evidence", [])}
    out: Dict[str, List[Dict[str, Any]]] = {k: [] for k in FACET_NAMES}
    subject = (doc.get("reference") or {}).get("subject")
    if subject:
        out["assunto"].append({"value": _short(subject, 120), "status": "metadata_claim"})
    for term in (doc.get("topic_facets") or {}).get("ai_terms", []):
        out["assunto"].append({"value": term, "status": "mentioned"})
    for c in doc.get("categories", []):
        item = {"category": c["category"], "support": c["support"], "review_state": c.get("review_state", "pending"),
                "evidence_ids": c.get("evidence_ids", []), "contradicting_evidence_ids": c.get("contradicting_evidence_ids", []),
                "authority": "human" if c.get("review_state") in ("accepted", "rejected", "edited") or c.get("added_by_human") else "automatic"}
        out["categoria_editorial"].append(item)
        if c.get("review_state") == "rejected":
            continue
        if c["category"] in ("conhecimento", "tutorial") and c["support"] not in WEAK_SUPPORT:
            out["conhecimento_transferivel"].append({"kind": c["category"], "support": c["support"], "evidence_ids": c.get("evidence_ids", []),
                                                     "rule": "categoria de conhecimento/tutorial com apoio acima de hipótese"})
        if c["category"] == "marketing_vendas" and c["support"] not in WEAK_SUPPORT:
            out["promessa_comercial"].append({"kind": "oferta_ou_chamada_comercial", "support": c["support"],
                                              "evidence_ids": c.get("evidence_ids", [])})
    for t in doc.get("tools", []):
        if t.get("mention_evidence_ids"):
            out["ferramenta_mencionada"].append({"name": t["name"], "status": t["status"], "evidence_ids": t["mention_evidence_ids"],
                                                 "corrected_from": t.get("corrected_from")})
        if t["status"] == "visually_identified":
            out["ferramenta_identificada_visualmente"].append({"name": t["name"], "evidence_ids": t.get("visual_evidence_ids", []),
                                                               "basis": "nome ou logotipo legível no quadro"})
    for tq in doc.get("techniques", []):
        base = {"technique": tq["technique"], "level": tq["level"], "evidence_ids": tq.get("evidence_ids", []),
                "timestamps": tq.get("timestamps", []), "proves": tq.get("proves") or LEVEL_PROVES.get(tq["level"], ("", ""))[0],
                "does_not_prove": tq.get("does_not_prove") or LEVEL_PROVES.get(tq["level"], ("", ""))[1]}
        if tq["level"] in OBSERVED_LEVELS:
            out["tecnica_observada"].append(base)
        elif tq["level"] == "hypothesis":
            out["tecnica_hipotetica"].append(base)
        elif tq["level"] == "reproduction_suggestion":
            out["potencial_criativo"].append({**base, "label": "ideia de produção: não afirma nada sobre o vídeo original"})
    for q in open_questions(doc.get("techniques", [])):
        out["potencial_criativo"].append({"open_question": q, "label": "o que ainda depende de ver o vídeo contínuo"})
    for b in doc.get("narrative_blocks", []):
        out["estrutura_narrativa"].append({"type": b["type"], "t_start_s": b["t_start_s"], "t_end_s": b["t_end_s"],
                                           "support": b.get("support"), "status": b.get("status", "suggested"),
                                           "evidence_ids": b.get("evidence_ids", [])})
    for eid, e in ev.items():
        if e["status"] == "unverified":
            out["promessa_comercial"].append({"kind": "afirmacao_nao_verificada", "claim": _short(e["claim"]), "evidence_ids": [eid],
                                              "note": "afirmação registrada sem demonstração; não é fato verificado"})
    return {"facets": out, "support_order": list(SUPPORT_LEVELS), "numeric_confidence": None,
            "notes": ["apoio é ordinal; não há porcentagem de confiança sem avaliação calibrada",
                      "ferramenta só é 'identificada visualmente' com nome ou logotipo legível; fala e legenda são menção"]}


class ClassificationService:
    def __init__(self, engine):
        self.engine = engine

    def request(self, reference_id: str, force: bool = False) -> Dict[str, Any]:
        if not self.engine.conn.execute("SELECT 1 FROM refs WHERE reference_id = ?", (reference_id,)).fetchone():
            raise KeyError(reference_id)
        plan = self.engine.plan(reference_id, force={"classify"} if force else ())
        job = self.engine.conn.execute("SELECT job_id, state FROM be_jobs WHERE reference_id = ? AND stage = 'classify' "
                                       "ORDER BY created_at DESC, rowid DESC LIMIT 1", (reference_id,)).fetchone()
        return {"reference_id": reference_id, "graph": plan.graph, "enqueued": plan.enqueued, "reused": plan.reused,
                "classify_job": dict(job) if job else None}

    def status(self, reference_id: str) -> Dict[str, Any]:
        view = self.engine.processing(reference_id)
        return {"reference_id": reference_id, "classify": view["stages"].get("classify"), "ii_mm_equivalent": view["ii_mm_equivalent"],
                "graph": view["graph"]}

    def result(self, reference_id: str) -> Optional[Dict[str, Any]]:
        conn: sqlite3.Connection = self.engine.conn
        doc = reviewed(conn, reference_id)
        if doc is None:
            return None
        aid = Repository(conn).current_analysis_id(reference_id)
        cur = I.current_result(conn, reference_id, "classify")
        return {"reference_id": reference_id, "analysis_id": aid, "classifier_version": (cur or {}).get("stage_version"),
                "human_overrides": ((cur or {}).get("result") or {}).get("human_overrides", []),
                "orphan_decisions": doc.get("orphan_decisions", []), **facets(doc)}

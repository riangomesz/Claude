"""Camada de conhecimento estruturado (Tarefa 13).

Referência → evidência → ferramenta / técnica / categoria / narrativa → conhecimento → possibilidade de reprodução.

O índice (`be_knowledge`) é DERIVADO da análise corrente do `ii_mm` já com as decisões humanas aplicadas
(`ReviewService.reviewed_document`) e das decisões de curadoria do backend. Cada linha carrega a proveniência:
`analysis_id`, ids de evidência e instantes. Nenhum vínculo é criado sem evidência; o que é hipótese continua
marcado como hipótese; o que o humano rejeitou fica com status de rejeição e sai das consultas positivas.

Facetas (todas multivaloradas por referência):
- categoria (status = apoio; `rejeitada_humano` quando rejeitada), ferramenta (status = visually_identified |
  mentioned_only | metadata_only | inferred), tecnica (status = nível do ii_mm; `hipotese_rejeitada`),
  narrativa (status = apoio), elemento_visual (tag de observação visual), assunto (termos de IA e assunto),
  conhecimento_transferivel (conhecimento/tutorial com apoio acima de hipótese), promessa_comercial,
  potencial_criativo (sugestões de reprodução: ideias de produção, nunca afirmações sobre o vídeo).
"""
from __future__ import annotations

import json
import sqlite3
from typing import Any, Dict, List, Optional, Tuple

from . import _ii_mm  # noqa: F401
from ii_mm.evidence_rules import SUPPORT_LEVELS

OBSERVED_LEVELS = ("observed_in_frame", "frame_pair_difference", "temporal_sequence")
WEAK_SUPPORT = ("hypothesis", "insufficient")
FACETS = ("categoria", "ferramenta", "tecnica", "narrativa", "elemento_visual", "assunto", "conhecimento_transferivel",
          "promessa_comercial", "potencial_criativo")

Row = Tuple[str, str, str, Dict[str, Any], str]  # facet, value, status, evidence, authority


def _ev(ids, timestamps=None, **extra) -> Dict[str, Any]:
    out = {"evidence_ids": sorted(set(ids or []))}
    if timestamps:
        out["timestamps"] = timestamps
    out.update({k: v for k, v in extra.items() if v is not None})
    return out


def rows_for(doc: Dict[str, Any], targets: Dict[str, str]) -> List[Row]:
    """`doc`: documento revisado; `targets`: decisões do backend (`hypothesis:<técnica>` → rejected, `evidence:<id>` → confirmed)."""
    rows: List[Row] = []
    confirmed = {t.split(":", 1)[1] for t, s in targets.items() if t.startswith("evidence:") and s == "confirmed"}
    for c in doc.get("categories", []):
        human = c.get("review_state") in ("accepted", "edited") or c.get("added_by_human")
        if c.get("review_state") == "rejected":
            rows.append(("categoria", c["category"], "rejeitada_humano", _ev(c.get("evidence_ids"), review_ref=c.get("review_ref")), "human"))
            continue
        rows.append(("categoria", c["category"], c["support"], _ev(c.get("evidence_ids"), review_ref=c.get("review_ref")),
                     "human" if human else "automatic"))
        if c["category"] in ("conhecimento", "tutorial") and c["support"] not in WEAK_SUPPORT:
            rows.append(("conhecimento_transferivel", c["category"], c["support"], _ev(c.get("evidence_ids")), "human" if human else "automatic"))
        if c["category"] == "marketing_vendas" and c["support"] not in WEAK_SUPPORT:
            rows.append(("promessa_comercial", "oferta_ou_chamada_comercial", c["support"], _ev(c.get("evidence_ids")),
                         "human" if human else "automatic"))
    for t in doc.get("tools", []):
        ids = list(t.get("visual_evidence_ids", [])) + list(t.get("mention_evidence_ids", []))
        rows.append(("ferramenta", t["name"], t["status"], _ev(ids, corrected_from=t.get("corrected_from")),
                     "human" if t.get("corrected_from") else "automatic"))
    for tq in doc.get("techniques", []):
        level = tq["level"]
        if level == "reproduction_suggestion":
            rows.append(("potencial_criativo", tq["technique"], "proposta_criativa", _ev(tq.get("evidence_ids"), author=tq.get("author")), "automatic"))
            continue
        status = level
        authority = "automatic"
        if level == "hypothesis" and targets.get(f"hypothesis:{tq['technique']}") == "rejected":
            status, authority = "hipotese_rejeitada", "human"
        rows.append(("tecnica", tq["technique"], status, _ev(tq.get("evidence_ids"), tq.get("timestamps")), authority))
    for b in doc.get("narrative_blocks", []):
        rows.append(("narrativa", b["type"], b.get("support", "hypothesis"), _ev(b.get("evidence_ids"), [[b["t_start_s"], b["t_end_s"]]]), "automatic"))
    tags: Dict[str, List[str]] = {}
    times: Dict[str, List[List[float]]] = {}
    unverified: List[str] = []
    for e in doc.get("evidence", []):
        if e["status"] == "observed_visual" and e.get("tag"):
            tags.setdefault(e["tag"], []).append(e["evidence_id"])
            if e.get("t_start_s") is not None:
                times.setdefault(e["tag"], []).append([e["t_start_s"], e.get("t_end_s", e["t_start_s"])])
        if e["status"] == "unverified":
            unverified.append(e["evidence_id"])
    for tag, ids in sorted(tags.items()):
        human = bool(confirmed.intersection(ids))
        rows.append(("elemento_visual", tag, "observed_visual", _ev(ids, sorted(times.get(tag, [])), human_confirmed=human or None),
                     "human" if human else "automatic"))
    if unverified:
        rows.append(("promessa_comercial", "afirmacao_nao_verificada", "unverified", _ev(unverified), "automatic"))
    subject = (doc.get("reference") or {}).get("subject")
    if subject:
        rows.append(("assunto", subject[:120], "metadata_claim", _ev([]), "automatic"))
    for term in (doc.get("topic_facets") or {}).get("ai_terms", []):
        rows.append(("assunto", term, "mentioned", _ev([]), "automatic"))
    seen, out = set(), []
    for r in rows:  # (faceta, valor, status) é chave: junta evidências repetidas
        k = r[:3]
        if k in seen:
            prev = next(i for i, x in enumerate(out) if x[:3] == k)
            merged = dict(out[prev][3])
            merged["evidence_ids"] = sorted(set(merged["evidence_ids"]) | set(r[3]["evidence_ids"]))
            out[prev] = (*k, merged, "human" if "human" in (out[prev][4], r[4]) else "automatic")
            continue
        seen.add(k)
        out.append(r)
    return out


def replace_rows(conn: sqlite3.Connection, reference_id: str, analysis_id: Optional[str], rows: List[Row]) -> int:
    if not conn.in_transaction:
        raise RuntimeError("replace_rows exige a transação de conclusão do índice")
    conn.execute("DELETE FROM be_knowledge WHERE reference_id = ?", (reference_id,))
    conn.executemany("INSERT INTO be_knowledge(reference_id, facet, value, status, analysis_id, evidence_json, authority) VALUES (?,?,?,?,?,?,?)",
                     [(reference_id, f, v, s, analysis_id, json.dumps(ev, ensure_ascii=False, sort_keys=True), a) for f, v, s, ev, a in rows])
    return len(rows)


def curation_targets(conn: sqlite3.Connection, reference_id: str) -> Dict[str, str]:
    return {r["target"]: r["state"] for r in conn.execute("SELECT target, state FROM be_curation_targets WHERE reference_id = ?", (reference_id,))}


# --------------------------------------------------------------------------- perguntas
def _q(conn: sqlite3.Connection, sql: str, args: list, limit: int) -> List[Dict[str, Any]]:
    limit = max(1, min(int(limit), 500))
    out = []
    for r in conn.execute(sql + " LIMIT ?", args + [limit]):
        d = dict(r)
        if "evidence_json" in d:
            d["provenance"] = json.loads(d.pop("evidence_json"))
        out.append(d)
    return out


def videos_teaching_tool(conn, tool: str, limit: int = 50) -> List[Dict[str, Any]]:
    """Referências que ENSINAM a ferramenta: tutorial/conhecimento com apoio acima de hipótese E a ferramenta
    citada ou identificada. `demonstrated` diz se a ferramenta foi identificada visualmente (nome/logotipo)."""
    return _q(conn, "SELECT k.reference_id, k.status AS tool_status, k.status = 'visually_identified' AS demonstrated, k.evidence_json, "
                    "(SELECT GROUP_CONCAT(t.value || ':' || t.status) FROM be_knowledge t WHERE t.reference_id = k.reference_id "
                    " AND t.facet = 'conhecimento_transferivel') AS teaching_basis "
                    "FROM be_knowledge k WHERE k.facet = 'ferramenta' AND k.value = ? AND EXISTS (SELECT 1 FROM be_knowledge c "
                    "WHERE c.reference_id = k.reference_id AND c.facet = 'conhecimento_transferivel') ORDER BY k.reference_id",
              [tool], limit)


def where_technique(conn, technique: str, include_hypotheses: bool = False, limit: int = 50) -> List[Dict[str, Any]]:
    statuses = list(OBSERVED_LEVELS) + (["hypothesis"] if include_hypotheses else [])
    return _q(conn, f"SELECT reference_id, status AS level, authority, evidence_json FROM be_knowledge WHERE facet = 'tecnica' AND value = ? "
                    f"AND status IN ({','.join('?' * len(statuses))}) ORDER BY reference_id", [technique, *statuses], limit)


def references_with_visual_element(conn, tag: str, limit: int = 50) -> List[Dict[str, Any]]:
    """Composição/elemento visual observado (ex.: split_screen, burned_caption)."""
    return _q(conn, "SELECT reference_id, authority, evidence_json FROM be_knowledge WHERE facet = 'elemento_visual' AND value = ? "
                    "ORDER BY reference_id", [tag], limit)


def techniques_by_evidence_level(conn, limit: int = 200) -> Dict[str, List[Dict[str, Any]]]:
    """Separa técnicas realmente observadas das que são só hipótese (contagem de referências por técnica)."""
    rows = conn.execute("SELECT value, status, COUNT(DISTINCT reference_id) AS refs FROM be_knowledge WHERE facet = 'tecnica' "
                        "GROUP BY value, status ORDER BY value, status LIMIT ?", (limit,)).fetchall()
    out: Dict[str, List[Dict[str, Any]]] = {"observadas": [], "hipoteses": [], "hipoteses_rejeitadas": []}
    for r in rows:
        key = "observadas" if r["status"] in OBSERVED_LEVELS else "hipoteses" if r["status"] == "hypothesis" else "hipoteses_rejeitadas"
        out[key].append({"technique": r["value"], "level": r["status"], "references": r["refs"]})
    return out


def tools_mentioned_not_demonstrated(conn, limit: int = 100) -> List[Dict[str, Any]]:
    return _q(conn, "SELECT k.value AS tool, k.reference_id, k.status, k.evidence_json FROM be_knowledge k WHERE k.facet = 'ferramenta' "
                    "AND k.status IN ('mentioned_only','metadata_only') AND NOT EXISTS (SELECT 1 FROM be_knowledge v WHERE "
                    "v.reference_id = k.reference_id AND v.facet = 'ferramenta' AND v.value = k.value AND v.status = 'visually_identified') "
                    "ORDER BY k.value, k.reference_id", [], limit)


def automation_processes(conn, limit: int = 50) -> List[Dict[str, Any]]:
    strong = [s for s in SUPPORT_LEVELS if s not in WEAK_SUPPORT]
    return _q(conn, f"SELECT reference_id, status AS support, authority, evidence_json FROM be_knowledge WHERE facet = 'categoria' "
                    f"AND value = 'automacao' AND status IN ({','.join('?' * len(strong))}) ORDER BY reference_id", strong, limit)


def transferable_knowledge(conn, limit: int = 50) -> List[Dict[str, Any]]:
    return _q(conn, "SELECT reference_id, value AS kind, status AS support, authority, evidence_json FROM be_knowledge "
                    "WHERE facet = 'conhecimento_transferivel' ORDER BY reference_id, value", [], limit)


def knowledge_for(conn, reference_id: str) -> List[Dict[str, Any]]:
    return _q(conn, "SELECT facet, value, status, authority, analysis_id, evidence_json FROM be_knowledge WHERE reference_id = ? "
                    "ORDER BY facet, value, status", [reference_id], 500)

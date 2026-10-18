"""Classificador multimodal v2 por evidências (Tarefa 05).

Entrada: documento `ii.reference_analysis.v2` já normalizado (evidências com status e proveniência).
Saída: o mesmo documento com `categories`, `tools`, `hypotheses` e `pending` preenchidos.

Regras:
- Multi-rótulo; cada categoria lista as evidências a favor (`evidence_ids`) e contra
  (`contradicting_evidence_ids`); o motivo de cada vínculo fica em `basis`.
- `support` = status da melhor evidência a favor (evidence_rules.category_support). Sem números.
- Texto: só termos FORTES do TextClassifier sustentam; sinais só fracos viram categoria `insufficient`.
- Medição sustenta categoria apenas por regra explícita (`MeasuredRule`), desligada por padrão porque
  nenhum limiar foi calibrado. Sem regra, medições entram como contexto (`context_evidence_ids`).
- Observações visuais e hipóteses entram pelo vocabulário de tags.
- Revisões humanas anteriores (review_state != pending) são preservadas ao reclassificar.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from . import SCHEMA_VERSION
from ._matcher import compile_keyword, normalize
from .evidence_rules import CATEGORIES, category_support
from .text_classifier import TextClassifier
from .vocabulary import TOOL_LEXICON, VISUAL_TAGS

CLASSIFIER_VERSION = "ii_mm.classifier/2.0.0"


@dataclass(frozen=True)
class MeasuredRule:
    """Regra explícita para medição sustentar uma categoria. `calibrated=False` fica registrado na saída."""
    category: str
    tag: str
    min_score: float
    min_count: int
    calibrated: bool = False


@dataclass
class ClassifierConfig:
    measured_rules: Sequence[MeasuredRule] = ()
    context_tags: Dict[str, str] = field(default_factory=lambda: {
        "scene_candidate": "edicao_audiovisual", "frame_difference_metric": "edicao_audiovisual"})
    tool_lexicon: Dict[str, tuple] = field(default_factory=lambda: dict(TOOL_LEXICON))


class Classifier:
    def __init__(self, config: Optional[ClassifierConfig] = None, text: Optional[TextClassifier] = None):
        self.cfg = config or ClassifierConfig()
        self.text = text or TextClassifier()
        for r in self.cfg.measured_rules:
            if r.category not in CATEGORIES:
                raise ValueError(f"MeasuredRule com categoria desconhecida: {r.category}")
        self._tools = {name: [compile_keyword(v) for v in variants] for name, variants in sorted(self.cfg.tool_lexicon.items())}

    # ------------------------------------------------------------------
    def _tool_names(self, text: str) -> List[str]:
        norm = normalize(text)
        return [name for name, pats in self._tools.items() if any(p.search(norm) for p in pats)]

    def classify(self, doc: Dict[str, Any]) -> Dict[str, Any]:
        if doc.get("schema_version") != SCHEMA_VERSION:
            raise ValueError(f"esperado {SCHEMA_VERSION}")
        out = copy.deepcopy(doc)
        evidence = out.get("evidence", [])
        prev_reviews = {c["category"]: c for c in doc.get("categories", []) if c.get("review_state", "pending") != "pending"}

        pro: Dict[str, Dict[str, Dict[str, Any]]] = {c: {} for c in CATEGORIES}
        contra: Dict[str, Dict[str, Dict[str, Any]]] = {c: {} for c in CATEGORIES}
        weak: Dict[str, List[Dict[str, Any]]] = {c: [] for c in CATEGORIES}
        context: Dict[str, List[str]] = {c: [] for c in CATEGORIES}
        notes: Dict[str, List[str]] = {c: [] for c in CATEGORIES}
        tools: Dict[str, Dict[str, List[str]]] = {}
        ai_terms: set = set()

        for e in evidence:
            st, eid = e["status"], e["evidence_id"]
            if st in ("transcript_claim", "metadata_claim"):
                res = self.text.classify(e["claim"])
                ai_terms.update(res.ai_topic_terms)
                for m in res.matches:
                    link = {"evidence_id": eid, "rule": "text_v2", "terms": m.terms}
                    if m.strength == "strong":
                        pro[m.category].setdefault(eid, link)
                    else:
                        weak[m.category].append(link)
                for name in self._tool_names(e["claim"]):
                    key = "mention_evidence_ids" if st == "transcript_claim" else "metadata_evidence_ids"
                    tools.setdefault(name, {}).setdefault(key, []).append(eid)
            elif st in ("observed_visual", "inference") and e.get("tag") in VISUAL_TAGS:
                spec = VISUAL_TAGS[e["tag"]]
                link = {"evidence_id": eid, "rule": "visual_tag", "tag": e["tag"], "basis": e.get("basis")}
                if spec.category:
                    pro[spec.category].setdefault(eid, link)
                if spec.contradicts:
                    contra[spec.contradicts].setdefault(eid, link)
                if e.get("tag") in ("ui_screen_visible", "tool_name_visible", "logo_visible"):
                    # Só nome ou logotipo LEGÍVEL identifica a ferramenta; reconhecer a interface pela
                    # aparência é conhecimento externo do observador (fica como inferida).
                    legible = st == "observed_visual" and e["tag"] in ("tool_name_visible", "logo_visible")
                    for name in self._tool_names(e["claim"]):
                        key = "visual_evidence_ids" if legible else "inferred_evidence_ids"
                        tools.setdefault(name, {}).setdefault(key, []).append(eid)
            elif st == "measured_signal":
                cat = self.cfg.context_tags.get(e.get("tag"))
                if cat:
                    context[cat].append(eid)

        for rule in self.cfg.measured_rules:
            hits = [e for e in evidence if e["status"] == "measured_signal" and e.get("tag") == rule.tag
                    and (e.get("extra") or {}).get("score", 0) >= rule.min_score]
            if len(hits) >= rule.min_count:
                for e in hits:
                    pro[rule.category].setdefault(e["evidence_id"], {
                        "evidence_id": e["evidence_id"], "rule": "measured_rule",
                        "min_score": rule.min_score, "min_count": rule.min_count})
                if not rule.calibrated:
                    notes[rule.category].append(f"regra de medição não calibrada ({rule.tag} ≥ {rule.min_score}, n ≥ {rule.min_count})")

        by_id = {e["evidence_id"]: e for e in evidence}
        categories = []
        pending = [p for p in out.get("pending", []) if not str(p.get("pending_id", "")).startswith("auto:")]
        for cat in CATEGORIES:
            links = sorted(pro[cat].values(), key=lambda l: l["evidence_id"])
            con = sorted(contra[cat].values(), key=lambda l: l["evidence_id"])
            if not links and not weak[cat] and not con:
                continue
            sup_ev = [by_id[l["evidence_id"]] for l in links]
            entry = {
                "category": cat,
                "support": category_support(sup_ev),
                "evidence_ids": [l["evidence_id"] for l in links],
                "contradicting_evidence_ids": [l["evidence_id"] for l in con if l["evidence_id"] not in pro[cat]],
                "context_evidence_ids": sorted(set(context[cat])) if links else [],
                "basis": links + [dict(l, contra=True) for l in con],
                "weak_signals": weak[cat],
                "notes": notes[cat],
                "review_state": "pending",
                "classifier_version": CLASSIFIER_VERSION,
            }
            if entry["contradicting_evidence_ids"]:
                entry["contested"] = True
                pending.append({"pending_id": f"auto:contested:{cat}", "description": f"'{cat}' tem evidência contrária; revisar", "blocking": False})
            if not links:
                pending.append({"pending_id": f"auto:insufficient:{cat}", "description": f"'{cat}' só tem sinais fracos ou contrários", "blocking": False})
            if cat in prev_reviews:
                prev = prev_reviews[cat]
                if sorted(prev.get("evidence_ids", [])) == entry["evidence_ids"]:
                    # mesma base de evidências: a decisão humana anterior continua válida
                    entry["review_state"] = prev["review_state"]
                    entry["review_ref"] = prev.get("review_ref")
                else:
                    # a revisão foi feita sobre outras evidências: não herda, mas fica rastreável
                    entry["stale_review_ref"] = prev.get("review_ref")
                    entry["notes"].append(f"revisão anterior ({prev['review_state']}) refere-se a outro conjunto de evidências")
            categories.append(entry)

        out["categories"] = categories
        out["tools"] = self._tools_out(tools)
        out["topic_facets"] = {"ai_terms": sorted(ai_terms)}
        out["pending"] = pending
        out.setdefault("classification_runs", []).append({"classifier_version": CLASSIFIER_VERSION,
                                                          "measured_rules": [r.__dict__ for r in self.cfg.measured_rules]})
        return out

    @staticmethod
    def _tools_out(tools) -> List[Dict[str, Any]]:
        """Correções humanas de nome de ferramenta ficam na camada de revisão (review.py), não aqui."""
        out = []
        for name in sorted(tools):
            t = tools[name]
            vis = sorted(set(t.get("visual_evidence_ids", [])))
            men = sorted(set(t.get("mention_evidence_ids", [])))
            meta = sorted(set(t.get("metadata_evidence_ids", [])))
            inf = sorted(set(t.get("inferred_evidence_ids", [])))
            status = ("visually_identified" if vis else "mentioned_only" if men else
                      "metadata_only" if meta else "inferred" if inf else "unverified")
            out.append({"name": name, "status": status, "visual_evidence_ids": vis,
                        "mention_evidence_ids": men + meta + inf})
        return out

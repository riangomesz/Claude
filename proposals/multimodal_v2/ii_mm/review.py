"""Revisão humana e correção de classificação (Tarefa 14).

Princípios:
- A análise automática gravada NUNCA é alterada: decisões ficam em `reviews` (histórico imutável, sequência
  por referência) e `review_state` (decisão corrente por alvo).
- A visão revisada (`reviewed_document`) é uma sobreposição calculada: aplica as decisões correntes sobre a
  análise corrente e continua válida pelo contrato.
- Concorrência otimista: quem revisa informa a última sequência que viu (`expected_seq`); se outra revisão
  entrou no meio, levanta `ReviewConflict` e nada é gravado.
- Justificativa é obrigatória para rejeitar, adicionar, corrigir ferramenta e rebaixar evidência.
- Decisões sobrevivem a reprocessamentos; decisão cujo alvo sumiu na nova análise é reportada como órfã.

Alvos: `category:<nome>`, `tool:<nome>`, `evidence:<id>`.
"""
from __future__ import annotations

import copy
import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .contract import assert_valid
from .db.repository import Repository
from .evidence_rules import CATEGORIES, category_support

ACTIONS = ("accept_category", "reject_category", "add_category", "correct_tool_name", "mark_evidence_hypothesis")
NEEDS_JUSTIFICATION = {"reject_category", "add_category", "correct_tool_name", "mark_evidence_hypothesis"}


class ReviewError(ValueError):
    pass


class ReviewConflict(ReviewError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


class ReviewService:
    def __init__(self, repo: Repository):
        self.repo = repo

    def last_seq(self, reference_id: str) -> int:
        row = self.repo.conn.execute("SELECT MAX(seq) FROM reviews WHERE reference_id = ?", (reference_id,)).fetchone()
        return int(row[0] or 0)

    def _record(self, reference_id: str, action: str, target: str, state: str, reviewer: str,
                justification: Optional[str], expected_seq: Optional[int], value: Any = None) -> str:
        if action not in ACTIONS:
            raise ReviewError(f"ação desconhecida: {action}")
        if not reviewer or not reviewer.strip():
            raise ReviewError("reviewer obrigatório")
        if action in NEEDS_JUSTIFICATION and not (justification and justification.strip()):
            raise ReviewError(f"{action} exige justificativa")
        analysis_id = self.repo.current_analysis_id(reference_id)
        if analysis_id is None:
            raise ReviewError(f"referência sem análise: {reference_id}")
        with self.repo.tx() as c:
            seq = int(c.execute("SELECT COALESCE(MAX(seq), 0) FROM reviews WHERE reference_id = ?", (reference_id,)).fetchone()[0])
            if expected_seq is not None and expected_seq != seq:
                raise ReviewConflict(f"revisão concorrente: esperado seq {expected_seq}, atual {seq}")
            before = c.execute("SELECT state, value_json FROM review_state WHERE reference_id = ? AND target = ?",
                               (reference_id, target)).fetchone()
            review_id = f"rv_{reference_id}_{seq + 1:05d}"
            after = {"state": state, "value": value}
            c.execute("INSERT INTO reviews(review_id, reference_id, analysis_id, seq, at, reviewer, action, target, before_json, after_json, justification) "
                      "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                      (review_id, reference_id, analysis_id, seq + 1, _now(), reviewer, action, target,
                       json.dumps(dict(before) if before else None, ensure_ascii=False), json.dumps(after, ensure_ascii=False),
                       justification))
            c.execute("INSERT INTO review_state(reference_id, target, state, value_json, review_id, updated_at) VALUES (?,?,?,?,?,?) "
                      "ON CONFLICT(reference_id, target) DO UPDATE SET state=excluded.state, value_json=excluded.value_json, "
                      "review_id=excluded.review_id, updated_at=excluded.updated_at",
                      (reference_id, target, state, json.dumps(value, ensure_ascii=False), review_id, _now()))
        return review_id

    # -- ações -------------------------------------------------------------
    def accept_category(self, reference_id, category, reviewer, justification=None, expected_seq=None):
        self._require_category(reference_id, category, must_exist=True)
        return self._record(reference_id, "accept_category", f"category:{category}", "accepted", reviewer, justification, expected_seq)

    def reject_category(self, reference_id, category, reviewer, justification, expected_seq=None):
        self._require_category(reference_id, category, must_exist=True)
        return self._record(reference_id, "reject_category", f"category:{category}", "rejected", reviewer, justification, expected_seq)

    def add_category(self, reference_id, category, reviewer, justification, expected_seq=None):
        if category not in CATEGORIES:
            raise ReviewError(f"categoria desconhecida: {category}")
        return self._record(reference_id, "add_category", f"category:{category}", "added", reviewer, justification, expected_seq)

    def correct_tool_name(self, reference_id, wrong_name, right_name, reviewer, justification, expected_seq=None):
        doc = self._current_doc(reference_id)
        if wrong_name not in {t["name"] for t in doc["tools"]}:
            raise ReviewError(f"ferramenta não encontrada na análise: {wrong_name}")
        if not right_name or right_name == wrong_name:
            raise ReviewError("novo nome inválido")
        return self._record(reference_id, "correct_tool_name", f"tool:{wrong_name}", "corrected", reviewer, justification,
                            expected_seq, value={"name": right_name})

    def mark_evidence_hypothesis(self, reference_id, evidence_id, reviewer, justification, expected_seq=None):
        doc = self._current_doc(reference_id)
        ev = next((e for e in doc["evidence"] if e["evidence_id"] == evidence_id), None)
        if ev is None:
            raise ReviewError(f"evidência não encontrada: {evidence_id}")
        if ev["source_type"] not in ("agent_observation", "human_observation", "text_classifier", "derived"):
            raise ReviewError("só observações e inferências podem ser rebaixadas para hipótese")
        return self._record(reference_id, "mark_evidence_hypothesis", f"evidence:{evidence_id}", "hypothesis",
                            reviewer, justification, expected_seq)

    # -- leitura -----------------------------------------------------------
    def history(self, reference_id: str) -> List[Dict[str, Any]]:
        return [dict(r) for r in self.repo.conn.execute(
            "SELECT review_id, seq, at, reviewer, action, target, before_json, after_json, justification "
            "FROM reviews WHERE reference_id = ? ORDER BY seq", (reference_id,))]

    def decisions(self, reference_id: str) -> Dict[str, Dict[str, Any]]:
        return {r["target"]: {"state": r["state"], "value": json.loads(r["value_json"]) if r["value_json"] else None,
                              "review_id": r["review_id"]}
                for r in self.repo.conn.execute("SELECT * FROM review_state WHERE reference_id = ?", (reference_id,))}

    def _current_doc(self, reference_id: str) -> Dict[str, Any]:
        aid = self.repo.current_analysis_id(reference_id)
        if aid is None:
            raise ReviewError(f"referência sem análise: {reference_id}")
        return self.repo.get_document(aid)

    def _require_category(self, reference_id: str, category: str, must_exist: bool) -> None:
        doc = self._current_doc(reference_id)
        present = {c["category"] for c in doc["categories"]}
        dec = self.decisions(reference_id).get(f"category:{category}")
        if must_exist and category not in present and not (dec and dec["state"] == "added"):
            raise ReviewError(f"categoria '{category}' não existe na análise corrente; use add_category")

    def reviewed_document(self, reference_id: str) -> Dict[str, Any]:
        """Análise corrente + decisões humanas correntes (sem alterar o registro automático)."""
        original = self._current_doc(reference_id)
        doc = copy.deepcopy(original)
        dec = self.decisions(reference_id)
        orphans = []
        ev_by_id = {e["evidence_id"]: e for e in doc["evidence"]}
        for target, d in dec.items():
            if target.startswith("evidence:"):
                e = ev_by_id.get(target.split(":", 1)[1])
                if e is None:
                    orphans.append(target)
                elif d["state"] == "hypothesis" and e["status"] != "inference":
                    e["original_status"] = e["status"]
                    e["status"] = "inference"
        for c in doc["categories"]:  # rebaixar evidência pode mudar o apoio
            c["support"] = category_support([ev_by_id[i] for i in c.get("evidence_ids", []) if i in ev_by_id])
        for t in doc["tools"]:  # ... e o status das ferramentas
            demoted = [i for i in t.get("visual_evidence_ids", []) if ev_by_id.get(i, {}).get("status") != "observed_visual"]
            if demoted:
                t["visual_evidence_ids"] = [i for i in t["visual_evidence_ids"] if i not in demoted]
                t["mention_evidence_ids"] = sorted(set(t.get("mention_evidence_ids", [])) | set(demoted))
                statuses = {ev_by_id[i]["status"] for i in t["mention_evidence_ids"] if i in ev_by_id}
                t["status"] = ("visually_identified" if t["visual_evidence_ids"] else
                               "mentioned_only" if "transcript_claim" in statuses else
                               "metadata_only" if "metadata_claim" in statuses else "inferred")
        cats = {c["category"]: c for c in doc["categories"]}
        for target, d in dec.items():
            if target.startswith("category:"):
                name = target.split(":", 1)[1]
                if name in cats:
                    cats[name]["review_state"] = "accepted" if d["state"] == "accepted" else "rejected" if d["state"] == "rejected" else "edited"
                    cats[name]["review_ref"] = d["review_id"]
                elif d["state"] == "added":
                    cats[name] = {"category": name, "support": "insufficient", "evidence_ids": [], "contradicting_evidence_ids": [],
                                  "review_state": "accepted", "review_ref": d["review_id"], "added_by_human": True}
                else:
                    orphans.append(target)
            elif target.startswith("tool:"):
                old = target.split(":", 1)[1]
                tool = next((t for t in doc["tools"] if t["name"] == old), None)
                if tool is None:
                    orphans.append(target)
                elif d["state"] == "corrected":
                    tool["corrected_from"] = old
                    tool["name"] = d["value"]["name"]
                    tool["review_ref"] = d["review_id"]
        from .evidence_rules import CATEGORIES as ORDER
        doc["categories"] = [cats[c] for c in ORDER if c in cats]
        doc["review_history"] = [{"review_id": h["review_id"], "at": h["at"], "reviewer": h["reviewer"], "action": h["action"],
                                  "target": h["target"], "justification": h["justification"]} for h in self.history(reference_id)]
        doc["orphan_decisions"] = sorted(orphans)
        assert_valid(doc)
        return doc

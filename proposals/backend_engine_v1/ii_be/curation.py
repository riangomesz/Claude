"""Serviço de curadoria humana (Tarefa 15).

Decisões suportadas e onde cada uma é a fonte de verdade:

| ação                                   | autoridade                          | justificativa |
|----------------------------------------|-------------------------------------|---------------|
| triage: manter / revisar / descartar   | `be_curation` (+ log)               | descartar     |
| rating: excelente / muito_bom / bom / ruim | `be_curation` (+ log)           | —             |
| accept_category / reject_category / add_category | `ii_mm` ReviewService     | reject, add   |
| correct_tool                           | `ii_mm` ReviewService               | sim           |
| demote_evidence (rebaixar a hipótese)  | `ii_mm` ReviewService               | sim           |
| confirm_evidence                       | `be_curation_targets` (+ log)       | —             |
| reject_hypothesis (técnica hipotética) | `be_curation_targets` (+ log)       | sim           |

- Concorrência otimista: o `etag` é `"<seq das revisões do ii_mm>.<revisão do backend>"`. Ações do ii_mm conferem a
  parte `seq` na transação do próprio ii_mm (`expected_seq`); ações do backend conferem a revisão na transação do
  backend. Quem decidiu com uma visão velha recebe `CurationConflict` e nada é gravado.
- Histórico: nada é sobrescrito. Estado anterior e posterior, motivo, revisor, data e revisão ficam no log; as
  revisões do ii_mm ficam em `reviews` (imutável). `history()` junta as duas fontes.
- Autoridade humana: o revisor precisa ser humano (`human:<nome>` ou nome simples). Atores automáticos (`auto:`,
  `agent:`, `worker:`, `system:`, `model:`, `n8n:`) são recusados: nenhuma automação registra curadoria.
- Decisões do backend gravam o evento `curation.reviewed` na MESMA transação; as do ii_mm entram por reconciliação
  (`events.reconcile_reviews`), sem perda nem duplicação.
"""
from __future__ import annotations

import json
import sqlite3
from typing import Any, Dict, List, Optional

from . import _ii_mm  # noqa: F401
from ii_mm.db.repository import Repository
from ii_mm.review import ReviewConflict, ReviewError, ReviewService
from .clock import iso
from .db import tx
from .events import emit

TRIAGE = {"manter": "manter", "revisar": "revisar_depois", "revisar_depois": "revisar_depois", "descartar": "descartar"}
RATINGS = ("excelente", "muito_bom", "bom", "ruim")
AUTOMATED_PREFIXES = ("auto:", "agent:", "worker:", "system:", "model:", "n8n:", "bot:")
ACTIONS = ("triage", "rating", "accept_category", "reject_category", "add_category", "correct_tool", "demote_evidence",
           "confirm_evidence", "reject_hypothesis")


class CurationError(ValueError):
    pass


class CurationConflict(CurationError):
    pass


def _check_reviewer(reviewer: Any) -> str:
    if not isinstance(reviewer, str) or not reviewer.strip() or len(reviewer) > 120 or any(ord(c) < 32 for c in reviewer):
        raise CurationError("revisor obrigatório")
    if reviewer.strip().lower().startswith(AUTOMATED_PREFIXES):
        raise CurationError("curadoria é humana: atores automáticos não registram decisões")
    return reviewer.strip()


class CurationService:
    def __init__(self, conn: sqlite3.Connection, clock):
        self.conn, self.clock = conn, clock
        self.repo = Repository(conn)
        self.ii = ReviewService(self.repo)

    # ------------------------------------------------------------------ leitura
    def _be_revision(self, c, reference_id: str) -> int:
        return int(c.execute("SELECT COALESCE(MAX(revision), 0) FROM be_curation_log WHERE reference_id = ?", (reference_id,)).fetchone()[0])

    def etag(self, reference_id: str) -> str:
        return f"{self.ii.last_seq(reference_id)}.{self._be_revision(self.conn, reference_id)}"

    def state(self, reference_id: str) -> Dict[str, Any]:
        self._require_ref(reference_id)
        row = self.conn.execute("SELECT triage, rating, revision, updated_at, updated_by FROM be_curation WHERE reference_id = ?",
                                (reference_id,)).fetchone()
        targets = {r["target"]: r["state"] for r in self.conn.execute("SELECT target, state FROM be_curation_targets WHERE reference_id = ?",
                                                                      (reference_id,))}
        return {"reference_id": reference_id, "etag": self.etag(reference_id), "triage": row["triage"] if row else None,
                "rating": row["rating"] if row else None, "targets": targets, "ii_decisions": self.ii.decisions(reference_id)}

    def history(self, reference_id: str) -> List[Dict[str, Any]]:
        be = [{"source": "backend", "revision": r["revision"], "action": r["action"], "target": r["target"], "reviewer": r["reviewer"],
               "reason": r["reason"], "before": json.loads(r["before_json"]) if r["before_json"] else None,
               "after": json.loads(r["after_json"]) if r["after_json"] else None, "ii_review_id": r["ii_review_id"], "at": r["at"]}
              for r in self.conn.execute("SELECT * FROM be_curation_log WHERE reference_id = ? ORDER BY log_id", (reference_id,))]
        logged = {h["ii_review_id"] for h in be if h["ii_review_id"]}
        ii = [{"source": "ii_mm", "seq": h["seq"], "action": h["action"], "target": h["target"], "reviewer": h["reviewer"],
               "reason": h["justification"], "before": json.loads(h["before_json"]) if h["before_json"] else None,
               "after": json.loads(h["after_json"]) if h["after_json"] else None, "ii_review_id": h["review_id"], "at": h["at"]}
              for h in self.ii.history(reference_id) if h["review_id"] not in logged]
        return be + ii

    def _require_ref(self, reference_id: str) -> None:
        if not self.conn.execute("SELECT 1 FROM refs WHERE reference_id = ?", (reference_id,)).fetchone():
            raise CurationError(f"referência desconhecida: {reference_id}")

    # ------------------------------------------------------------------ escrita
    def decide(self, reference_id: str, action: str, reviewer: str, reason: Optional[str] = None,
               expected_etag: Optional[str] = None, **params: Any) -> Dict[str, Any]:
        if action not in ACTIONS:
            raise CurationError(f"ação desconhecida: {action}")
        reviewer = _check_reviewer(reviewer)
        self._require_ref(reference_id)
        if reason is not None and (not isinstance(reason, str) or len(reason) > 2000):
            raise CurationError("motivo inválido")
        exp_seq = exp_rev = None
        if expected_etag is not None:
            try:
                a, b = str(expected_etag).split(".")
                exp_seq, exp_rev = int(a), int(b)
            except ValueError:
                raise CurationError("etag inválido") from None
        if action in ("accept_category", "reject_category", "add_category", "correct_tool", "demote_evidence"):
            return self._ii_action(reference_id, action, reviewer, reason, exp_seq, params)
        return self._be_action(reference_id, action, reviewer, reason, exp_rev, params)

    def _ii_action(self, ref, action, reviewer, reason, exp_seq, p) -> Dict[str, Any]:
        try:
            if action == "accept_category":
                rid = self.ii.accept_category(ref, p.get("category"), reviewer, reason, expected_seq=exp_seq)
            elif action == "reject_category":
                rid = self.ii.reject_category(ref, p.get("category"), reviewer, reason, expected_seq=exp_seq)
            elif action == "add_category":
                rid = self.ii.add_category(ref, p.get("category"), reviewer, reason, expected_seq=exp_seq)
            elif action == "correct_tool":
                rid = self.ii.correct_tool_name(ref, p.get("wrong_name"), p.get("right_name"), reviewer, reason, expected_seq=exp_seq)
            else:
                rid = self.ii.mark_evidence_hypothesis(ref, p.get("evidence_id"), reviewer, reason, expected_seq=exp_seq)
        except ReviewConflict as exc:
            raise CurationConflict(str(exc)) from None
        except ReviewError as exc:
            raise CurationError(str(exc)) from None
        now = self.clock.now()
        with tx(self.conn) as c:  # registro espelho; a fonte de verdade é o `reviews` do ii_mm (já confirmado)
            rev = self._be_revision(c, ref) + 1
            c.execute("INSERT INTO be_curation_log(reference_id, revision, action, target, before_json, after_json, reviewer, reason, ii_review_id, at) "
                      "VALUES (?,?,?,?,?,?,?,?,?,?)", (ref, rev, action, p.get("category") or p.get("wrong_name") or p.get("evidence_id"),
                                                       None, json.dumps(p, ensure_ascii=False, sort_keys=True), reviewer, reason, rid, iso(now)))
            emit(c, "curation.reviewed", ref, {"source": "ii_mm.review", "review_id": rid, "action": action}, now, dedup_key=f"ii_review|{rid}")
        return {"reference_id": ref, "action": action, "ii_review_id": rid, "etag": self.etag(ref)}

    def _be_action(self, ref, action, reviewer, reason, exp_rev, p) -> Dict[str, Any]:
        now = self.clock.now()
        doc = None
        if action in ("confirm_evidence", "reject_hypothesis"):
            aid = self.repo.current_analysis_id(ref)
            if aid is None:
                raise CurationError("referência sem análise corrente")
            doc = self.repo.get_document(aid)
        if action == "triage":
            value = TRIAGE.get(str(p.get("value")))
            if value is None:
                raise CurationError(f"triagem inválida: {p.get('value')!r} (manter, revisar, descartar)")
            if value == "descartar" and not (reason and reason.strip()):
                raise CurationError("descartar exige motivo")
        elif action == "rating":
            value = p.get("value")
            if value not in RATINGS:
                raise CurationError(f"nota inválida: {value!r} ({', '.join(RATINGS)})")
        elif action == "confirm_evidence":
            value = p.get("evidence_id")
            if value not in {e["evidence_id"] for e in doc["evidence"]}:
                raise CurationError(f"evidência não encontrada na análise corrente: {value}")
        else:
            value = p.get("technique")
            if not (reason and reason.strip()):
                raise CurationError("rejeitar hipótese exige motivo")
            if value not in {t["technique"] for t in doc["techniques"] if t["level"] == "hypothesis"}:
                raise CurationError(f"técnica hipotética não encontrada: {value}")
        with tx(self.conn) as c:
            rev = self._be_revision(c, ref)
            if exp_rev is not None and exp_rev != rev:
                raise CurationConflict(f"curadoria concorrente: esperado revisão {exp_rev}, atual {rev}")
            rev += 1
            at = iso(now)
            if action in ("triage", "rating"):
                before = c.execute("SELECT triage, rating FROM be_curation WHERE reference_id = ?", (ref,)).fetchone()
                before_d = dict(before) if before else None
                col = "triage" if action == "triage" else "rating"
                c.execute(f"INSERT INTO be_curation(reference_id, {col}, revision, updated_at, updated_by) VALUES (?,?,?,?,?) "
                          f"ON CONFLICT(reference_id) DO UPDATE SET {col}=excluded.{col}, revision=excluded.revision, "
                          "updated_at=excluded.updated_at, updated_by=excluded.updated_by", (ref, value, rev, at, reviewer))
                target, after = col, {col: value}
            else:
                target = f"evidence:{value}" if action == "confirm_evidence" else f"hypothesis:{value}"
                state = "confirmed" if action == "confirm_evidence" else "rejected"
                before = c.execute("SELECT state FROM be_curation_targets WHERE reference_id = ? AND target = ?", (ref, target)).fetchone()
                before_d = {"state": before["state"]} if before else None
                c.execute("INSERT INTO be_curation_targets(reference_id, target, state, revision, updated_at) VALUES (?,?,?,?,?) "
                          "ON CONFLICT(reference_id, target) DO UPDATE SET state=excluded.state, revision=excluded.revision, "
                          "updated_at=excluded.updated_at", (ref, target, state, rev, at))
                after = {"state": state}
            c.execute("INSERT INTO be_curation_log(reference_id, revision, action, target, before_json, after_json, reviewer, reason, at) "
                      "VALUES (?,?,?,?,?,?,?,?,?)", (ref, rev, action, target, json.dumps(before_d, ensure_ascii=False),
                                                     json.dumps(after, ensure_ascii=False), reviewer, reason, at))
            emit(c, "curation.reviewed", ref, {"source": "backend", "action": action, "target": target, "revision": rev}, now,
                 dedup_key=f"be_curation|{ref}|{rev}")
        return {"reference_id": ref, "action": action, "revision": rev, "etag": self.etag(ref)}

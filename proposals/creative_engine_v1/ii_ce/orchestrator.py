"""CreativeEngine: investigações versionadas, tarefas idempotentes e retomáveis, reconciliação, dossiê e eventos.

Persistência: mesmo SQLite do `ii_be` (tabelas `ce_*`). Cada investigação guarda o pacote de evidências congelado.
Execução: a transição de tarefa `pending → running` é um UPDATE condicional (vale entre threads e processos); a tarefa tem
lease; queda no meio deixa a tarefa `running` até o lease vencer, e `run` a recoloca na fila. Afirmações têm id determinístico
(INSERT OR IGNORE), então repetir uma tarefa não duplica nada. Decisões humanas nunca são tocadas pelo motor.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import _be  # noqa: F401
from ii_be.clock import SystemClock
from ii_be.curation import AUTOMATED_PREFIXES
from ii_be.db import tx
from . import events as EV
from . import planner as PL
from .commercial import load_profiles
from .contracts import (APPROVAL_SCOPES, DEPTHS, DOMAINS, REVIEW_DECISIONS, SCHEMA_INVESTIGATION, SPECIALISTS, canonical_json, clean_text, digest)
from .db import migrate_ce
from .evidence import build_bundle, select_for
from .providers import SpecialistGateway
from .reconcile import latest_reviews, reconcile

TERMINAL_OK = ("done",)
READY_STATES = ("pending", "awaiting_approval")
DEFAULT_PROFILES = ("rian_rocha_ia", "objetaria")


class CEError(ValueError):
    pass


def _human(name: Any) -> str:
    if not isinstance(name, str) or not name.strip() or len(name) > 120 or any(ord(c) < 32 for c in name):
        raise CEError("identificação humana obrigatória")
    if name.strip().lower().startswith(AUTOMATED_PREFIXES):
        raise CEError("decisão humana: atores automáticos (auto:, agent:, n8n:, …) não podem registrá-la")
    return name.strip()


class CreativeEngine:
    def __init__(self, engine=None, conn: Optional[sqlite3.Connection] = None, providers: Optional[Dict[str, Any]] = None,
                 profiles_dir: Optional[Path] = None, clock=None, lease_s: float = 120.0, max_attempts: int = 3, deadline_s: float = 30.0):
        if engine is None and conn is None:
            raise CEError("informe engine (ii_be) ou conn")
        self.engine = engine
        self.conn = conn or engine.conn
        self.clock = clock or (engine.clock if engine is not None else SystemClock())
        self.gateway = SpecialistGateway(providers or {})
        self.profiles_dir = Path(profiles_dir) if profiles_dir else Path(__file__).resolve().parents[1] / "profiles"
        self.lease_s, self.max_attempts, self.deadline_s = lease_s, max_attempts, deadline_s
        migrate_ce(self.conn)

    # ---------------------------------------------------------------- investigação
    def profiles(self, ids=DEFAULT_PROFILES) -> Dict[str, Dict[str, Any]]:
        return load_profiles(self.profiles_dir, ids)

    def open_investigation(self, reference_id: str, depth: str = "standard", profile_ids=DEFAULT_PROFILES, priority: int = 5,
                           limits: Optional[Dict[str, Any]] = None, requested_by: str = "human:desconhecido") -> Dict[str, Any]:
        if depth not in DEPTHS:
            raise CEError(f"profundidade inválida: {depth}")
        if not isinstance(priority, int) or not 1 <= priority <= 9:
            raise CEError("prioridade deve estar entre 1 e 9")
        limits = {k: v for k, v in (limits or {}).items() if k in ("max_calls", "max_usd", "deadline_s", "require_start_approval")}
        profs = self.profiles(profile_ids)
        bundle = build_bundle(self.engine, reference_id)
        versions = {**bundle["versions"], "profiles": {pid: {"version": p["version"], "hash": p["hash"]} for pid, p in profs.items()}}
        input_hash = digest(bundle["content_hash"], versions, depth, limits, n=32)
        found = self._by_input(reference_id, input_hash)
        if found:
            return {**self._summary(found), "created": False}
        plan = PL.plan(bundle, depth, limits, estimate=self.gateway.estimate, registered=self.gateway.has)
        inv_id = "inv_" + digest(reference_id, input_hash)
        now = self.clock.now()
        try:
            with tx(self.conn) as c:
                last = c.execute("SELECT investigation_id, seq FROM ce_investigations WHERE reference_id = ? ORDER BY seq DESC LIMIT 1", (reference_id,)).fetchone()
                seq = (last["seq"] + 1) if last else 1
                if plan["reference_kind"] == "sem_evidencia":
                    state = "blocked_no_evidence"
                elif limits.get("require_start_approval"):
                    state = "awaiting_start_approval"
                else:
                    state = "planned"
                c.execute("INSERT INTO ce_investigations(investigation_id, reference_id, seq, input_hash, content_hash, bundle_json, depth, priority, profile_ids_json, "
                          "versions_json, limits_json, plan_json, state, supersedes, requested_by, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                          (inv_id, reference_id, seq, input_hash, bundle["content_hash"], canonical_json(bundle), depth, priority, json.dumps(list(profs)),
                           canonical_json(versions), canonical_json(limits), canonical_json(plan), state, last["investigation_id"] if last else None, requested_by, now, now))
                if last:
                    c.execute("UPDATE ce_investigations SET state = 'superseded', updated_at = ? WHERE investigation_id = ? AND state != 'superseded'", (now, last["investigation_id"]))
                for t in plan["tasks"]:
                    tid = digest(inv_id, t["specialist"], t["kind"])
                    st = ("pending" if self.gateway.has(t["specialist"]) else "blocked_provider") if t["selected"] else "skipped"
                    c.execute("INSERT INTO ce_tasks(task_id, investigation_id, specialist, kind, state, depends_on_json, reason, est_usd, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                              (tid, inv_id, t["specialist"], t["kind"], st, json.dumps([digest(inv_id, d, SPECIALISTS[d]["kind"]) for d in t["depends_on"]]), t["reason"], t["est_usd"], now, now))
                EV.emit(c, "investigation.blocked" if state == "blocked_no_evidence" else "investigation.created", inv_id,
                        {"reference_id": reference_id, "seq": seq, "state": state, "depth": depth, "reference_kind": plan["reference_kind"]}, now, inv_id)
        except sqlite3.IntegrityError:  # outra thread/processo criou a mesma investigação no mesmo instante
            found = self._by_input(reference_id, input_hash)
            if found:
                return {**self._summary(found), "created": False}
            raise
        return {**self._summary(self._by_input(reference_id, input_hash)), "created": True}

    def _by_input(self, reference_id: str, input_hash: str):
        return self.conn.execute("SELECT * FROM ce_investigations WHERE reference_id = ? AND input_hash = ?", (reference_id, input_hash)).fetchone()

    @staticmethod
    def _summary(row) -> Dict[str, Any]:
        plan = json.loads(row["plan_json"])
        return {"investigation_id": row["investigation_id"], "reference_id": row["reference_id"], "seq": row["seq"], "state": row["state"], "depth": row["depth"],
                "reference_kind": plan["reference_kind"], "plan": plan}

    def get(self, investigation_id: str) -> Dict[str, Any]:
        r = self.conn.execute("SELECT * FROM ce_investigations WHERE investigation_id = ?", (investigation_id,)).fetchone()
        if r is None:
            raise CEError(f"investigação desconhecida: {investigation_id}")
        d = dict(r)
        for k in ("bundle", "profile_ids", "versions", "limits", "plan"):
            d[k] = json.loads(d.pop(f"{k}_json"))
        return d

    def latest(self, reference_id: str) -> Optional[str]:
        r = self.conn.execute("SELECT investigation_id FROM ce_investigations WHERE reference_id = ? ORDER BY seq DESC LIMIT 1", (reference_id,)).fetchone()
        return r["investigation_id"] if r else None

    # ---------------------------------------------------------------- aprovações e revisão humana
    def approve(self, investigation_id: str, scope: str, value: str, approver: str) -> Dict[str, Any]:
        approver = _human(approver)
        if scope not in APPROVAL_SCOPES:
            raise CEError(f"escopo inválido: {scope}")
        inv = self.get(investigation_id)
        now = self.clock.now()
        with tx(self.conn) as c:
            cur = c.execute("INSERT INTO ce_approvals(investigation_id, scope, value, approver, created_at) VALUES (?,?,?,?,?)", (investigation_id, scope, clean_text(value, 120), approver, now))
            EV.emit(c, "approval.recorded", investigation_id, {"scope": scope, "value": clean_text(value, 120), "approver": approver}, now, f"{investigation_id}|approval|{cur.lastrowid}")
            if scope == "start" and inv["state"] == "awaiting_start_approval":
                c.execute("UPDATE ce_investigations SET state = 'planned', updated_at = ? WHERE investigation_id = ?", (now, investigation_id))
        return {"investigation_id": investigation_id, "scope": scope, "approver": approver}

    def _approved(self, investigation_id: str, scope: str) -> bool:
        return self.conn.execute("SELECT 1 FROM ce_approvals WHERE investigation_id = ? AND scope = ? AND value != 'revoked' LIMIT 1", (investigation_id, scope)).fetchone() is not None

    def review(self, reference_id: str, key: str, decision: str, reviewer: str, note: Optional[str] = None, corrected_value: Optional[str] = None) -> Dict[str, Any]:
        reviewer = _human(reviewer)
        if decision not in REVIEW_DECISIONS:
            raise CEError(f"decisão inválida: {decision}")
        if decision == "correct" and not corrected_value:
            raise CEError("correção exige corrected_value")
        known = self.conn.execute("SELECT c.investigation_id FROM ce_claims c JOIN ce_investigations i ON i.investigation_id = c.investigation_id "
                                  "WHERE i.reference_id = ? AND c.key = ? ORDER BY i.seq DESC LIMIT 1", (reference_id, key)).fetchone()
        if known is None:
            raise CEError(f"chave desconhecida para a referência: {key}")
        now = self.clock.now()
        with tx(self.conn) as c:
            cur = c.execute("INSERT INTO ce_reviews(reference_id, key, decision, reviewer, note, corrected_value, created_at) VALUES (?,?,?,?,?,?,?)",
                            (reference_id, key, decision, reviewer, clean_text(note, 600) if note else None, clean_text(corrected_value, 300) if corrected_value else None, now))
            EV.emit(c, "review.registered", known["investigation_id"], {"reference_id": reference_id, "key": key, "decision": decision}, now, f"review|{cur.lastrowid}")
        return {"review_id": cur.lastrowid, "key": key, "decision": decision}

    # ---------------------------------------------------------------- execução
    def retry_blocked(self, investigation_id: str) -> int:
        now = self.clock.now()
        with tx(self.conn) as c:
            n = c.execute("UPDATE ce_tasks SET state = 'pending', error = NULL, updated_at = ? WHERE investigation_id = ? AND state IN ('blocked_provider','blocked_dependency')",
                          (now, investigation_id)).rowcount
        return n

    def _recover_expired(self, investigation_id: str) -> int:
        now = self.clock.now()
        with tx(self.conn) as c:
            c.execute("UPDATE ce_tasks SET state = 'failed', owner = NULL, lease_until = NULL, error = 'tentativas esgotadas após queda', updated_at = ? "
                      "WHERE investigation_id = ? AND state = 'running' AND lease_until < ? AND attempts >= ?", (now, investigation_id, now, self.max_attempts))
            return c.execute("UPDATE ce_tasks SET state = 'pending', owner = NULL, lease_until = NULL, updated_at = ? "
                             "WHERE investigation_id = ? AND state = 'running' AND lease_until < ?", (now, investigation_id, now)).rowcount

    def _claim_next(self, inv: Dict[str, Any], owner: str) -> Optional[sqlite3.Row]:
        limits, now = inv["limits"], self.clock.now()
        with tx(self.conn) as c:
            tasks = c.execute("SELECT * FROM ce_tasks WHERE investigation_id = ? ORDER BY rowid", (inv["investigation_id"],)).fetchall()
            state = {t["task_id"]: t["state"] for t in tasks}
            spent = sum(t["usd"] for t in tasks)
            for t in tasks:
                if t["state"] not in READY_STATES:
                    continue
                deps = [state[d] for d in json.loads(t["depends_on_json"])]
                if any(d in ("failed", "skipped", "blocked_dependency") for d in deps):
                    c.execute("UPDATE ce_tasks SET state = 'blocked_dependency', error = 'dependência não concluída', updated_at = ? WHERE task_id = ? AND state IN ('pending','awaiting_approval')", (now, t["task_id"]))
                    state[t["task_id"]] = "blocked_dependency"
                    continue
                if any(d != "done" for d in deps):
                    continue
                if t["est_usd"] > 0 and not self._approved(inv["investigation_id"], "paid_models"):
                    c.execute("UPDATE ce_tasks SET state = 'awaiting_approval', updated_at = ? WHERE task_id = ?", (now, t["task_id"]))
                    state[t["task_id"]] = "awaiting_approval"
                    continue
                if limits.get("max_usd") is not None and spent + t["est_usd"] > float(limits["max_usd"]):
                    c.execute("UPDATE ce_tasks SET state = 'skipped', error = 'limite_de_custo', updated_at = ? WHERE task_id = ?", (now, t["task_id"]))
                    state[t["task_id"]] = "skipped"
                    continue
                n = c.execute("UPDATE ce_tasks SET state = 'running', owner = ?, lease_until = ?, attempts = attempts + 1, updated_at = ? "
                              "WHERE task_id = ? AND state IN ('pending','awaiting_approval')", (owner, now + self.lease_s, now, t["task_id"])).rowcount
                if n == 1:
                    return c.execute("SELECT * FROM ce_tasks WHERE task_id = ?", (t["task_id"],)).fetchone()
        return None

    def _upstream(self, task) -> List[Dict[str, Any]]:
        out = []
        for dep in json.loads(task["depends_on_json"]):
            for r in self.conn.execute("SELECT key, kind, statement, evidence_ids_json FROM ce_claims WHERE task_id = ? AND kind IN ('tool','process','technique') ORDER BY claim_id", (dep,)):
                out.append({"key": r["key"], "kind": r["kind"], "statement": r["statement"], "evidence_ids": json.loads(r["evidence_ids_json"])})
        return out

    def run(self, investigation_id: str, owner: str = "worker:ce-main", max_tasks: Optional[int] = None, retry_blocked: bool = False) -> Dict[str, Any]:
        inv = self.get(investigation_id)
        if inv["state"] in ("blocked_no_evidence", "superseded"):
            return {"investigation_id": investigation_id, "state": inv["state"], "executed": 0}
        if inv["state"] == "awaiting_start_approval":
            return {"investigation_id": investigation_id, "state": "awaiting_start_approval", "executed": 0}
        if retry_blocked:
            self.retry_blocked(investigation_id)
        self._recover_expired(investigation_id)
        executed = 0
        while max_tasks is None or executed < max_tasks:
            task = self._claim_next(inv, owner)
            if task is None:
                break
            self._execute(inv, task, owner)
            executed += 1
        return {"investigation_id": investigation_id, "executed": executed, "state": self._settle(inv)}

    def _execute(self, inv: Dict[str, Any], task, owner: str) -> None:
        bundle, spec, tid = inv["bundle"], task["specialist"], task["task_id"]
        upstream = self._upstream(task)
        evidence = select_for(spec, bundle, upstream)
        outcome = self.gateway.execute(tid, spec, evidence, bundle, upstream, deadline_s=float(inv["limits"].get("deadline_s", self.deadline_s)))
        now = self.clock.now()
        with tx(self.conn) as c:
            if outcome.status == "ok":
                n = c.execute("UPDATE ce_tasks SET state = 'done', usd = ?, evidence_ids_json = ?, input_digest = ?, error = NULL, owner = NULL, lease_until = NULL, result_json = ?, updated_at = ? "
                              "WHERE task_id = ? AND state = 'running' AND owner = ?",
                              (outcome.usd, json.dumps([e["id"] for e in evidence]), digest([e["id"] for e in evidence], upstream),
                               canonical_json({"questions": outcome.questions, "notes": outcome.notes, "provenance": outcome.provenance}), now, tid, owner)).rowcount
                if n == 1:  # só quem ainda detém o lease grava (evita escrita de executor que perdeu a tarefa)
                    for cl in outcome.claims:
                        cid = digest(tid, cl["key"], cl["value"], cl["statement"])
                        c.execute("INSERT OR IGNORE INTO ce_claims(claim_id, investigation_id, task_id, specialist, domain, kind, key, value, statement, evidence_ids_json, confidence, created_at) "
                                  "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", (cid, inv["investigation_id"], tid, spec, cl["domain"], cl["kind"], cl["key"], cl["value"], cl["statement"],
                                                                        json.dumps(cl["evidence_ids"]), cl["confidence"], now))
                    EV.emit(c, "task.completed", inv["investigation_id"], {"specialist": spec, "claims": len(outcome.claims), "usd": outcome.usd}, now, tid)
            elif outcome.status == "blocked_provider":
                c.execute("UPDATE ce_tasks SET state = 'blocked_provider', error = ?, owner = NULL, lease_until = NULL, updated_at = ? WHERE task_id = ? AND state = 'running' AND owner = ?",
                          (clean_text(outcome.error, 300), now, tid, owner))
                EV.emit(c, "task.blocked", inv["investigation_id"], {"specialist": spec, "reason": "provider_unavailable"}, now, f"{tid}|blocked|{task['attempts']}")
            else:
                final = task["attempts"] >= self.max_attempts
                c.execute("UPDATE ce_tasks SET state = ?, error = ?, owner = NULL, lease_until = NULL, updated_at = ? WHERE task_id = ? AND state = 'running' AND owner = ?",
                          ("failed" if final else "pending", clean_text(outcome.error, 300), now, tid, owner))
                if final:
                    EV.emit(c, "task.failed", inv["investigation_id"], {"specialist": spec, "error": clean_text(outcome.error, 200)}, now, tid)

    def _settle(self, inv: Dict[str, Any]) -> str:
        iid = inv["investigation_id"]
        tasks = [dict(t) for t in self.conn.execute("SELECT specialist, state FROM ce_tasks WHERE investigation_id = ?", (iid,))]
        wanted = [t for t in tasks if t["state"] != "skipped" or True]
        done = [t for t in tasks if t["state"] == "done"]
        open_ = [t for t in tasks if t["state"] in ("pending", "running")]
        stuck = [t for t in tasks if t["state"] in ("blocked_provider", "blocked_dependency", "awaiting_approval", "failed")]
        if not tasks or all(t["state"] == "skipped" for t in tasks):
            state = "blocked" if tasks else "planned"
        elif open_:
            state = "running"
        elif stuck and done:
            state = "partial"
        elif stuck:
            state = "blocked"
        else:
            state = "complete"
        now = self.clock.now()
        reconcile(self.conn, iid, inv["bundle"])
        with tx(self.conn) as c:
            c.execute("UPDATE ce_investigations SET state = ?, updated_at = ? WHERE investigation_id = ? AND state != 'superseded'", (state, now, iid))
            if state in ("partial", "complete"):
                EV.emit(c, "investigation.completed" if state == "complete" else "investigation.partial", iid,
                        {"state": state, "done": len(done), "stuck": [t["specialist"] for t in stuck]}, now, f"{iid}|{state}|{len(done)}|{len(stuck)}")
        return state

    # ---------------------------------------------------------------- leitura
    def groups(self, investigation_id: str) -> List[Dict[str, Any]]:
        return reconcile(self.conn, investigation_id, self.get(investigation_id)["bundle"])

    def status(self, investigation_id: str) -> Dict[str, Any]:
        inv = self.get(investigation_id)
        tasks = [dict(t) for t in self.conn.execute("SELECT specialist, kind, state, attempts, usd, est_usd, reason, error FROM ce_tasks WHERE investigation_id = ? ORDER BY rowid", (investigation_id,))]
        selected = [t for t in tasks if t["state"] != "skipped" or t["error"] == "limite_de_custo"]
        done = sum(1 for t in tasks if t["state"] == "done")
        groups = self.groups(investigation_id)
        by_state: Dict[str, int] = {}
        for g in groups:
            by_state[g["state"]] = by_state.get(g["state"], 0) + 1
        dossier = self.conn.execute("SELECT version, content_hash FROM ce_dossiers WHERE investigation_id = ? ORDER BY version DESC LIMIT 1", (investigation_id,)).fetchone()
        approved = bool(dossier and self.conn.execute("SELECT 1 FROM ce_approvals WHERE investigation_id = ? AND scope = 'dossier' AND value = ?", (investigation_id, dossier["content_hash"])).fetchone())
        return {"schema_version": "ii.ce.status.v1", "investigation_id": investigation_id, "reference_id": inv["reference_id"], "seq": inv["seq"], "state": inv["state"],
                "depth": inv["depth"], "reference_kind": inv["plan"]["reference_kind"], "tasks": tasks,
                "progress": {"done": done, "planned": len([t for t in tasks if t["state"] != "skipped"]), "skipped": len(tasks) - len([t for t in tasks if t["state"] != "skipped"])},
                "usd_spent": round(sum(t["usd"] for t in tasks), 4), "groups": by_state, "conflicts": [g["key"] for g in groups if g["conflict"]],
                "pending_approvals": (["start"] if inv["state"] == "awaiting_start_approval" else []) + (["paid_models"] if any(t["state"] == "awaiting_approval" for t in tasks) else []),
                "dossier": {"version": dossier["version"] if dossier else None, "approved": approved},
                "awaiting_human": bool(dossier and not approved)}

    def investigation_object(self, investigation_id: str) -> Dict[str, Any]:
        """Objeto de investigação (contrato ii.ce.investigation.v1): identificadores, versões, evidências, etapas, análises, revisões, dossiê."""
        inv = self.get(investigation_id)
        b = inv["bundle"]
        tasks = [dict(t) for t in self.conn.execute("SELECT specialist, kind, state FROM ce_tasks WHERE investigation_id = ?", (investigation_id,))]
        counts: Dict[str, int] = {}
        for e in b["evidence"]:
            counts[e["status"]] = counts.get(e["status"], 0) + 1
        claims = {d: 0 for d in DOMAINS}
        for r in self.conn.execute("SELECT domain, COUNT(*) n FROM ce_claims WHERE investigation_id = ? GROUP BY domain", (investigation_id,)):
            claims[r["domain"]] = r["n"]
        dossiers = [dict(r) for r in self.conn.execute("SELECT version, content_hash FROM ce_dossiers WHERE investigation_id = ? ORDER BY version", (investigation_id,))]
        prev = [r["investigation_id"] for r in self.conn.execute("SELECT investigation_id FROM ce_investigations WHERE reference_id = ? AND seq < ? ORDER BY seq", (inv["reference_id"], inv["seq"]))]
        return {"schema_version": SCHEMA_INVESTIGATION, "investigation_id": investigation_id, "seq": inv["seq"], "supersedes": inv["supersedes"], "previous": prev,
                "reference_id": inv["reference_id"], "media": {"sha256": b["media_sha256"]}, "content_hash": inv["content_hash"], "input_hash": inv["input_hash"],
                "versions": inv["versions"], "depth": inv["depth"], "state": inv["state"], "evidence": {"total": len(b["evidence"]), "by_status": counts},
                "stages": {"done": [t["specialist"] for t in tasks if t["state"] == "done"],
                           "pending": [t["specialist"] for t in tasks if t["state"] in ("pending", "running", "awaiting_approval", "blocked_provider", "blocked_dependency")],
                           "skipped": [t["specialist"] for t in tasks if t["state"] == "skipped"], "failed": [t["specialist"] for t in tasks if t["state"] == "failed"]},
                "analyses": {"claims_by_domain": claims}, "human_reviews": len(latest_reviews(self.conn, inv["reference_id"])),
                "dossier_versions": dossiers, "dossier_version": dossiers[-1]["version"] if dossiers else None}

    # ---------------------------------------------------------------- saídas (dossiê, Obsidian, eventos)
    def generate_dossier(self, investigation_id: str, out_dir: Path) -> Dict[str, Any]:
        from .dossier import write_dossier
        return write_dossier(self, investigation_id, Path(out_dir))

    def export_obsidian(self, investigation_id: str, staging_dir: Path) -> Dict[str, Any]:
        from .obsidian import export_investigation
        return export_investigation(self, investigation_id, Path(staging_dir))

    def drain_events(self, consumer: str, handler) -> int:
        return EV.drain(self.conn, consumer, handler, self.clock.now())

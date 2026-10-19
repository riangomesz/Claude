"""Fila persistente de jobs em SQLite (Tarefa 05).

Estados: queued → claimed → running → completed
                          ↘ retry_scheduled ↺ / waiting_dependency ↺ / failed / dead_letter / cancelled

- Toda transição acontece numa transação `BEGIN IMMEDIATE` (serializa vários processos e threads).
- Posse e lease com a MESMA semântica do `ii_mm.pipeline` (e a mesma exceção `LeaseLost`): dono, `lease_until`,
  `heartbeat()` renova; quem perdeu a posse não grava nada (nem resultado, nem falha).
- Lease vencido é recuperado no próximo `claim` de qualquer worker: a tentativa vira `lease_lost` e o job volta
  para `retry_scheduled` (ou `dead_letter` se esgotou), sem perder o histórico.
- Dedup de solicitações: no máximo um job ATIVO por `dedup_key` (índice único parcial). Pedir de novo devolve o
  job existente.
- Dependências: um job só é assumido quando TODAS as dependências estão `completed`. Cancelar um job cancela em
  cascata os dependentes que ainda não começaram. Dependência que falhou deixa os dependentes bloqueados
  (`waiting_dependency`) e visíveis no diagnóstico até um `requeue` da dependência.
- Concorrência limitada: `max_running` global e `kind_limits` por tipo, contados na mesma transação do claim.
- Cancelamento de job em execução é cooperativo (`cancel_requested`, lido no heartbeat); um job cancelado nunca
  grava resultado, mesmo se o handler terminar depois.

Relação com o `ii_mm`: a fila é a autoridade sobre EXECUÇÃO (tentativas, agendamento, posse). O estado de
processamento da referência é DERIVADO dos jobs e dos resultados de etapa (ver `scheduler.processing_view`),
com os nomes de etapa do `ii_mm.pipeline.STAGES` para compatibilidade. O backend não escreve em
`processing_state`: duas máquinas gravando a mesma tabela seriam duas autoridades.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Optional

from . import _ii_mm  # noqa: F401
from ii_mm.pipeline import LeaseLost
from .db import tx
from .errors import Decision, RetryPolicy, classify_exception, safe_message
from .events import emit

ACTIVE = ("queued", "claimed", "running", "waiting_dependency", "retry_scheduled")
# Literais idênticos aos dos índices parciais (o SQLite só usa o índice se o termo da consulta for o mesmo).
NOT_TERMINAL_SQL = "state NOT IN ('completed','failed','cancelled','dead_letter')"
CLAIM_SQL = "j.state IN ('queued','retry_scheduled','waiting_dependency') AND j.blocked_deps = 0 AND j.cancel_requested = 0"
TERMINAL = ("completed", "failed", "cancelled", "dead_letter")
CLAIMABLE = ("queued", "retry_scheduled", "waiting_dependency")
OUTCOME_FOR = {"retry_scheduled": "retry", "waiting_dependency": "waiting_dependency", "failed": "failed",
               "dead_letter": "dead_letter"}

__all__ = ["JobQueue", "Job", "LeaseLost"]


@dataclass
class Job:
    job_id: str
    kind: str
    reference_id: Optional[str]
    stage: Optional[str]
    run_id: Optional[str]
    state: str
    attempts: int
    priority: int
    payload: Dict[str, Any] = field(default_factory=dict)
    lease_owner: Optional[str] = None
    lease_until: Optional[float] = None
    dedup_key: Optional[str] = None

    @classmethod
    def from_row(cls, r: sqlite3.Row) -> "Job":
        return cls(r["job_id"], r["kind"], r["reference_id"], r["stage"], r["run_id"], r["state"], r["attempts"],
                   r["priority"], json.loads(r["payload_json"] or "{}"), r["lease_owner"], r["lease_until"], r["dedup_key"])


@dataclass
class EnqueueResult:
    job_id: str
    created: bool
    state: str


class JobQueue:
    def __init__(self, conn: sqlite3.Connection, clock, policy: Optional[RetryPolicy] = None, lease_s: float = 300.0,
                 max_running: Optional[int] = None, kind_limits: Optional[Dict[str, int]] = None):
        if conn.isolation_level is not None:
            raise ValueError("use db.open_engine_db()/connect(): a fila exige transações explícitas")
        self.conn, self.clock = conn, clock
        self.policy = policy or RetryPolicy()
        self.lease_s, self.max_running = lease_s, max_running
        self.kind_limits = dict(kind_limits or {})

    # ------------------------------------------------------------------ criação
    def _new_id(self, c: sqlite3.Connection, base: str) -> str:
        n = 0
        while True:
            jid = "job_" + hashlib.sha256(f"{base}|{n}".encode()).hexdigest()[:20]
            if not c.execute("SELECT 1 FROM be_jobs WHERE job_id = ?", (jid,)).fetchone():
                return jid
            n += 1

    def enqueue_in(self, c: sqlite3.Connection, kind: str, reference_id: Optional[str] = None, stage: Optional[str] = None,
                   payload: Optional[Dict[str, Any]] = None, priority: int = 100, dedup_key: Optional[str] = None,
                   depends_on: Iterable[str] = (), max_attempts: int = 5, run_id: Optional[str] = None,
                   delay_s: float = 0.0) -> EnqueueResult:
        """Enfileira dentro da transação do chamador (ex.: o planner cria o grafo inteiro de uma vez)."""
        if not c.in_transaction:
            raise RuntimeError("enqueue_in exige transação aberta")
        if not kind or len(kind) > 64:
            raise ValueError("kind inválido")
        if not 1 <= int(max_attempts) <= 50:
            raise ValueError("max_attempts fora de 1..50")
        if dedup_key:
            row = c.execute(f"SELECT job_id, state FROM be_jobs WHERE dedup_key = ? AND {NOT_TERMINAL_SQL}", (dedup_key,)).fetchone()
            if row:
                return EnqueueResult(row["job_id"], False, row["state"])
        deps = list(dict.fromkeys(depends_on))
        dep_states = {}
        for d in deps:
            r = c.execute("SELECT state FROM be_jobs WHERE job_id = ?", (d,)).fetchone()
            if r is None:
                raise ValueError(f"dependência inexistente: {d}")
            dep_states[d] = r["state"]
        now = self.clock.now()
        jid = self._new_id(c, f"{kind}|{reference_id}|{stage}|{run_id}|{dedup_key}|{now!r}")
        blocked = sum(1 for s in dep_states.values() if s != "completed")
        state = "queued" if blocked == 0 else "waiting_dependency"
        c.execute("INSERT INTO be_jobs(job_id, kind, reference_id, stage, run_id, dedup_key, priority, state, max_attempts, not_before, "
                  "payload_json, created_at, updated_at, blocked_deps) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (jid, kind, reference_id, stage, run_id, dedup_key, int(priority), state, int(max_attempts), now + max(0.0, delay_s),
                   json.dumps(payload or {}, ensure_ascii=False, sort_keys=True), now, now, blocked))
        c.executemany("INSERT INTO be_job_deps(job_id, depends_on) VALUES (?,?)", [(jid, d) for d in deps])
        return EnqueueResult(jid, True, state)

    def enqueue(self, kind: str, **kw) -> EnqueueResult:
        try:
            with tx(self.conn) as c:
                return self.enqueue_in(c, kind, **kw)
        except sqlite3.IntegrityError:
            # corrida entre dois produtores com a mesma dedup_key: o índice único garantiu um só; devolve o vencedor
            if kw.get("dedup_key"):
                row = self.conn.execute(f"SELECT job_id, state FROM be_jobs WHERE dedup_key = ? AND {NOT_TERMINAL_SQL}",
                                        (kw["dedup_key"],)).fetchone()
                if row:
                    return EnqueueResult(row["job_id"], False, row["state"])
            raise

    # ------------------------------------------------------------------ posse
    def _recover_expired(self, c: sqlite3.Connection, now: float) -> int:
        rows = c.execute("SELECT * FROM be_jobs WHERE state IN ('claimed','running') AND lease_until < ?", (now,)).fetchall()
        for r in rows:
            if r["cancel_requested"]:
                self._finish_attempt(c, r["job_id"], r["attempts"], "cancelled", now, "lease_lost", "cancelado; dono perdeu o lease")
                c.execute("UPDATE be_jobs SET state='cancelled', lease_owner=NULL, lease_until=NULL, updated_at=?, finished_at=? WHERE job_id=?",
                          (now, now, r["job_id"]))
                self._cascade_cancel(c, r["job_id"], now)
                continue
            failures = r["failures"] + 1
            d = self.policy.decide("lease_lost", failures, r["max_attempts"])
            self._finish_attempt(c, r["job_id"], r["attempts"], "lease_lost", now, "lease_lost", f"lease de {r['lease_owner']} expirou")
            c.execute("UPDATE be_jobs SET state=?, failures=?, not_before=?, lease_owner=NULL, lease_until=NULL, last_error_class='lease_lost', "
                      "last_error=?, updated_at=? WHERE job_id=?",
                      (d.state, failures, now + d.delay_s, f"lease de {r['lease_owner']} expirou ({d.reason})", now, r["job_id"]))
            if d.state == "dead_letter":
                emit(c, "job.dead_letter", r["reference_id"], {"job_id": r["job_id"], "stage": r["stage"], "reason": d.reason},
                     now, dedup_key=f"dead|{r['job_id']}|{r['attempts']}")
        return len(rows)

    def recover_expired(self) -> int:
        with tx(self.conn) as c:
            return self._recover_expired(c, self.clock.now())

    def claim(self, owner: str, kinds: Optional[Iterable[str]] = None) -> Optional[Job]:
        kinds = list(kinds) if kinds else None
        with tx(self.conn) as c:
            now = self.clock.now()
            self._recover_expired(c, now)
            running = {r["kind"]: r["n"] for r in c.execute(
                "SELECT kind, COUNT(*) AS n FROM be_jobs WHERE state IN ('claimed','running') GROUP BY kind")}
            if self.max_running is not None and sum(running.values()) >= self.max_running:
                return None
            full = [k for k, lim in self.kind_limits.items() if running.get(k, 0) >= lim]
            where = [CLAIM_SQL, "j.not_before <= ?"]
            args: List[Any] = [now]
            if kinds:
                where.append(f"j.kind IN ({','.join('?' * len(kinds))})"); args += kinds
            if full:
                where.append(f"j.kind NOT IN ({','.join('?' * len(full))})"); args += full
            row = c.execute(f"SELECT j.* FROM be_jobs j INDEXED BY idx_be_jobs_claim WHERE {' AND '.join(where)} "
                            "ORDER BY j.priority, j.not_before, j.created_at, j.job_id LIMIT 1", args).fetchone()
            if row is None:
                return None
            attempt = row["attempts"] + 1
            c.execute("UPDATE be_jobs SET state='claimed', lease_owner=?, lease_until=?, attempts=?, updated_at=? WHERE job_id=?",
                      (owner, now + self.lease_s, attempt, now, row["job_id"]))
            c.execute("INSERT INTO be_job_attempts(job_id, attempt_no, owner, started_at) VALUES (?,?,?,?)",
                      (row["job_id"], attempt, owner, now))
            return Job.from_row(c.execute("SELECT * FROM be_jobs WHERE job_id = ?", (row["job_id"],)).fetchone())

    def _owned(self, c: sqlite3.Connection, job_id: str, owner: str) -> sqlite3.Row:
        r = c.execute("SELECT * FROM be_jobs WHERE job_id = ?", (job_id,)).fetchone()
        if r is None or r["lease_owner"] != owner or r["state"] not in ("claimed", "running"):
            raise LeaseLost(f"{job_id}: posse perdida (estado {r['state'] if r else 'inexistente'}, dono {r['lease_owner'] if r else '-'})")
        return r

    def mark_running(self, job_id: str, owner: str) -> None:
        with tx(self.conn) as c:
            now = self.clock.now()
            self._owned(c, job_id, owner)
            c.execute("UPDATE be_jobs SET state='running', started_at=COALESCE(started_at, ?), lease_until=?, updated_at=? WHERE job_id=?",
                      (now, now + self.lease_s, now, job_id))

    def heartbeat(self, job_id: str, owner: str) -> bool:
        """Renova o lease. Devolve True se houve pedido de cancelamento. Levanta LeaseLost se a posse se foi."""
        with tx(self.conn) as c:
            now = self.clock.now()
            r = self._owned(c, job_id, owner)  # lease vencido mas ainda não recuperado por outro: o dono pode renovar
            c.execute("UPDATE be_jobs SET lease_until=?, updated_at=? WHERE job_id=?", (now + self.lease_s, now, job_id))
            return bool(r["cancel_requested"])

    # ------------------------------------------------------------------ conclusão
    def _finish_attempt(self, c, job_id, attempt_no, outcome, now, error_class=None, error=None) -> None:
        c.execute("UPDATE be_job_attempts SET finished_at=?, outcome=?, error_class=?, error=? WHERE job_id=? AND attempt_no=? AND finished_at IS NULL",
                  (now, outcome, error_class, error, job_id, attempt_no))

    def _promote_dependents(self, c, job_id, now) -> None:
        for d in c.execute("SELECT job_id FROM be_job_deps WHERE depends_on = ?", (job_id,)).fetchall():
            pending = c.execute("SELECT COUNT(*) FROM be_job_deps d JOIN be_jobs p ON p.job_id = d.depends_on "
                                "WHERE d.job_id = ? AND p.state <> 'completed'", (d["job_id"],)).fetchone()[0]
            c.execute("UPDATE be_jobs SET blocked_deps=?, updated_at=? WHERE job_id=?", (pending, now, d["job_id"]))
            if pending == 0:
                c.execute("UPDATE be_jobs SET state='queued', updated_at=? WHERE job_id=? AND state='waiting_dependency'", (now, d["job_id"]))

    def complete(self, job_id: str, owner: str, result: Optional[Dict[str, Any]] = None,
                 effects: Optional[Callable[[sqlite3.Connection], None]] = None, reused: bool = False) -> str:
        """Conclui. `effects(c)` roda na MESMA transação (resultado da etapa, eventos): tudo ou nada.
        Devolve o estado final (`completed` ou `cancelled` se houve pedido de cancelamento)."""
        with tx(self.conn) as c:
            now = self.clock.now()
            r = self._owned(c, job_id, owner)
            if r["cancel_requested"]:
                self._finish_attempt(c, job_id, r["attempts"], "cancelled", now, "cancelled", "cancelado antes de gravar o resultado")
                c.execute("UPDATE be_jobs SET state='cancelled', lease_owner=NULL, lease_until=NULL, updated_at=?, finished_at=? WHERE job_id=?",
                          (now, now, job_id))
                self._cascade_cancel(c, job_id, now)
                return "cancelled"
            if effects:
                effects(c)
            c.execute("UPDATE be_jobs SET state='completed', result_json=?, lease_owner=NULL, lease_until=NULL, updated_at=?, finished_at=?, "
                      "last_error_class=NULL, last_error=NULL WHERE job_id=?",
                      (json.dumps(result or {}, ensure_ascii=False, sort_keys=True), now, now, job_id))
            self._finish_attempt(c, job_id, r["attempts"], "reused" if reused else "completed", now)
            self._promote_dependents(c, job_id, now)
            return "completed"

    def fail(self, job_id: str, owner: str, exc: BaseException) -> Decision:
        cls = classify_exception(exc)
        msg = safe_message(exc)
        with tx(self.conn) as c:
            now = self.clock.now()
            r = self._owned(c, job_id, owner)
            if cls == "cancelled" or r["cancel_requested"]:
                self._finish_attempt(c, job_id, r["attempts"], "cancelled", now, "cancelled", msg)
                c.execute("UPDATE be_jobs SET state='cancelled', lease_owner=NULL, lease_until=NULL, updated_at=?, finished_at=?, "
                          "last_error_class='cancelled', last_error=? WHERE job_id=?", (now, now, msg, job_id))
                self._cascade_cancel(c, job_id, now)
                return Decision("cancelled", reason="cancelado")
            counts = cls not in ("resource_busy", "dependency_missing")
            failures = r["failures"] + (1 if counts else 0)
            d = self.policy.decide(cls, failures, r["max_attempts"], r["busy_retries"], r["dependency_waits"])
            outcome = "busy" if cls == "resource_busy" and d.state == "retry_scheduled" else OUTCOME_FOR.get(d.state, "failed")
            if cls == "timeout" and d.state == "retry_scheduled":
                outcome = "timeout"
            self._finish_attempt(c, job_id, r["attempts"], outcome, now, cls, msg)
            c.execute("UPDATE be_jobs SET state=?, failures=?, busy_retries=busy_retries+?, dependency_waits=dependency_waits+?, "
                      "not_before=?, lease_owner=NULL, lease_until=NULL, last_error_class=?, last_error=?, updated_at=?, "
                      "finished_at=CASE WHEN ? IN ('failed','dead_letter') THEN ? ELSE finished_at END WHERE job_id=?",
                      (d.state, failures, 1 if cls == "resource_busy" else 0, 1 if cls == "dependency_missing" else 0,
                       now + d.delay_s, cls, f"{msg} [{d.reason}]"[:500], now, d.state, now, job_id))
            if d.state == "dead_letter":
                emit(c, "job.dead_letter", r["reference_id"], {"job_id": job_id, "stage": r["stage"], "error_class": cls, "reason": d.reason},
                     now, dedup_key=f"dead|{job_id}|{r['attempts']}")
            return d

    # ------------------------------------------------------------------ operação
    def _cascade_cancel(self, c, job_id, now) -> List[str]:
        out = []
        stack = [job_id]
        while stack:
            cur = stack.pop()
            for d in c.execute("SELECT d.job_id FROM be_job_deps d JOIN be_jobs j ON j.job_id = d.job_id "
                               "WHERE d.depends_on = ? AND j.state IN ('queued','waiting_dependency','retry_scheduled')", (cur,)).fetchall():
                c.execute("UPDATE be_jobs SET state='cancelled', last_error_class='cancelled', last_error=?, updated_at=?, finished_at=? WHERE job_id=?",
                          (f"dependência {cur} cancelada", now, now, d["job_id"]))
                out.append(d["job_id"])
                stack.append(d["job_id"])
        return out

    def cancel(self, job_id: str, reason: str = "cancelado pelo operador") -> str:
        with tx(self.conn) as c:
            now = self.clock.now()
            r = c.execute("SELECT state FROM be_jobs WHERE job_id = ?", (job_id,)).fetchone()
            if r is None:
                raise ValueError(f"job inexistente: {job_id}")
            if r["state"] in ("queued", "waiting_dependency", "retry_scheduled"):
                c.execute("UPDATE be_jobs SET state='cancelled', last_error_class='cancelled', last_error=?, updated_at=?, finished_at=? WHERE job_id=?",
                          (reason[:300], now, now, job_id))
                self._cascade_cancel(c, job_id, now)
                return "cancelled"
            if r["state"] in ("claimed", "running"):
                c.execute("UPDATE be_jobs SET cancel_requested=1, updated_at=? WHERE job_id=?", (now, job_id))
                return "cancel_requested"
            return r["state"]

    def requeue(self, job_id: str) -> str:
        """Operador devolve à fila um job `failed`/`dead_letter`/`cancelled` (histórico de tentativas preservado).
        Mantém o mesmo id: os dependentes bloqueados voltam a andar quando ele concluir."""
        with tx(self.conn) as c:
            now = self.clock.now()
            r = c.execute("SELECT state, dedup_key FROM be_jobs WHERE job_id = ?", (job_id,)).fetchone()
            if r is None:
                raise ValueError(f"job inexistente: {job_id}")
            if r["state"] not in ("failed", "dead_letter", "cancelled"):
                return r["state"]
            if r["dedup_key"] and c.execute(f"SELECT 1 FROM be_jobs WHERE dedup_key = ? AND job_id <> ? AND {NOT_TERMINAL_SQL}",
                                            (r["dedup_key"], job_id)).fetchone():
                return "superseded_by_active"
            c.execute("UPDATE be_jobs SET state='queued', failures=0, busy_retries=0, dependency_waits=0, cancel_requested=0, not_before=?, "
                      "last_error_class=NULL, last_error=NULL, finished_at=NULL, updated_at=? WHERE job_id=?", (now, now, job_id))
            for d in c.execute("SELECT job_id FROM be_job_deps WHERE depends_on = ?", (job_id,)).fetchall():
                c.execute("UPDATE be_jobs SET state='waiting_dependency', updated_at=? WHERE job_id=? AND state='cancelled' "
                          "AND last_error LIKE 'dependência %'", (now, d["job_id"]))
            return "queued"

    def reschedule(self, job_id: str, delay_s: Optional[float] = None, priority: Optional[int] = None) -> str:
        with tx(self.conn) as c:
            now = self.clock.now()
            r = c.execute("SELECT state FROM be_jobs WHERE job_id = ?", (job_id,)).fetchone()
            if r is None or r["state"] not in CLAIMABLE:
                return r["state"] if r else "inexistente"
            if delay_s is not None:
                c.execute("UPDATE be_jobs SET not_before=?, updated_at=? WHERE job_id=?", (now + max(0.0, delay_s), now, job_id))
            if priority is not None:
                c.execute("UPDATE be_jobs SET priority=?, updated_at=? WHERE job_id=?", (int(priority), now, job_id))
            return r["state"]

    # ------------------------------------------------------------------ leitura
    def get(self, job_id: str) -> Optional[Dict[str, Any]]:
        r = self.conn.execute("SELECT * FROM be_jobs WHERE job_id = ?", (job_id,)).fetchone()
        if r is None:
            return None
        out = dict(r)
        out["payload"] = json.loads(out.pop("payload_json") or "{}")
        out["result"] = json.loads(out.pop("result_json")) if out.get("result_json") else None
        out["depends_on"] = [d[0] for d in self.conn.execute("SELECT depends_on FROM be_job_deps WHERE job_id = ? ORDER BY depends_on", (job_id,))]
        return out

    def attempts(self, job_id: str) -> List[Dict[str, Any]]:
        return [dict(r) for r in self.conn.execute("SELECT * FROM be_job_attempts WHERE job_id = ? ORDER BY attempt_no", (job_id,))]

    def counts(self) -> Dict[str, int]:
        return {r["state"]: r["n"] for r in self.conn.execute("SELECT state, COUNT(*) AS n FROM be_jobs GROUP BY state ORDER BY state")}

    def blocked(self) -> List[Dict[str, Any]]:
        """Jobs esperando dependência que não vai concluir sozinha (falhou, dead_letter ou cancelada)."""
        return [dict(r) for r in self.conn.execute(
            "SELECT j.job_id, j.stage, j.reference_id, p.job_id AS blocked_by, p.state AS blocked_by_state FROM be_jobs j "
            "JOIN be_job_deps d ON d.job_id = j.job_id JOIN be_jobs p ON p.job_id = d.depends_on "
            "WHERE j.state = 'waiting_dependency' AND p.state IN ('failed','dead_letter','cancelled') ORDER BY j.job_id")]

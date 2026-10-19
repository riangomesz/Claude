"""Máquina de estados idempotente do processamento audiovisual (Tarefa 09).

Etapas (ordem fixa):
    discovered → media_available → metadata_extracted → audio_processed → visual_processed
    → evidence_normalized → classified → awaiting_review → completed      (+ failed)

Cada etapa grava em `processing_state` o status (running/done/failed), tentativas, o `input_hash`
e a referência de saída. Regras:
- Etapa `done` com o mesmo input_hash não é repetida.
- O input_hash de uma etapa encadeia as saídas das anteriores; se uma etapa anterior muda de saída,
  as seguintes rodam de novo automaticamente.
- `force={"etapa"}` refaz explicitamente essa etapa e as seguintes.
- Interrupção (KeyboardInterrupt/SystemExit) deixa a etapa como `running`; a próxima execução a retoma.
- Exceção comum marca `failed` com a mensagem; nova execução tenta de novo até `max_attempts`.
- `awaiting_review` só conclui quando o handler devolve uma saída (ex.: id da revisão); `None` = aguardando.
- Posse e lease (Missão Suprema 02): cada executor tem um `owner`. Uma etapa `running` de OUTRO dono com lease
  válido não é tocada (estado `busy`); lease vencido (dono caiu) libera a retomada; o mesmo dono retoma na hora.
- Heartbeat (Missão Suprema 03): etapa mais longa que o lease chama `ctx.heartbeat()` para renová-lo; se a posse
  já foi perdida, levanta `LeaseLost`. Ao concluir, a posse é conferida antes de gravar: quem perdeu o lease não
  sobrescreve o estado de quem assumiu.
"""
from __future__ import annotations

import hashlib
import sqlite3
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Dict, Iterable, List, Optional

STAGES = ("discovered", "media_available", "metadata_extracted", "audio_processed", "visual_processed",
          "evidence_normalized", "classified", "awaiting_review", "completed")
TERMINAL_FAILED = "failed"

Handler = Callable[["StageContext"], Optional[str]]


class LeaseLost(RuntimeError):
    """O lease desta etapa expirou e outro executor assumiu; o trabalho em andamento deve parar."""


@dataclass
class StageContext:
    video_pk: int
    stage: str
    upstream: Dict[str, str]
    attempt: int
    heartbeat: Callable[[], None] = lambda: None  # etapas longas chamam periodicamente para renovar o lease


@dataclass
class RunReport:
    video_pk: int
    executed: List[str] = field(default_factory=list)
    skipped: List[str] = field(default_factory=list)
    state: str = "discovered"
    waiting_on: Optional[str] = None
    error: Optional[str] = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


class Pipeline:
    def __init__(self, conn: sqlite3.Connection, handlers: Dict[str, Handler], max_attempts: int = 3,
                 owner: Optional[str] = None, lease_s: float = 600.0, clock: Callable[[], float] = time.time):
        unknown = set(handlers) - set(STAGES)
        if unknown:
            raise ValueError(f"etapas desconhecidas: {sorted(unknown)}")
        missing = [s for s in STAGES if s not in handlers]
        if missing:
            raise ValueError(f"faltam handlers para: {missing}")
        if conn.isolation_level is not None:
            raise ValueError("use migrations.connect() (transações explícitas)")
        self.conn, self.handlers, self.max_attempts = conn, handlers, max_attempts
        self.owner = owner or f"runner-{uuid.uuid4().hex[:8]}"
        self.lease_s, self.clock = lease_s, clock

    def _row(self, video_pk: int, stage: str):
        return self.conn.execute("SELECT * FROM processing_state WHERE video_pk = ? AND stage = ?", (video_pk, stage)).fetchone()

    def _renew(self, video_pk: int, stage: str) -> None:
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            cur = self.conn.execute("UPDATE processing_state SET lease_until = ?, updated_at = ? WHERE video_pk = ? AND stage = ? "
                                    "AND status = 'running' AND owner = ?", (self.clock() + self.lease_s, _now(), video_pk, stage, self.owner))
            self.conn.execute("COMMIT")
        except BaseException:
            if self.conn.in_transaction:
                self.conn.execute("ROLLBACK")
            raise
        if cur.rowcount != 1:
            raise LeaseLost(f"{stage}: posse perdida para outro executor")

    def _still_owner(self, video_pk: int, stage: str) -> bool:
        row = self.conn.execute("SELECT owner, status FROM processing_state WHERE video_pk = ? AND stage = ?", (video_pk, stage)).fetchone()
        return bool(row) and row["owner"] == self.owner and row["status"] == "running"

    def _write(self, video_pk: int, stage: str, status: str, attempt: int, input_hash: str,
               output_ref: Optional[str] = None, error: Optional[str] = None, claim: bool = False) -> Optional[str]:
        """Grava o estado. Com `claim=True`, só grava se a etapa não estiver com lease válido de OUTRO dono;
        devolve o dono atual nesse caso (e não grava). Leitura e escrita na mesma transação IMMEDIATE."""
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            if claim:
                row = self.conn.execute("SELECT status, owner, lease_until FROM processing_state WHERE video_pk = ? AND stage = ?",
                                        (video_pk, stage)).fetchone()
                if row and row["status"] == "running" and row["owner"] not in (None, self.owner) \
                        and (row["lease_until"] or 0) > self.clock():
                    self.conn.execute("ROLLBACK")
                    return row["owner"]
            lease = self.clock() + self.lease_s if status == "running" else None
            self.conn.execute(
                "INSERT INTO processing_state(video_pk, stage, status, attempt, input_hash, output_ref, error, updated_at, owner, lease_until) "
                "VALUES (?,?,?,?,?,?,?,?,?,?) ON CONFLICT(video_pk, stage) DO UPDATE SET status=excluded.status, "
                "attempt=excluded.attempt, input_hash=excluded.input_hash, output_ref=excluded.output_ref, "
                "error=excluded.error, updated_at=excluded.updated_at, owner=excluded.owner, lease_until=excluded.lease_until",
                (video_pk, stage, status, attempt, input_hash, output_ref, error, _now(), self.owner, lease))
            self.conn.execute("COMMIT")
        except BaseException:
            if self.conn.in_transaction:
                self.conn.execute("ROLLBACK")
            raise
        return None

    @staticmethod
    def _input_hash(stage: str, upstream: Dict[str, str]) -> str:
        payload = stage + "|" + "|".join(f"{s}={upstream[s]}" for s in STAGES if s in upstream)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def state(self, video_pk: int) -> Dict[str, Dict[str, object]]:
        return {r["stage"]: dict(r) for r in self.conn.execute(
            "SELECT * FROM processing_state WHERE video_pk = ?", (video_pk,))}

    def run(self, video_pk: int, force: Iterable[str] = ()) -> RunReport:
        force = set(force)
        if force - set(STAGES):
            raise ValueError(f"etapas desconhecidas em force: {sorted(force - set(STAGES))}")
        report = RunReport(video_pk)
        upstream: Dict[str, str] = {}
        forcing = False
        for stage in STAGES:
            forcing = forcing or stage in force
            ih = self._input_hash(stage, upstream)
            row = self._row(video_pk, stage)
            if row and row["status"] == "done" and row["input_hash"] == ih and not forcing:
                upstream[stage] = row["output_ref"]
                report.skipped.append(stage)
                report.state = stage
                continue
            attempt = 1
            if row and row["status"] in ("failed", "running") and row["input_hash"] == ih and not forcing:
                attempt = row["attempt"] + 1
                if row["status"] == "failed" and row["attempt"] >= self.max_attempts:
                    report.state, report.error = TERMINAL_FAILED, f"{stage}: limite de {self.max_attempts} tentativas ({row['error']})"
                    return report
            holder = self._write(video_pk, stage, "running", attempt, ih, claim=True)
            if holder is not None:
                report.state, report.error = "busy", f"{stage}: em execução por {holder} (lease válido)"
                return report
            ctx = StageContext(video_pk, stage, dict(upstream), attempt, heartbeat=lambda: self._renew(video_pk, stage))
            try:
                out = self.handlers[stage](ctx)
            except (KeyboardInterrupt, SystemExit):
                raise  # estado fica 'running' e será retomado
            except LeaseLost as exc:  # outro executor é o dono agora: não grava nada
                report.state, report.error = TERMINAL_FAILED, str(exc)
                return report
            except Exception as exc:
                if not self._still_owner(video_pk, stage):
                    report.state, report.error = TERMINAL_FAILED, f"{stage}: falhou após perder a posse; estado do novo dono preservado"
                    return report
                self._write(video_pk, stage, "failed", attempt, ih, error=f"{exc.__class__.__name__}: {exc}"[:500])
                report.state, report.error = TERMINAL_FAILED, f"{stage}: {exc}"
                return report
            if out is None:
                if not self._still_owner(video_pk, stage):
                    report.state, report.error = TERMINAL_FAILED, f"{stage}: posse perdida durante a execução"
                    return report
                if stage != "awaiting_review":
                    self._write(video_pk, stage, "failed", attempt, ih, error="handler não devolveu referência de saída")
                    report.state, report.error = TERMINAL_FAILED, f"{stage}: sem saída"
                    return report
                self._write(video_pk, stage, "running", attempt, ih)
                report.state, report.waiting_on = "awaiting_review", stage
                report.executed.append(stage)
                return report
            if not self._still_owner(video_pk, stage):
                report.state, report.error = TERMINAL_FAILED, f"{stage}: posse perdida durante a execução (lease expirou); resultado descartado"
                return report
            self._write(video_pk, stage, "done", attempt, ih, output_ref=str(out))
            upstream[stage] = str(out)
            report.executed.append(stage)
            report.state = stage
        return report

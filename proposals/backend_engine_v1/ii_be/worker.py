"""Worker: assume jobs, executa etapas com prazo, reaproveita resultados e grava tudo atomicamente.

Ciclo de um job de etapa:
1. `claim` (lease) → `mark_running`.
2. Lê os resultados correntes das etapas anteriores e calcula a impressão digital de entrada.
3. Se já existe resultado válido com a mesma impressão digital (e não é `force`): conclui como `reused`
   sem rodar o handler (processamento incremental).
4. Senão roda o handler com `StageContext` (heartbeat, prazo, cancelamento cooperativo).
5. Conclui numa ÚNICA transação: resultado da etapa + efeitos (índice, artefato derivado) + eventos + estado.
   Quem perdeu a posse no meio do caminho recebe `LeaseLost` e não grava nada.

Prazo: com `db_path`, o handler roda numa thread com conexão própria e é abandonado ao passar do prazo de
parede (`StageTimeout`); o abandono não deixa escrita pela metade porque a conclusão exige a posse, e a única
escrita fora da conclusão (`Repository.save_analysis`) é idempotente. Sem `db_path` (banco em memória), o prazo
é cooperativo (`ctx.check()`), e o lease cobre um handler travado.

`KeyboardInterrupt`/`SystemExit` (e `SimulatedCrash` nos testes) não mexem no job: ele fica com o lease, que
vence e é recuperado por outro worker — o mesmo comportamento do `ii_mm.pipeline`.
"""
from __future__ import annotations

import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional

from . import _ii_mm  # noqa: F401
from ii_mm.db.migrations import connect
from ii_mm.pipeline import LeaseLost
from . import incremental as I
from .errors import DependencyMissing, PermanentError, StageTimeout, classify_exception
from .events import emit
from .observability import NullLogger
from .queue import Job, JobQueue
from .scheduler import MEDIA_GRAPH, METADATA_GRAPH, EngineConfig, stage_inputs
from .stages import HANDLERS, StageContext, StageOutput


class SimulatedCrash(BaseException):
    """Queda simulada do processo (testes/demonstração): não é tratada como falha do job."""


GRAPHS = {"media": MEDIA_GRAPH, "metadata": METADATA_GRAPH}


class Worker:
    def __init__(self, conn, clock, store=None, export_dir: Optional[Path] = None, cfg: Optional[EngineConfig] = None,
                 owner: Optional[str] = None, kinds: Optional[Iterable[str]] = None, logger=None,
                 handlers: Optional[Dict[str, Callable[[StageContext], StageOutput]]] = None,
                 job_handlers: Optional[Dict[str, Callable[["Worker", Job], Dict[str, Any]]]] = None,
                 queue: Optional[JobQueue] = None, db_path: Optional[str] = None, hooks: Optional[Dict[str, Callable]] = None):
        self.conn, self.clock, self.store = conn, clock, store
        self.export_dir = Path(export_dir) if export_dir else None
        self.cfg = cfg or EngineConfig()
        self.owner = owner or f"worker-{uuid.uuid4().hex[:8]}"
        self.kinds = list(kinds) if kinds else None
        self.log = logger or NullLogger()
        self.handlers = dict(HANDLERS, **(handlers or {}))
        self.job_handlers = dict(job_handlers or {})
        self.queue = queue or JobQueue(conn, clock)
        self.db_path = db_path
        self.hooks = dict(hooks or {})   # ex.: {"before_complete": fn(job)} para simular quedas nos testes

    # ------------------------------------------------------------------ execução
    def run_once(self) -> Optional[Dict[str, Any]]:
        job = self.queue.claim(self.owner, self.kinds)
        if job is None:
            return None
        t0 = self.clock.now()
        self.log.log("job.claimed", job_id=job.job_id, reference_id=job.reference_id, stage=job.stage, attempt=job.attempts,
                     run_id=job.run_id, owner=self.owner)
        try:
            self.queue.mark_running(job.job_id, self.owner)
            if job.kind == "stage":
                outcome = self._run_stage(job)
            elif job.kind in self.job_handlers:
                result = self.job_handlers[job.kind](self, job)
                outcome = self.queue.complete(job.job_id, self.owner, result)
            else:
                raise PermanentError(f"tipo de job sem handler: {job.kind}")
        except LeaseLost as exc:
            self.log.log("job.lease_lost", level="warning", job_id=job.job_id, stage=job.stage, error=str(exc))
            return {"job_id": job.job_id, "stage": job.stage, "outcome": "lease_lost"}
        except (KeyboardInterrupt, SystemExit, SimulatedCrash):
            raise
        except BaseException as exc:  # noqa: BLE001 - toda falha vira decisão explícita da política
            try:
                d = self.queue.fail(job.job_id, self.owner, exc)
            except LeaseLost:
                return {"job_id": job.job_id, "stage": job.stage, "outcome": "lease_lost"}
            self.log.log("job.failed", level="warning", job_id=job.job_id, reference_id=job.reference_id, stage=job.stage,
                         attempt=job.attempts, error_class=classify_exception(exc), outcome=d.state,
                         duration_ms=round((self.clock.now() - t0) * 1000, 3))
            return {"job_id": job.job_id, "stage": job.stage, "outcome": d.state, "error_class": classify_exception(exc)}
        self.log.log("job.finished", job_id=job.job_id, reference_id=job.reference_id, stage=job.stage, attempt=job.attempts,
                     outcome=outcome, duration_ms=round((self.clock.now() - t0) * 1000, 3),
                     processing_version=self.cfg.stage_versions.get(job.stage or "", None))
        return {"job_id": job.job_id, "stage": job.stage, "outcome": outcome}

    def run_until_idle(self, max_jobs: int = 10_000) -> List[Dict[str, Any]]:
        out = []
        for _ in range(max_jobs):
            r = self.run_once()
            if r is None:
                break
            out.append(r)
        return out

    # ------------------------------------------------------------------ etapas
    def _run_stage(self, job: Job) -> str:
        graph = GRAPHS.get(job.payload.get("graph"), MEDIA_GRAPH)
        if job.stage not in graph.deps:
            raise PermanentError(f"etapa {job.stage} não pertence ao grafo {job.payload.get('graph')}")
        upstream = {d: I.current_result(self.conn, job.reference_id, d) for d in graph.deps[job.stage]}
        missing = [d for d, r in upstream.items() if r is None]
        if missing:
            raise DependencyMissing(f"resultado ausente de {missing}")
        version = self.cfg.stage_versions[job.stage]
        fp = I.fingerprint(job.stage, version, stage_inputs(self.conn, job.reference_id, job.stage, graph,
                                                            {d: r["output_digest"] for d, r in upstream.items()}, self.cfg))
        if not job.payload.get("force"):
            hit = I.find_result(self.conn, job.reference_id, job.stage, fp)
            if hit:
                if "before_complete" in self.hooks:
                    self.hooks["before_complete"](job)
                return self.queue.complete(job.job_id, self.owner, dict(hit["result"], reused=True), reused=True)
        timeout = self.cfg.stage_timeout_s.get(job.stage, self.cfg.default_timeout_s)
        out = self._call(job, upstream, timeout)
        if "before_complete" in self.hooks:
            self.hooks["before_complete"](job)
        now = self.clock.now()

        def effects(c):
            I.record_result(c, job.reference_id, job.stage, fp, out.digest, out.result, version, job.job_id, now)
            if out.effects:
                out.effects(c)
            for type_, payload, key in out.events:
                emit(c, type_, job.reference_id, payload, now, dedup_key=key)
        return self.queue.complete(job.job_id, self.owner, out.result, effects)

    def _ctx(self, conn, job: Job, upstream, deadline) -> StageContext:
        return StageContext(conn=conn, reference_id=job.reference_id, stage=job.stage, job_id=job.job_id, attempt=job.attempts,
                            payload=job.payload, upstream=upstream, store=self.store, export_dir=self.export_dir, clock=self.clock,
                            deadline=deadline, heartbeat_fn=lambda: self.queue.heartbeat(job.job_id, self.owner))

    def _call(self, job: Job, upstream, timeout: float) -> StageOutput:
        handler = self.handlers[job.stage]
        deadline = self.clock.now() + timeout
        if not self.db_path:
            return handler(self._ctx(self.conn, job, upstream, deadline))
        box: Dict[str, Any] = {}
        holder: Dict[str, StageContext] = {}

        def target():
            conn = connect(self.db_path)
            try:
                ctx = self._ctx(conn, job, upstream, deadline)
                ctx.heartbeat_fn = lambda: False  # a thread do handler não renova o lease; o worker cuida disso
                holder["ctx"] = ctx
                box["out"] = handler(ctx)
            except BaseException as exc:  # noqa: BLE001
                box["exc"] = exc
            finally:
                conn.close()

        th = threading.Thread(target=target, name=f"stage-{job.stage}", daemon=True)
        th.start()
        start = time.monotonic()
        step = max(0.05, min(self.queue.lease_s / 3.0, 5.0))
        while th.is_alive() and time.monotonic() - start < timeout:
            th.join(min(step, max(0.0, timeout - (time.monotonic() - start))))
            if th.is_alive():
                try:
                    if self.queue.heartbeat(job.job_id, self.owner) and "ctx" in holder:
                        holder["ctx"].cancelled = True   # cancelamento pedido: o handler para no próximo check()
                except LeaseLost:
                    if "ctx" in holder:
                        holder["ctx"].cancelled = True
                    raise
        if th.is_alive():
            if "ctx" in holder:
                holder["ctx"].cancelled = True  # o handler para no próximo check()
            raise StageTimeout(f"{job.stage}: excedeu {timeout} s")
        if "exc" in box:
            raise box["exc"]
        return box["out"]

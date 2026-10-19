"""Fachada do motor: liga ingestão, artefatos, planner, fila, workers, eventos e serviços.

Fluxo orientado a eventos (tudo dentro do SQLite, sem serviço externo):
    ingest / register_artifact / curadoria  ──outbox──▶  consumidor "planner"  ──▶  job `plan` (dedup por referência)
    worker executa `plan`  ──▶  jobs de etapa com dependências  ──▶  workers executam  ──▶  eventos de saída
O consumidor grava o job `plan` NA MESMA transação em que marca o evento como consumido: um evento nunca gera
dois planejamentos, e uma queda no meio não perde o planejamento.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from . import _ii_mm  # noqa: F401
from ii_mm.db.migrations import connect
from . import artifacts as A
from .clock import SystemClock, iso
from .db import open_engine_db, tx
from .errors import InvalidInput, RetryPolicy
from .events import Dispatcher, emit, reconcile_reviews
from .ingest import IngestResult, IngestService
from .observability import NullLogger, diagnostics
from .queue import JobQueue
from .scheduler import EngineConfig, Planner, PlanResult, processing_view
from .worker import Worker

PLANNING_EVENTS = ["reference.ingested", "media.available", "artifact.registered", "curation.reviewed"]


class Engine:
    def __init__(self, db_path: str = ":memory:", root: Optional[Path] = None, export_dir: Optional[Path] = None,
                 clock=None, cfg: Optional[EngineConfig] = None, logger=None, lease_s: float = 300.0,
                 kind_limits: Optional[Dict[str, int]] = None, max_running: Optional[int] = None,
                 policy: Optional[RetryPolicy] = None):
        self.db_path = str(db_path)
        self.clock = clock or SystemClock()
        self.cfg = cfg or EngineConfig()
        self.log = logger or NullLogger()
        self.conn = open_engine_db(self.db_path)
        self.store = None
        if root is not None:
            root = Path(root)
            self.store = A.ArtifactStore(root) if (root / A.MARKER).is_file() else A.ArtifactStore.create(root)
        self.export_dir = Path(export_dir) if export_dir else None
        self.lease_s, self.kind_limits, self.max_running = lease_s, kind_limits, max_running
        self.policy = policy or RetryPolicy()
        self.queue = self._queue(self.conn)
        self.planner = Planner(self.conn, self.queue, self.cfg)
        self.ingestor = IngestService(self.conn, self.clock, self.store)

    def _queue(self, conn) -> JobQueue:
        return JobQueue(conn, self.clock, policy=self.policy, lease_s=self.lease_s, max_running=self.max_running,
                        kind_limits=self.kind_limits)

    def close(self) -> None:
        self.conn.close()

    # ------------------------------------------------------------------ entrada
    def ingest(self, record: Dict[str, Any]) -> IngestResult:
        return self.ingestor.ingest(record)

    def register_artifact(self, reference_id: str, kind: str, relpath: str, origin: str, expected_sha256: Optional[str] = None,
                          expected_size: Optional[int] = None, complete: bool = True, temp: bool = False) -> Dict[str, Any]:
        """Ferramenta externa (ffprobe, whisper, ffmpeg, agente de observação) avisa que produziu um arquivo."""
        if self.store is None:
            raise InvalidInput("motor sem raiz de artefatos")
        if not self.conn.execute("SELECT 1 FROM refs WHERE reference_id = ?", (reference_id,)).fetchone():
            raise InvalidInput(f"referência desconhecida: {reference_id}")
        if not origin or len(origin) > 120 or any(ord(c) < 32 for c in origin):
            raise InvalidInput("origin inválido")
        info = self.store.inspect(relpath)  # hash fora da transação
        now = self.clock.now()
        with tx(self.conn) as c:
            art = A.record(c, reference_id, kind, info, origin=origin, now_iso=iso(now), expected_sha=expected_sha256,
                           expected_size=expected_size, complete=complete, temp=temp)
            if art["new"]:
                emit(c, "artifact.registered", reference_id, {"artifact_id": art["artifact_id"], "kind": kind, "state": art["state"],
                                                               "sha256": art["sha256"]}, now, dedup_key=f"artifact|{art['artifact_id']}")
                if kind == "video" and art["state"] == "verified":
                    emit(c, "media.available", reference_id, {"reference_id": reference_id, "artifact_id": art["artifact_id"],
                                                               "sha256": art["sha256"]}, now, dedup_key=f"media|{art['artifact_id']}")
        return art

    # ------------------------------------------------------------------ planejamento e execução
    def plan(self, reference_id: str, force: Iterable[str] = ()) -> PlanResult:
        return self.planner.plan(reference_id, force=force)

    def _plan_job(self, worker: Worker, job) -> Dict[str, Any]:
        planner = Planner(worker.conn, worker.queue, self.cfg)
        r = planner.plan(job.reference_id, force=job.payload.get("force", []))
        return {"graph": r.graph, "enqueued": r.enqueued, "reused": r.reused, "already_active": r.already_active}

    def worker(self, owner: Optional[str] = None, own_connection: bool = False, **kw) -> Worker:
        """Worker na conexão do motor, ou com conexão própria (necessário para várias threads/processos)."""
        conn = self.conn
        if own_connection:
            if self.db_path == ":memory:":
                raise InvalidInput("várias conexões exigem banco em arquivo")
            conn = connect(self.db_path)
        return Worker(conn, self.clock, store=self.store, export_dir=self.export_dir, cfg=self.cfg, owner=owner, logger=self.log,
                      queue=self._queue(conn), job_handlers={"plan": self._plan_job, **kw.pop("job_handlers", {})},
                      db_path=kw.pop("db_path", None), **kw)

    def pump_events(self) -> Dict[str, int]:
        """Consumidor interno: transforma eventos de entrada em jobs `plan` (idempotente)."""
        now = self.clock.now()
        reconcile_reviews(self.conn, now)

        def handler(c: sqlite3.Connection, ev: Dict[str, Any]) -> None:
            ref = ev["aggregate_id"]
            if not ref or not c.execute("SELECT 1 FROM refs WHERE reference_id = ?", (ref,)).fetchone():
                return
            force = []
            if ev["type"] == "curation.reviewed":
                force = []  # a curadoria muda a impressão digital do índice; nada precisa ser forçado
            self.queue.enqueue_in(c, "plan", reference_id=ref, payload={"force": force, "trigger": ev["type"]},
                                  priority=10, dedup_key=f"plan|{ref}")
        return Dispatcher(self.conn, "planner", handler, types=PLANNING_EVENTS, clock=self.clock).run_once(limit=10_000)

    def run(self, max_rounds: int = 50, worker: Optional[Worker] = None) -> List[Dict[str, Any]]:
        """Bombeia eventos e executa jobs até não haver mais nada pronto (uma thread)."""
        w = worker or self.worker(owner="engine-main")
        done: List[Dict[str, Any]] = []
        for _ in range(max_rounds):
            self.pump_events()
            batch = w.run_until_idle()
            done += batch
            if not batch and not Dispatcher(self.conn, "planner", lambda c, e: None, types=PLANNING_EVENTS).pending(1):
                break
        return done

    # ------------------------------------------------------------------ leitura
    def processing(self, reference_id: str) -> Dict[str, Any]:
        return processing_view(self.conn, reference_id)

    def diagnostics(self) -> Dict[str, Any]:
        return diagnostics(self.conn, self.clock.now())

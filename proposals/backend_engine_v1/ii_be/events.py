"""Eventos internos com transactional outbox em SQLite (Tarefa 16).

Por que outbox: a mudança de dados e o registro do evento acontecem na MESMA transação do SQLite. Se a
transação desfaz, o evento some junto; se confirma, o evento existe e será entregue. Sem fila externa.

- `emit(conn, ...)` exige transação aberta pelo chamador. `dedup_key` torna o evento idempotente (mesma
  chave = mesmo `event_id`; reemitir não duplica).
- Consumidores: `Dispatcher` entrega em ordem (`event_seq`) e marca `be_consumed(consumer, event_id)` na mesma
  transação do efeito do handler: reprocessar depois de uma queda não repete o efeito.
- Falha no handler: desfaz, conta a falha; depois de `max_failures` o evento é estacionado (`parked`) para
  inspeção e o consumidor segue (sem bloqueio eterno da fila).
- Decisões gravadas pelo `ReviewService` do `ii_mm` (transação própria, que não podemos estender) entram no
  outbox por reconciliação: `reconcile_reviews` emite `curation.reviewed` para cada `reviews.review_id` ainda
  sem evento (chave = review_id). Uma queda entre a revisão e o evento não perde nada nem duplica.
- Saídas para fora (n8n): só `JsonlSink` em modo de teste; nenhum webhook real é chamado nesta missão.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .db import tx

EVENT_TYPES = ("reference.ingested", "media.available", "artifact.registered", "analysis.completed",
               "classification.updated", "curation.reviewed", "knowledge.indexed", "export.ready",
               "job.dead_letter", "gateway.completed")


def event_id_for(dedup_key: str) -> str:
    return "evt_" + hashlib.sha256(dedup_key.encode("utf-8")).hexdigest()[:24]


def emit(conn: sqlite3.Connection, type_: str, aggregate_id: Optional[str], payload: Dict[str, Any], now: float,
         dedup_key: Optional[str] = None) -> Optional[str]:
    if not conn.in_transaction:
        raise RuntimeError("emit exige a transação da mudança (outbox transacional)")
    if type_ not in EVENT_TYPES:
        raise ValueError(f"tipo de evento desconhecido: {type_}")
    eid = event_id_for(f"{type_}|{dedup_key}") if dedup_key else "evt_" + uuid.uuid4().hex[:24]
    cur = conn.execute("INSERT OR IGNORE INTO be_outbox(event_id, type, aggregate_id, payload_json, created_at) VALUES (?,?,?,?,?)",
                       (eid, type_, aggregate_id, json.dumps(payload, ensure_ascii=False, sort_keys=True), now))
    return eid if cur.rowcount == 1 else None


def reconcile_reviews(conn: sqlite3.Connection, now: float) -> int:
    """Emite `curation.reviewed` para revisões do `ii_mm` que ainda não têm evento."""
    rows = conn.execute("SELECT r.review_id, r.reference_id, r.action, r.target FROM reviews r ORDER BY r.reference_id, r.seq").fetchall()
    n = 0
    with tx(conn):
        for r in rows:
            if emit(conn, "curation.reviewed", r["reference_id"],
                    {"source": "ii_mm.review", "review_id": r["review_id"], "action": r["action"], "target": r["target"]},
                    now, dedup_key=f"ii_review|{r['review_id']}"):
                n += 1
    return n


Handler = Callable[[sqlite3.Connection, Dict[str, Any]], None]


class Dispatcher:
    def __init__(self, conn: sqlite3.Connection, consumer: str, handler: Handler, types: Optional[List[str]] = None,
                 max_failures: int = 3, clock=None):
        self.conn, self.consumer, self.handler = conn, consumer, handler
        self.types = list(types) if types else None
        self.max_failures = max_failures
        self.clock = clock

    def _now(self) -> float:
        return self.clock.now() if self.clock else 0.0

    def pending(self, limit: int = 100) -> List[Dict[str, Any]]:
        sql = ("SELECT o.* FROM be_outbox o WHERE NOT EXISTS (SELECT 1 FROM be_consumed c WHERE c.consumer = ? AND c.event_id = o.event_id)")
        args: list = [self.consumer]
        if self.types:
            sql += f" AND o.type IN ({','.join('?' * len(self.types))})"
            args += self.types
        rows = self.conn.execute(sql + " ORDER BY o.event_seq LIMIT ?", args + [limit]).fetchall()
        return [dict(r, payload=json.loads(r["payload_json"])) for r in rows]

    def run_once(self, limit: int = 100) -> Dict[str, int]:
        stats = {"processed": 0, "failed": 0, "parked": 0, "skipped": 0}
        for ev in self.pending(limit):
            try:
                with tx(self.conn) as c:
                    if c.execute("SELECT 1 FROM be_consumed WHERE consumer = ? AND event_id = ?", (self.consumer, ev["event_id"])).fetchone():
                        stats["skipped"] += 1  # outro dispatcher do mesmo consumidor chegou antes
                        continue
                    self.handler(c, ev)
                    fails = c.execute("SELECT failures FROM be_consumer_failures WHERE consumer = ? AND event_id = ?",
                                      (self.consumer, ev["event_id"])).fetchone()
                    c.execute("INSERT INTO be_consumed(consumer, event_id, outcome, attempts, processed_at) VALUES (?,?,?,?,?)",
                              (self.consumer, ev["event_id"], "processed", (fails[0] if fails else 0) + 1, self._now()))
                stats["processed"] += 1
            except Exception as exc:
                stats["failed"] += 1
                msg = " ".join(f"{exc.__class__.__name__}: {exc}".split())[:300]
                with tx(self.conn) as c:
                    c.execute("INSERT INTO be_consumer_failures(consumer, event_id, failures, last_error) VALUES (?,?,1,?) "
                              "ON CONFLICT(consumer, event_id) DO UPDATE SET failures = failures + 1, last_error = excluded.last_error",
                              (self.consumer, ev["event_id"], msg))
                    n = c.execute("SELECT failures FROM be_consumer_failures WHERE consumer = ? AND event_id = ?",
                                  (self.consumer, ev["event_id"])).fetchone()[0]
                    if n >= self.max_failures:
                        c.execute("INSERT OR IGNORE INTO be_consumed(consumer, event_id, outcome, attempts, processed_at, error) "
                                  "VALUES (?,?,?,?,?,?)", (self.consumer, ev["event_id"], "parked", n, self._now(), msg))
                        stats["parked"] += 1
                if n < self.max_failures:
                    break  # preserva a ordem: tenta de novo na próxima rodada antes de seguir
        return stats


class JsonlSink:
    """Destino de teste para integração futura com n8n: grava eventos em JSON Lines numa pasta de staging.
    Não faz nenhuma chamada de rede."""

    def __init__(self, path: Path):
        self.path = Path(path)

    def __call__(self, conn: sqlite3.Connection, event: Dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        line = {"event_id": event["event_id"], "type": event["type"], "aggregate_id": event["aggregate_id"],
                "payload": event["payload"], "schema": "ii.be.event.v1"}
        with open(self.path, "a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(line, ensure_ascii=False, sort_keys=True) + "\n")


def outbox_counts(conn: sqlite3.Connection) -> Dict[str, int]:
    return {r["type"]: r["n"] for r in conn.execute("SELECT type, COUNT(*) AS n FROM be_outbox GROUP BY type ORDER BY type")}

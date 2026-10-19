"""Outbox do motor criativo (para o n8n e o painel). Gravado na MESMA transação da mudança; consumo idempotente."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from . import _be  # noqa: F401
from ii_be.events import event_id_for

EVENT_TYPES = ("investigation.created", "investigation.blocked", "task.completed", "task.blocked", "task.failed", "investigation.partial",
               "investigation.completed", "dossier.generated", "review.registered", "approval.recorded", "obsidian.exported")


def emit(conn: sqlite3.Connection, type_: str, investigation_id: Optional[str], payload: Dict[str, Any], now: float, dedup_key: str) -> Optional[str]:
    if not conn.in_transaction:
        raise RuntimeError("emit exige a transação da mudança")
    if type_ not in EVENT_TYPES:
        raise ValueError(f"tipo de evento desconhecido: {type_}")
    eid = event_id_for(f"ce|{type_}|{dedup_key}")
    cur = conn.execute("INSERT OR IGNORE INTO ce_events(event_id, type, investigation_id, payload_json, created_at, seq) "
                       "VALUES (?,?,?,?,?, (SELECT COALESCE(MAX(seq),0)+1 FROM ce_events))",
                       (eid, type_, investigation_id, json.dumps(payload, ensure_ascii=False, sort_keys=True), now))
    return eid if cur.rowcount == 1 else None


def pending(conn: sqlite3.Connection, consumer: str, limit: int = 100) -> List[Dict[str, Any]]:
    rows = conn.execute("SELECT e.* FROM ce_events e WHERE NOT EXISTS (SELECT 1 FROM ce_consumed c WHERE c.consumer = ? AND c.event_id = e.event_id) "
                        "ORDER BY e.seq LIMIT ?", (consumer, limit)).fetchall()
    return [{**dict(r), "payload": json.loads(r["payload_json"])} for r in rows]


def drain(conn: sqlite3.Connection, consumer: str, handler: Callable[[Dict[str, Any]], None], now: float, limit: int = 1000) -> int:
    """Entrega cada evento uma vez por consumidor; o handler que falha deixa o evento pendente (sem perda)."""
    n = 0
    for ev in pending(conn, consumer, limit):
        handler(ev)
        conn.execute("INSERT OR IGNORE INTO ce_consumed(consumer, event_id, consumed_at) VALUES (?,?,?)", (consumer, ev["event_id"], now))
        conn.commit() if conn.in_transaction else None
        n += 1
    return n


class JsonlSink:
    """Consumidor que acrescenta cada evento a um arquivo JSONL (formato lido pelo n8n sem rede)."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def __call__(self, ev: Dict[str, Any]) -> None:
        line = json.dumps({"event_id": ev["event_id"], "type": ev["type"], "investigation_id": ev["investigation_id"], "payload": ev["payload"]},
                          ensure_ascii=False, sort_keys=True)
        with self.path.open("a", encoding="utf-8", newline="\n") as f:
            f.write(line + "\n")

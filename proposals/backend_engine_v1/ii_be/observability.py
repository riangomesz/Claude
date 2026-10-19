"""Observabilidade operacional (Tarefa 18): logs estruturados (JSON Lines) e diagnóstico a partir do banco.

Logs:
- Cada linha tem `event` e, quando houver, `job_id`, `reference_id`, `stage`, `attempt`, `duration_ms`, `outcome`,
  `error_class`, `run_id`, `processing_version`.
- `redact` remove segredos: chaves com cara de credencial (token, secret, password, authorization, cookie,
  api_key, session…) viram `[REDACTED]`; valores com padrão de credencial (Bearer …, sk-…, ghp_…, chave AWS)
  também. Textos de conteúdo (legenda, transcrição, claim, text, caption…) viram {len, sha256}: dá para
  correlacionar sem copiar conteúdo privado para o log.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import sys
import threading
from typing import Any, Dict, IO, Optional

SECRET_KEY = re.compile(r"(pass(word)?|secret|token|authorization|cookie|api[_-]?key|session|credential|private[_-]?key|signature)", re.I)
SECRET_VALUE = re.compile(r"(bearer\s+[A-Za-z0-9._\-]{8,}|\bsk-[A-Za-z0-9_\-]{16,}|\bghp_[A-Za-z0-9]{20,}|\bAKIA[0-9A-Z]{16}\b|"
                          r"\bxox[abp]-[A-Za-z0-9-]{10,})", re.I)
CONTENT_KEYS = {"caption", "transcript", "text", "claim", "title", "segments", "quote", "body", "prompt", "content", "description"}


def redact(obj: Any, _depth: int = 0) -> Any:
    if _depth > 8:
        return "[profundo demais]"
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            ks = str(k)
            if SECRET_KEY.search(ks):
                out[ks] = "[REDACTED]"
            elif ks.lower() in CONTENT_KEYS and isinstance(v, (str, list)):
                raw = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False, sort_keys=True)
                out[ks] = {"len": len(raw), "sha256": hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]}
            else:
                out[ks] = redact(v, _depth + 1)
        return out
    if isinstance(obj, (list, tuple)):
        return [redact(v, _depth + 1) for v in list(obj)[:50]]
    if isinstance(obj, str):
        s = SECRET_VALUE.sub("[REDACTED]", obj)
        return s if len(s) <= 500 else s[:500] + "…"
    return obj


class JsonLogger:
    def __init__(self, stream: Optional[IO[str]] = None, clock=None, static: Optional[Dict[str, Any]] = None):
        self.stream = stream if stream is not None else sys.stderr
        self.clock = clock
        self.static = dict(static or {})
        self._lock = threading.Lock()
        self.lines = 0

    def log(self, event: str, level: str = "info", **fields: Any) -> None:
        rec = {"event": event, "level": level, **self.static, **{k: v for k, v in fields.items() if v is not None}}
        if self.clock is not None:
            rec["ts"] = round(self.clock.now(), 3)
        line = json.dumps(redact(rec), ensure_ascii=False, sort_keys=True, default=str)
        with self._lock:
            self.stream.write(line + "\n")
            self.lines += 1


class NullLogger(JsonLogger):
    def __init__(self):
        super().__init__(stream=None)

    def log(self, event: str, level: str = "info", **fields: Any) -> None:
        return None


def diagnostics(conn: sqlite3.Connection, now: float, recent_s: float = 3600.0) -> Dict[str, Any]:
    q = lambda sql, *a: conn.execute(sql, a).fetchall()  # noqa: E731
    by_state = {r["state"]: r["n"] for r in q("SELECT state, COUNT(*) AS n FROM be_jobs GROUP BY state")}
    blocked = q("SELECT COUNT(DISTINCT j.job_id) AS n FROM be_jobs j JOIN be_job_deps d ON d.job_id = j.job_id JOIN be_jobs p "
                "ON p.job_id = d.depends_on WHERE j.state = 'waiting_dependency' AND p.state IN ('failed','dead_letter','cancelled')")[0]["n"]
    stage_time = {r["stage"]: {"attempts": r["n"], "avg_s": round(r["avg_s"] or 0, 4), "max_s": round(r["max_s"] or 0, 4)}
                  for r in q("SELECT j.stage, COUNT(*) AS n, AVG(a.finished_at - a.started_at) AS avg_s, MAX(a.finished_at - a.started_at) AS max_s "
                             "FROM be_job_attempts a JOIN be_jobs j ON j.job_id = a.job_id WHERE a.outcome IN ('completed','reused') "
                             "GROUP BY j.stage ORDER BY j.stage")}
    attempts = q("SELECT outcome, COUNT(*) AS n FROM be_job_attempts GROUP BY outcome")
    stage_jobs = q("SELECT COUNT(*) AS n, SUM(CASE WHEN run_cnt > 1 THEN 1 ELSE 0 END) AS re FROM "
                   "(SELECT reference_id, stage, COUNT(*) AS run_cnt FROM be_jobs WHERE kind = 'stage' GROUP BY reference_id, stage)")[0]
    recent = [dict(r) for r in q("SELECT job_id, stage, reference_id, state, last_error_class, last_error, updated_at FROM be_jobs "
                                 "WHERE state IN ('failed','dead_letter') OR (state = 'retry_scheduled' AND last_error_class IS NOT NULL) "
                                 "ORDER BY updated_at DESC LIMIT 20")]
    awaiting = q("SELECT COUNT(*) AS n FROM refs r WHERE EXISTS (SELECT 1 FROM ref_videos rv JOIN analyses a ON a.video_pk = rv.video_pk "
                 "WHERE rv.reference_id = r.reference_id AND a.status = 'current') AND NOT EXISTS (SELECT 1 FROM review_state s "
                 "WHERE s.reference_id = r.reference_id) AND NOT EXISTS (SELECT 1 FROM be_curation c WHERE c.reference_id = r.reference_id)")[0]["n"]
    expired = q("SELECT COUNT(*) AS n FROM be_jobs WHERE state IN ('claimed','running') AND lease_until < ?", now)[0]["n"]
    outbox = q("SELECT COUNT(*) AS n FROM be_outbox")[0]["n"]
    parked = q("SELECT COUNT(*) AS n FROM be_consumed WHERE outcome = 'parked'")[0]["n"]
    return {
        "jobs": {"pending": sum(by_state.get(s, 0) for s in ("queued", "retry_scheduled", "waiting_dependency")),
                 "running": by_state.get("claimed", 0) + by_state.get("running", 0), "blocked": blocked,
                 "expired_leases": expired, "by_state": dict(sorted(by_state.items()))},
        "attempts_by_outcome": {r["outcome"] or "open": r["n"] for r in attempts},
        "time_per_stage": stage_time,
        "reprocess_rate": {"stage_pairs": stage_jobs["n"], "reprocessed_pairs": stage_jobs["re"] or 0},
        "recent_failures": recent,
        "awaiting_review": awaiting,
        "events": {"outbox": outbox, "parked": parked},
    }

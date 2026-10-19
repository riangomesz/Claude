"""Migrações próprias do motor criativo (trilha `ce_schema_migrations`), no MESMO banco do `ii_be`.

Autoridade por dado:
- ce_investigations: uma linha por versão de investigação (reference_id, seq). Nunca é sobrescrita: entrada nova
  (evidências, versões, perfis, profundidade ou limites diferentes) cria a próxima versão e marca a anterior como superseded.
- ce_tasks: uma tarefa por (investigação, especialista, tipo); a transição pending→running é atômica (UPDATE condicional).
- ce_claims: afirmações dos especialistas (só acrescenta; id determinístico).
- ce_groups: reconciliação (DERIVADA; reconstruída a partir de ce_claims + ce_reviews).
- ce_reviews: decisões humanas, por (reference_id, key), só acrescenta; sobrevivem às versões.
- ce_approvals, ce_dossiers, ce_events/ce_consumed: aprovações, versões do dossiê e outbox para o n8n.
"""
from __future__ import annotations

import sqlite3
from typing import List

from . import _be  # noqa: F401
from ii_mm.db.migrations import IncompatibleSchemaError, Migration, MigrationError
from ii_be.db import _now_iso

CE001 = Migration(1, "investigacao_tarefas_afirmacoes_dossie", (
    """CREATE TABLE ce_investigations (
        investigation_id TEXT PRIMARY KEY, reference_id TEXT NOT NULL, seq INTEGER NOT NULL,
        input_hash TEXT NOT NULL, content_hash TEXT NOT NULL, bundle_json TEXT NOT NULL, depth TEXT NOT NULL, priority INTEGER NOT NULL DEFAULT 5,
        profile_ids_json TEXT NOT NULL, versions_json TEXT NOT NULL, limits_json TEXT NOT NULL, plan_json TEXT NOT NULL,
        state TEXT NOT NULL, supersedes TEXT, requested_by TEXT, created_at REAL NOT NULL, updated_at REAL NOT NULL,
        UNIQUE (reference_id, seq), UNIQUE (reference_id, input_hash))""",
    """CREATE TABLE ce_tasks (
        task_id TEXT PRIMARY KEY, investigation_id TEXT NOT NULL REFERENCES ce_investigations(investigation_id),
        specialist TEXT NOT NULL, kind TEXT NOT NULL, state TEXT NOT NULL, depends_on_json TEXT NOT NULL DEFAULT '[]',
        evidence_ids_json TEXT NOT NULL DEFAULT '[]', reason TEXT NOT NULL, est_usd REAL NOT NULL DEFAULT 0, usd REAL NOT NULL DEFAULT 0,
        attempts INTEGER NOT NULL DEFAULT 0, lease_until REAL, owner TEXT, error TEXT, input_digest TEXT, result_json TEXT,
        created_at REAL NOT NULL, updated_at REAL NOT NULL)""",
    "CREATE INDEX idx_ce_tasks_inv ON ce_tasks(investigation_id, state)",
    """CREATE TABLE ce_claims (
        claim_id TEXT PRIMARY KEY, investigation_id TEXT NOT NULL REFERENCES ce_investigations(investigation_id),
        task_id TEXT NOT NULL REFERENCES ce_tasks(task_id), specialist TEXT NOT NULL, domain TEXT NOT NULL, kind TEXT NOT NULL,
        key TEXT NOT NULL, value TEXT NOT NULL DEFAULT 'present', statement TEXT NOT NULL, evidence_ids_json TEXT NOT NULL,
        confidence TEXT NOT NULL DEFAULT 'low', created_at REAL NOT NULL)""",
    "CREATE INDEX idx_ce_claims_inv ON ce_claims(investigation_id, key)",
    """CREATE TABLE ce_groups (
        investigation_id TEXT NOT NULL, key TEXT NOT NULL, domain TEXT NOT NULL, kind TEXT NOT NULL, state TEXT NOT NULL,
        human_state TEXT, strongest_status TEXT, agents_json TEXT NOT NULL, claim_ids_json TEXT NOT NULL,
        evidence_ids_json TEXT NOT NULL, values_json TEXT NOT NULL, conflict INTEGER NOT NULL DEFAULT 0, summary TEXT NOT NULL,
        PRIMARY KEY (investigation_id, key))""",
    """CREATE TABLE ce_reviews (
        review_id INTEGER PRIMARY KEY AUTOINCREMENT, reference_id TEXT NOT NULL, key TEXT NOT NULL, decision TEXT NOT NULL,
        reviewer TEXT NOT NULL, note TEXT, corrected_value TEXT, created_at REAL NOT NULL)""",
    "CREATE INDEX idx_ce_reviews_ref ON ce_reviews(reference_id, key, review_id)",
    """CREATE TABLE ce_approvals (
        approval_id INTEGER PRIMARY KEY AUTOINCREMENT, investigation_id TEXT NOT NULL, scope TEXT NOT NULL, value TEXT NOT NULL,
        approver TEXT NOT NULL, created_at REAL NOT NULL)""",
    """CREATE TABLE ce_dossiers (
        dossier_id TEXT PRIMARY KEY, investigation_id TEXT NOT NULL, version INTEGER NOT NULL, content_hash TEXT NOT NULL,
        path TEXT NOT NULL, manifest_json TEXT NOT NULL, created_at REAL NOT NULL, UNIQUE (investigation_id, content_hash))""",
    """CREATE TABLE ce_events (
        event_id TEXT PRIMARY KEY, type TEXT NOT NULL, investigation_id TEXT, payload_json TEXT NOT NULL, created_at REAL NOT NULL,
        seq INTEGER)""",
    "CREATE TABLE ce_consumed (consumer TEXT NOT NULL, event_id TEXT NOT NULL, consumed_at REAL NOT NULL, PRIMARY KEY (consumer, event_id))",
))
CE_MIGRATIONS = (CE001,)


def migrate_ce(conn: sqlite3.Connection) -> List[int]:
    conn.execute("""CREATE TABLE IF NOT EXISTS ce_schema_migrations (
        version INTEGER PRIMARY KEY, name TEXT NOT NULL, checksum TEXT NOT NULL, applied_at TEXT NOT NULL)""")
    done = {r["version"]: r for r in conn.execute("SELECT * FROM ce_schema_migrations")}
    last = CE_MIGRATIONS[-1].version
    if done and max(done) > last:
        raise IncompatibleSchemaError(f"motor criativo no banco na versão {max(done)}; o código conhece até {last}")
    known = {m.version: m for m in CE_MIGRATIONS}
    for v, row in done.items():
        if row["checksum"] != known[v].checksum:
            raise MigrationError(f"migração criativa {v} foi alterada depois de aplicada")
    applied = []
    for m in CE_MIGRATIONS:
        if m.version in done:
            continue
        conn.execute("BEGIN IMMEDIATE")
        try:
            for stmt in m.statements:
                conn.execute(stmt)
            conn.execute("INSERT INTO ce_schema_migrations(version, name, checksum, applied_at) VALUES (?,?,?,?)",
                         (m.version, m.name, m.checksum, _now_iso()))
            conn.execute("COMMIT")
        except Exception as exc:
            conn.execute("ROLLBACK")
            raise MigrationError(f"migração criativa {m.version} falhou e foi desfeita: {exc}") from exc
        applied.append(m.version)
    return applied

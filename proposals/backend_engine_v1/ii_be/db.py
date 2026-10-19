"""Banco do motor: as migrações M001–M008 do `ii_mm` + as migrações próprias do backend (BE001…).

Fonte de verdade de cada dado (uma autoridade por informação):
- Identidade da referência, vídeos, análises, evidências, revisões de categoria/ferramenta/evidência: tabelas do
  `ii_mm` (refs, ref_aliases, videos, ref_videos, analyses, …, reviews, review_state). O backend grava `refs` e
  `ref_aliases` com as mesmas regras de `Repository.save_analysis`, e as análises SÓ por `Repository`.
- Origem e histórico de metadados: `be_sources`, `be_reference_meta` (só acrescenta).
- Arquivos (mídia e saídas de ferramentas): `be_artifacts` (identidade do arquivo = SHA-256).
- Execução: `be_jobs` + `be_job_deps` + `be_job_attempts` (a fila é a autoridade sobre tentativas e agendamento).
- Saídas de etapa reutilizáveis: `be_stage_results` (cache com impressão digital de entrada).
- Curadoria de triagem/nota/confirmação de evidência/rejeição de hipótese: `be_curation*` (as decisões de
  categoria e ferramenta continuam no `ii_mm`).
- Eventos: `be_outbox` (gravado na MESMA transação da mudança) + `be_consumed` (consumo idempotente).
- Índice de conhecimento e termos: `be_knowledge`, `be_terms` (derivados; podem ser reconstruídos).
- Gateway de modelos (simulado) e idempotência da API: `be_gateway_*`, `be_api_requests`.

As migrações do backend têm trilha própria (`be_schema_migrations`), com as mesmas garantias das do `ii_mm`:
sequenciais, checksum, transação por migração e recusa de banco mais novo que o código.
"""
from __future__ import annotations

import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, List, Sequence, Tuple

from . import _ii_mm  # noqa: F401
from ii_mm.db.migrations import IncompatibleSchemaError, Migration, MigrationError, connect, migrate

BE001 = Migration(1, "origem_metadados_artefatos", (
    """CREATE TABLE be_sources (
        source_id     INTEGER PRIMARY KEY,
        reference_id  TEXT NOT NULL REFERENCES refs(reference_id) ON DELETE CASCADE,
        source_kind   TEXT NOT NULL,
        source_ref    TEXT,
        observed_at   TEXT,
        received_at   TEXT NOT NULL,
        payload_sha256 TEXT NOT NULL,
        acquisition_hint TEXT,
        dedup_key     TEXT NOT NULL UNIQUE
    )""",
    "CREATE INDEX idx_be_sources_ref ON be_sources(reference_id, source_id)",
    """CREATE TABLE be_reference_meta (
        meta_id       INTEGER PRIMARY KEY,
        reference_id  TEXT NOT NULL REFERENCES refs(reference_id) ON DELETE CASCADE,
        field         TEXT NOT NULL,
        value_json    TEXT NOT NULL,
        source_id     INTEGER NOT NULL REFERENCES be_sources(source_id),
        observed_at   TEXT,
        recorded_at   TEXT NOT NULL
    )""",
    "CREATE INDEX idx_be_meta_ref_field ON be_reference_meta(reference_id, field, meta_id)",
    """CREATE TABLE be_artifacts (
        artifact_id   TEXT PRIMARY KEY,
        reference_id  TEXT NOT NULL REFERENCES refs(reference_id) ON DELETE CASCADE,
        kind          TEXT NOT NULL,
        version       INTEGER NOT NULL,
        relpath       TEXT NOT NULL,
        sha256        TEXT CHECK (sha256 IS NULL OR length(sha256) = 64),
        size_bytes    INTEGER,
        expected_sha256 TEXT,
        expected_size INTEGER,
        state         TEXT NOT NULL CHECK (state IN ('registered','verified','missing','corrupt','partial','temp','superseded')),
        origin        TEXT NOT NULL,
        job_id        TEXT,
        created_at    TEXT NOT NULL,
        verified_at   TEXT,
        error         TEXT,
        UNIQUE (reference_id, kind, version)
    )""",
    "CREATE INDEX idx_be_artifacts_sha ON be_artifacts(sha256)",
    "CREATE INDEX idx_be_artifacts_ref_kind ON be_artifacts(reference_id, kind, version)",
    """CREATE TABLE be_artifact_deps (
        artifact_id   TEXT NOT NULL REFERENCES be_artifacts(artifact_id) ON DELETE CASCADE,
        depends_on    TEXT NOT NULL REFERENCES be_artifacts(artifact_id),
        PRIMARY KEY (artifact_id, depends_on)
    )""",
))

BE002 = Migration(2, "fila_dependencias_tentativas_resultados", (
    """CREATE TABLE be_jobs (
        job_id        TEXT PRIMARY KEY,
        kind          TEXT NOT NULL,
        reference_id  TEXT,
        stage         TEXT,
        run_id        TEXT,
        dedup_key     TEXT,
        priority      INTEGER NOT NULL DEFAULT 100,
        state         TEXT NOT NULL CHECK (state IN ('queued','claimed','running','waiting_dependency','retry_scheduled',
                                                     'completed','failed','cancelled','dead_letter')),
        attempts      INTEGER NOT NULL DEFAULT 0,
        failures      INTEGER NOT NULL DEFAULT 0,
        busy_retries  INTEGER NOT NULL DEFAULT 0,
        dependency_waits INTEGER NOT NULL DEFAULT 0,
        max_attempts  INTEGER NOT NULL DEFAULT 5,
        not_before    REAL NOT NULL,
        lease_owner   TEXT,
        lease_until   REAL,
        cancel_requested INTEGER NOT NULL DEFAULT 0,
        payload_json  TEXT NOT NULL DEFAULT '{}',
        result_json   TEXT,
        last_error_class TEXT,
        last_error    TEXT,
        created_at    REAL NOT NULL,
        updated_at    REAL NOT NULL,
        started_at    REAL,
        finished_at   REAL
    )""",
    # deduplicação de solicitações: no máximo UM job ATIVO por chave
    "CREATE UNIQUE INDEX idx_be_jobs_active_dedup ON be_jobs(dedup_key) WHERE dedup_key IS NOT NULL "
    "AND state NOT IN ('completed','failed','cancelled','dead_letter')",
    "CREATE INDEX idx_be_jobs_ready ON be_jobs(state, priority, not_before, created_at)",
    "CREATE INDEX idx_be_jobs_ref ON be_jobs(reference_id, stage, created_at)",
    "CREATE INDEX idx_be_jobs_lease ON be_jobs(state, lease_until)",
    """CREATE TABLE be_job_deps (
        job_id      TEXT NOT NULL REFERENCES be_jobs(job_id) ON DELETE CASCADE,
        depends_on  TEXT NOT NULL REFERENCES be_jobs(job_id),
        PRIMARY KEY (job_id, depends_on)
    )""",
    "CREATE INDEX idx_be_job_deps_rev ON be_job_deps(depends_on, job_id)",
    """CREATE TABLE be_job_attempts (
        attempt_id  INTEGER PRIMARY KEY,
        job_id      TEXT NOT NULL REFERENCES be_jobs(job_id) ON DELETE CASCADE,
        attempt_no  INTEGER NOT NULL,
        owner       TEXT NOT NULL,
        started_at  REAL NOT NULL,
        finished_at REAL,
        outcome     TEXT CHECK (outcome IS NULL OR outcome IN ('completed','reused','retry','failed','dead_letter','lease_lost',
                                                               'cancelled','timeout','waiting_dependency','busy')),
        error_class TEXT,
        error       TEXT,
        UNIQUE (job_id, attempt_no)
    )""",
    """CREATE TABLE be_stage_results (
        reference_id  TEXT NOT NULL,
        stage         TEXT NOT NULL,
        fingerprint   TEXT NOT NULL,
        output_digest TEXT NOT NULL,
        result_json   TEXT NOT NULL,
        stage_version TEXT NOT NULL,
        job_id        TEXT,
        status        TEXT NOT NULL CHECK (status IN ('valid','invalidated')),
        created_at    REAL NOT NULL,
        invalidated_reason TEXT,
        PRIMARY KEY (reference_id, stage, fingerprint)
    )""",
    "CREATE INDEX idx_be_stage_current ON be_stage_results(reference_id, stage, status, created_at)",
))

BE003 = Migration(3, "curadoria_eventos_conhecimento", (
    """CREATE TABLE be_curation (
        reference_id TEXT PRIMARY KEY REFERENCES refs(reference_id) ON DELETE CASCADE,
        triage       TEXT CHECK (triage IS NULL OR triage IN ('manter','revisar_depois','descartar')),
        rating       TEXT CHECK (rating IS NULL OR rating IN ('excelente','muito_bom','bom','ruim')),
        revision     INTEGER NOT NULL,
        updated_at   TEXT NOT NULL,
        updated_by   TEXT NOT NULL
    )""",
    """CREATE TABLE be_curation_targets (
        reference_id TEXT NOT NULL REFERENCES refs(reference_id) ON DELETE CASCADE,
        target       TEXT NOT NULL,
        state        TEXT NOT NULL CHECK (state IN ('confirmed','rejected')),
        revision     INTEGER NOT NULL,
        updated_at   TEXT NOT NULL,
        PRIMARY KEY (reference_id, target)
    )""",
    """CREATE TABLE be_curation_log (
        log_id       INTEGER PRIMARY KEY,
        reference_id TEXT NOT NULL REFERENCES refs(reference_id) ON DELETE CASCADE,
        revision     INTEGER NOT NULL,
        action       TEXT NOT NULL,
        target       TEXT,
        before_json  TEXT,
        after_json   TEXT,
        reviewer     TEXT NOT NULL,
        reason       TEXT,
        ii_review_id TEXT,
        at           TEXT NOT NULL
    )""",
    "CREATE INDEX idx_be_curation_log_ref ON be_curation_log(reference_id, log_id)",
    """CREATE TABLE be_outbox (
        event_seq    INTEGER PRIMARY KEY AUTOINCREMENT,
        event_id     TEXT NOT NULL UNIQUE,
        type         TEXT NOT NULL,
        aggregate_id TEXT,
        payload_json TEXT NOT NULL,
        created_at   REAL NOT NULL
    )""",
    "CREATE INDEX idx_be_outbox_type ON be_outbox(type, event_seq)",
    """CREATE TABLE be_consumed (
        consumer     TEXT NOT NULL,
        event_id     TEXT NOT NULL,
        outcome      TEXT NOT NULL CHECK (outcome IN ('processed','parked')),
        attempts     INTEGER NOT NULL,
        processed_at REAL NOT NULL,
        error        TEXT,
        PRIMARY KEY (consumer, event_id)
    )""",
    """CREATE TABLE be_consumer_failures (
        consumer     TEXT NOT NULL,
        event_id     TEXT NOT NULL,
        failures     INTEGER NOT NULL,
        last_error   TEXT,
        PRIMARY KEY (consumer, event_id)
    )""",
    """CREATE TABLE be_knowledge (
        reference_id TEXT NOT NULL REFERENCES refs(reference_id) ON DELETE CASCADE,
        facet        TEXT NOT NULL,
        value        TEXT NOT NULL,
        status       TEXT NOT NULL,
        analysis_id  TEXT,
        evidence_json TEXT NOT NULL,
        authority    TEXT NOT NULL CHECK (authority IN ('automatic','human')),
        PRIMARY KEY (reference_id, facet, value, status)
    )""",
    "CREATE INDEX idx_be_knowledge_lookup ON be_knowledge(facet, value, status, reference_id)",
    """CREATE TABLE be_terms (
        term         TEXT NOT NULL,
        reference_id TEXT NOT NULL REFERENCES refs(reference_id) ON DELETE CASCADE,
        PRIMARY KEY (term, reference_id)
    )""",
    "CREATE INDEX idx_be_terms_ref ON be_terms(reference_id)",
))

BE004 = Migration(4, "gateway_e_idempotencia_da_api", (
    """CREATE TABLE be_gateway_requests (
        request_id     TEXT PRIMARY KEY,
        provider       TEXT NOT NULL,
        model          TEXT NOT NULL,
        prompt_version TEXT NOT NULL,
        reference_id   TEXT,
        evidence_sha256 TEXT NOT NULL,
        request_sha256 TEXT NOT NULL,
        state          TEXT NOT NULL CHECK (state IN ('pending_approval','approved','running','completed','failed',
                                                       'rejected','cancelled','timeout')),
        budget_json    TEXT NOT NULL,
        approved_by    TEXT,
        result_json    TEXT,
        usage_json     TEXT,
        error          TEXT,
        attempts       INTEGER NOT NULL DEFAULT 0,
        created_at     REAL NOT NULL,
        finished_at    REAL
    )""",
    """CREATE TABLE be_gateway_attempts (
        attempt_id   INTEGER PRIMARY KEY,
        request_id   TEXT NOT NULL REFERENCES be_gateway_requests(request_id) ON DELETE CASCADE,
        attempt_no   INTEGER NOT NULL,
        started_at   REAL NOT NULL,
        finished_at  REAL,
        outcome      TEXT,
        error        TEXT
    )""",
    "CREATE INDEX idx_be_gateway_window ON be_gateway_attempts(started_at)",
    """CREATE TABLE be_api_requests (
        idempotency_key TEXT PRIMARY KEY,
        operation       TEXT NOT NULL,
        request_sha256  TEXT NOT NULL,
        response_json   TEXT NOT NULL,
        created_at      REAL NOT NULL
    )""",
))

# BE005 (benchmark de 1.000 referências): o claim varria todos os jobs elegíveis com NOT EXISTS e ordenava numa árvore
# temporária a cada chamada (6,9 ms com 4.000 jobs; vazão de 501 → 93 jobs/s de 82 para 1.000 referências).
# `blocked_deps` (dependências ainda não concluídas) é mantida pela fila e o índice parcial entrega o próximo job
# já na ordem do claim.
BE005 = Migration(5, "indice_de_claim_e_dependencias_pendentes", (
    "ALTER TABLE be_jobs ADD COLUMN blocked_deps INTEGER NOT NULL DEFAULT 0",
    "UPDATE be_jobs SET blocked_deps = (SELECT COUNT(*) FROM be_job_deps d JOIN be_jobs p ON p.job_id = d.depends_on "
    "WHERE d.job_id = be_jobs.job_id AND p.state <> 'completed')",
    "CREATE INDEX idx_be_jobs_claim ON be_jobs(priority, not_before, created_at, job_id) "
    "WHERE state IN ('queued','retry_scheduled','waiting_dependency') AND blocked_deps = 0 AND cancel_requested = 0",
    "CREATE INDEX idx_be_jobs_running_kind ON be_jobs(state, kind)",
))

BE_MIGRATIONS: Tuple[Migration, ...] = (BE001, BE002, BE003, BE004, BE005)
BE_LATEST = BE_MIGRATIONS[-1].version


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def migrate_backend(conn: sqlite3.Connection, migrations: Sequence[Migration] = BE_MIGRATIONS) -> List[int]:
    """Aplica as migrações do backend (trilha `be_schema_migrations`), depois das do `ii_mm`."""
    versions = [m.version for m in migrations]
    if versions != list(range(1, len(versions) + 1)):
        raise MigrationError("migrações do backend devem ser sequenciais e começar em 1")
    conn.execute("""CREATE TABLE IF NOT EXISTS be_schema_migrations (
        version INTEGER PRIMARY KEY, name TEXT NOT NULL, checksum TEXT NOT NULL, applied_at TEXT NOT NULL)""")
    done = {r["version"]: r for r in conn.execute("SELECT * FROM be_schema_migrations")}
    if done and max(done) > versions[-1]:
        raise IncompatibleSchemaError(f"backend no banco na versão {max(done)}; o código conhece até {versions[-1]}")
    known = {m.version: m for m in migrations}
    for v, row in done.items():
        if row["checksum"] != known[v].checksum:
            raise MigrationError(f"migração do backend {v} ({row['name']}) foi alterada depois de aplicada")
    applied_now = []
    for m in migrations:
        if m.version in done:
            continue
        conn.execute("BEGIN IMMEDIATE")
        try:
            for stmt in m.statements:
                conn.execute(stmt)
            conn.execute("INSERT INTO be_schema_migrations(version, name, checksum, applied_at) VALUES (?,?,?,?)",
                         (m.version, m.name, m.checksum, _now_iso()))
            conn.execute("COMMIT")
        except Exception as exc:
            conn.execute("ROLLBACK")
            raise MigrationError(f"migração do backend {m.version} ({m.name}) falhou e foi desfeita: {exc}") from exc
        applied_now.append(m.version)
    return applied_now


def open_engine_db(path: str | Path = ":memory:") -> sqlite3.Connection:
    """Conecta (recusa `catalog.sqlite`), migra o `ii_mm` e o backend. Banco SEMPRE separado do catálogo legado."""
    conn = connect(path)
    migrate(conn)
    migrate_backend(conn)
    return conn


class Busy(sqlite3.OperationalError):
    """Banco ocupado além do tempo de espera configurado."""


@contextmanager
def tx(conn: sqlite3.Connection, retries: int = 5, base_sleep: float = 0.02) -> Iterator[sqlite3.Connection]:
    """Transação `BEGIN IMMEDIATE` com nova tentativa só na ABERTURA (antes de qualquer escrita).

    O `busy_timeout` da conexão (5 s) já espera o bloqueio; as tentativas extras cobrem o caso de outro
    processo segurar a escrita por mais tempo. Depois de aberta, qualquer erro desfaz tudo.
    """
    if conn.in_transaction:
        raise RuntimeError("transação aninhada: o chamador já está numa transação")
    for i in range(retries + 1):
        try:
            conn.execute("BEGIN IMMEDIATE")
            break
        except sqlite3.OperationalError as exc:
            if "locked" not in str(exc) and "busy" not in str(exc):
                raise
            if i == retries:
                raise Busy(f"banco ocupado após {retries + 1} tentativas: {exc}") from exc
            time.sleep(base_sleep * (2 ** i))
    try:
        yield conn
        conn.execute("COMMIT")
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise

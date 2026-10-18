"""Migrações SQLite versionadas (Tarefa 06).

- `schema_migrations(version, name, checksum, applied_at)` registra cada migração aplicada.
- Migrações são sequenciais; cada uma roda numa transação explícita e é desfeita por inteiro se falhar.
- O checksum (SHA-256 do SQL) detecta migração já aplicada que foi editada depois: erro, nunca silêncio.
- Banco com versão MAIOR que a conhecida pelo código é recusado (código antigo não escreve em esquema novo).
- Reaplicar é idempotente: nada acontece se tudo já estiver aplicado.
- `connect()` recusa caminhos com nome de banco de produção (`catalog.sqlite`).
"""
from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

PRODUCTION_DB_NAMES = {"catalog.sqlite", "catalog.sqlite3", "catalog.db"}


class MigrationError(RuntimeError):
    pass


class IncompatibleSchemaError(MigrationError):
    pass


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    statements: Tuple[str, ...]

    @property
    def checksum(self) -> str:
        return hashlib.sha256("\n;\n".join(s.strip() for s in self.statements).encode("utf-8")).hexdigest()


M001 = Migration(1, "nucleo_referencias_videos_analises", (
    """CREATE TABLE refs (
        reference_id   TEXT PRIMARY KEY,
        platform       TEXT NOT NULL,
        canonical_key  TEXT NOT NULL UNIQUE,
        origin_url     TEXT,
        author_handle  TEXT,
        subject        TEXT,
        created_at     TEXT NOT NULL
    )""",
    """CREATE TABLE ref_aliases (
        alias_key      TEXT PRIMARY KEY,
        reference_id   TEXT NOT NULL REFERENCES refs(reference_id) ON DELETE CASCADE,
        seen_url       TEXT,
        created_at     TEXT NOT NULL
    )""",
    """CREATE TABLE videos (
        video_pk        INTEGER PRIMARY KEY,
        content_sha256  TEXT UNIQUE CHECK (content_sha256 IS NULL OR length(content_sha256) = 64),
        duration_s      REAL NOT NULL CHECK (duration_s > 0),
        width INTEGER, height INTEGER, fps REAL,
        created_at      TEXT NOT NULL
    )""",
    """CREATE TABLE ref_videos (
        reference_id TEXT NOT NULL REFERENCES refs(reference_id) ON DELETE CASCADE,
        video_pk     INTEGER NOT NULL REFERENCES videos(video_pk) ON DELETE RESTRICT,
        platform_video_id TEXT,
        PRIMARY KEY (reference_id, video_pk)
    )""",
    """CREATE TABLE analyses (
        analysis_id        TEXT PRIMARY KEY,
        video_pk           INTEGER NOT NULL REFERENCES videos(video_pk) ON DELETE RESTRICT,
        schema_version     TEXT NOT NULL,
        classifier_version TEXT,
        input_hash         TEXT NOT NULL,
        status             TEXT NOT NULL CHECK (status IN ('current','superseded')),
        superseded_by      TEXT REFERENCES analyses(analysis_id),
        created_at         TEXT NOT NULL,
        document_json      TEXT NOT NULL,
        UNIQUE (video_pk, input_hash)
    )""",
))

M002 = Migration(2, "evidencias_segmentos_categorias_ferramentas_tecnicas", (
    """CREATE TABLE segments (
        analysis_id TEXT NOT NULL REFERENCES analyses(analysis_id) ON DELETE CASCADE,
        segment_id  TEXT NOT NULL,
        t_start_s REAL NOT NULL, t_end_s REAL NOT NULL CHECK (t_end_s >= t_start_s),
        text TEXT NOT NULL, source TEXT,
        PRIMARY KEY (analysis_id, segment_id)
    )""",
    """CREATE TABLE evidence (
        analysis_id TEXT NOT NULL REFERENCES analyses(analysis_id) ON DELETE CASCADE,
        evidence_id TEXT NOT NULL,
        status TEXT NOT NULL CHECK (status IN ('observed_visual','measured_signal','transcript_claim','metadata_claim','inference','unverified')),
        source_type TEXT NOT NULL, claim TEXT NOT NULL,
        t_start_s REAL, t_end_s REAL, ref TEXT, tag TEXT, basis TEXT,
        provenance_json TEXT NOT NULL,
        PRIMARY KEY (analysis_id, evidence_id)
    )""",
    """CREATE TABLE categories (
        analysis_id TEXT NOT NULL REFERENCES analyses(analysis_id) ON DELETE CASCADE,
        category TEXT NOT NULL,
        support TEXT NOT NULL CHECK (support IN ('supported_visual','supported_measured','mentioned_speech','suggested_metadata','hypothesis','insufficient')),
        auto_review_state TEXT NOT NULL DEFAULT 'pending',
        PRIMARY KEY (analysis_id, category)
    )""",
    """CREATE TABLE category_evidence (
        analysis_id TEXT NOT NULL, category TEXT NOT NULL, evidence_id TEXT NOT NULL,
        role TEXT NOT NULL CHECK (role IN ('pro','contra','context')),
        PRIMARY KEY (analysis_id, category, evidence_id, role),
        FOREIGN KEY (analysis_id, category) REFERENCES categories(analysis_id, category) ON DELETE CASCADE,
        FOREIGN KEY (analysis_id, evidence_id) REFERENCES evidence(analysis_id, evidence_id) ON DELETE CASCADE
    )""",
    """CREATE TABLE tools (
        analysis_id TEXT NOT NULL REFERENCES analyses(analysis_id) ON DELETE CASCADE,
        name TEXT NOT NULL, status TEXT NOT NULL,
        PRIMARY KEY (analysis_id, name)
    )""",
    """CREATE TABLE techniques (
        analysis_id TEXT NOT NULL REFERENCES analyses(analysis_id) ON DELETE CASCADE,
        technique TEXT NOT NULL, level TEXT NOT NULL,
        PRIMARY KEY (analysis_id, technique, level)
    )""",
    """CREATE TABLE search_terms (
        analysis_id TEXT NOT NULL REFERENCES analyses(analysis_id) ON DELETE CASCADE,
        term TEXT NOT NULL,
        PRIMARY KEY (term, analysis_id)
    )""",
))

M003 = Migration(3, "processamento_revisoes_pendencias", (
    """CREATE TABLE processing_state (
        video_pk INTEGER NOT NULL REFERENCES videos(video_pk) ON DELETE CASCADE,
        stage TEXT NOT NULL,
        status TEXT NOT NULL CHECK (status IN ('running','done','failed')),
        attempt INTEGER NOT NULL DEFAULT 1,
        input_hash TEXT,
        output_ref TEXT,
        error TEXT,
        updated_at TEXT NOT NULL,
        PRIMARY KEY (video_pk, stage)
    )""",
    """CREATE TABLE reviews (
        review_id TEXT PRIMARY KEY,
        reference_id TEXT NOT NULL REFERENCES refs(reference_id) ON DELETE CASCADE,
        analysis_id TEXT REFERENCES analyses(analysis_id),
        seq INTEGER NOT NULL,
        at TEXT NOT NULL, reviewer TEXT NOT NULL,
        action TEXT NOT NULL, target TEXT NOT NULL,
        before_json TEXT, after_json TEXT, justification TEXT,
        UNIQUE (reference_id, seq)
    )""",
    """CREATE TABLE issues (
        issue_id INTEGER PRIMARY KEY,
        video_pk INTEGER REFERENCES videos(video_pk) ON DELETE CASCADE,
        analysis_id TEXT REFERENCES analyses(analysis_id) ON DELETE CASCADE,
        kind TEXT NOT NULL CHECK (kind IN ('error','pending','conflict')),
        description TEXT NOT NULL,
        blocking INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL,
        resolved_at TEXT
    )""",
))

M004 = Migration(4, "indices_de_consulta", (
    "CREATE INDEX idx_analyses_current ON analyses(status, video_pk)",
    "CREATE INDEX idx_ref_videos_video ON ref_videos(video_pk)",
    "CREATE INDEX idx_refs_platform_created ON refs(platform, created_at, reference_id)",
    "CREATE INDEX idx_refs_author ON refs(author_handle)",
    "CREATE INDEX idx_evidence_tag ON evidence(tag)",
    "CREATE INDEX idx_evidence_time ON evidence(analysis_id, t_start_s)",
    "CREATE INDEX idx_categories_lookup ON categories(category, support, analysis_id)",
    "CREATE INDEX idx_category_evidence_ev ON category_evidence(analysis_id, evidence_id)",
    "CREATE INDEX idx_tools_name ON tools(name, status)",
    "CREATE INDEX idx_techniques_name ON techniques(technique, level)",
    "CREATE INDEX idx_issues_open ON issues(resolved_at, kind)",
    "CREATE INDEX idx_reviews_ref ON reviews(reference_id, seq)",
))

M005 = Migration(5, "estado_corrente_de_revisao", (
    """CREATE TABLE review_state (
        reference_id TEXT NOT NULL REFERENCES refs(reference_id) ON DELETE CASCADE,
        target TEXT NOT NULL,
        state TEXT NOT NULL,
        value_json TEXT,
        review_id TEXT NOT NULL REFERENCES reviews(review_id),
        updated_at TEXT NOT NULL,
        PRIMARY KEY (reference_id, target)
    )""",
    "CREATE INDEX idx_review_state_target ON review_state(target, state)",
))

# M006 surgiu do EXPLAIN do catálogo: sem este índice cada página ordenava o conjunto inteiro (TEMP B-TREE).
M006 = Migration(6, "indice_de_paginacao_do_catalogo", (
    "CREATE INDEX idx_refs_created ON refs(created_at, reference_id)",
))

MIGRATIONS: Tuple[Migration, ...] = (M001, M002, M003, M004, M005, M006)
LATEST_VERSION = MIGRATIONS[-1].version


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(path: str | Path = ":memory:", allow_production_name: bool = False) -> sqlite3.Connection:
    p = str(path)
    if p != ":memory:" and Path(p).name.lower() in PRODUCTION_DB_NAMES and not allow_production_name:
        raise MigrationError(f"recusado: {Path(p).name} é nome de banco de produção; use um banco isolado")
    conn = sqlite3.connect(p, isolation_level=None)  # transações explícitas
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    if p != ":memory:":
        conn.execute("PRAGMA journal_mode = WAL")
    return conn


def current_version(conn: sqlite3.Connection) -> int:
    has = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_migrations'").fetchone()
    if not has:
        return 0
    row = conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()
    return int(row[0] or 0)


def applied(conn: sqlite3.Connection) -> List[sqlite3.Row]:
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_migrations'").fetchone():
        return []
    return conn.execute("SELECT version, name, checksum, applied_at FROM schema_migrations ORDER BY version").fetchall()


def migrate(conn: sqlite3.Connection, migrations: Sequence[Migration] = MIGRATIONS,
            target: Optional[int] = None) -> List[int]:
    """Aplica as migrações pendentes até `target` (padrão: a última). Devolve as versões aplicadas."""
    versions = [m.version for m in migrations]
    if versions != sorted(versions) or len(set(versions)) != len(versions) or versions[:1] not in ([], [1]):
        raise MigrationError("migrações devem ser sequenciais e únicas, começando em 1")
    for a, b in zip(versions, versions[1:]):
        if b != a + 1:
            raise MigrationError(f"lacuna na sequência de migrações: {a} -> {b}")
    known = {m.version: m for m in migrations}
    target = versions[-1] if target is None else target
    if target not in known and target != 0:
        raise MigrationError(f"versão alvo desconhecida: {target}")

    conn.execute("""CREATE TABLE IF NOT EXISTS schema_migrations (
        version INTEGER PRIMARY KEY, name TEXT NOT NULL, checksum TEXT NOT NULL, applied_at TEXT NOT NULL)""")
    done = {r["version"]: r for r in conn.execute("SELECT * FROM schema_migrations").fetchall()}
    if done and max(done) > versions[-1]:
        raise IncompatibleSchemaError(f"banco na versão {max(done)}, código conhece até {versions[-1]}")
    for v, row in done.items():
        if row["checksum"] != known[v].checksum:
            raise MigrationError(f"migração {v} ({row['name']}) foi alterada depois de aplicada (checksum diverge)")
    if done and sorted(done) != list(range(1, max(done) + 1)):
        raise MigrationError(f"histórico de migrações com lacunas: {sorted(done)}")

    applied_now = []
    for m in migrations:
        if m.version in done or m.version > target:
            continue
        conn.execute("BEGIN IMMEDIATE")
        try:
            for stmt in m.statements:
                conn.execute(stmt)
            conn.execute("INSERT INTO schema_migrations(version, name, checksum, applied_at) VALUES (?,?,?,?)",
                         (m.version, m.name, m.checksum, _now()))
            violations = conn.execute("PRAGMA foreign_key_check").fetchall()
            if violations:
                raise MigrationError(f"migração {m.version} deixaria violações de chave estrangeira: {len(violations)}")
            conn.execute("COMMIT")
        except Exception as exc:
            conn.execute("ROLLBACK")
            if isinstance(exc, MigrationError):
                raise
            raise MigrationError(f"migração {m.version} ({m.name}) falhou e foi desfeita: {exc}") from exc
        applied_now.append(m.version)
    return applied_now


def open_database(path: str | Path = ":memory:") -> sqlite3.Connection:
    """Conecta e migra até a última versão (uso típico em fixtures e na demonstração)."""
    conn = connect(path)
    migrate(conn)
    return conn

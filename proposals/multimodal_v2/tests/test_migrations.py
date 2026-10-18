import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

from tests import _helpers  # noqa: F401
from ii_mm.db.migrations import (
    LATEST_VERSION, MIGRATIONS, IncompatibleSchemaError, Migration, MigrationError, applied, connect,
    current_version, migrate, open_database,
)


def fresh(tc):
    c = connect()
    tc.addCleanup(c.close)
    return c


def opened(tc):
    c = open_database()
    tc.addCleanup(c.close)
    return c


def tables(conn):
    return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


class MigrationTest(unittest.TestCase):
    def test_fresh_database_reaches_latest_and_is_idempotent(self):
        conn = fresh(self)
        self.assertEqual(migrate(conn), [1, 2, 3, 4])
        self.assertEqual(current_version(conn), LATEST_VERSION)
        self.assertEqual(migrate(conn), [])
        self.assertEqual(len(applied(conn)), 4)
        self.assertTrue({"refs", "videos", "analyses", "evidence", "reviews", "processing_state", "issues"} <= tables(conn))

    def test_stepwise_upgrade(self):
        conn = fresh(self)
        self.assertEqual(migrate(conn, target=2), [1, 2])
        self.assertNotIn("reviews", tables(conn))
        self.assertEqual(migrate(conn), [3, 4])

    def test_failed_migration_rolls_back_entirely(self):
        bad = Migration(5, "quebrada", ("CREATE TABLE nova_ok (x INTEGER)", "CREATE TABLE refs (x INTEGER)"))
        conn = opened(self)
        with self.assertRaises(MigrationError) as ctx:
            migrate(conn, MIGRATIONS + (bad,))
        self.assertIn("desfeita", str(ctx.exception))
        self.assertNotIn("nova_ok", tables(conn))
        self.assertEqual(current_version(conn), 4)

    def test_edited_applied_migration_is_detected(self):
        conn = opened(self)
        tampered = list(MIGRATIONS)
        tampered[1] = Migration(2, MIGRATIONS[1].name, MIGRATIONS[1].statements + ("CREATE TABLE extra (x)",))
        with self.assertRaises(MigrationError) as ctx:
            migrate(conn, tuple(tampered))
        self.assertIn("checksum", str(ctx.exception))

    def test_newer_database_refused(self):
        conn = opened(self)
        conn.execute("INSERT INTO schema_migrations VALUES (99, 'do_futuro', 'x', 'agora')")
        with self.assertRaises(IncompatibleSchemaError):
            migrate(conn)

    def test_sequence_validation(self):
        with self.assertRaises(MigrationError):
            migrate(fresh(self), (MIGRATIONS[0], MIGRATIONS[2]))
        with self.assertRaises(MigrationError):
            migrate(fresh(self), (MIGRATIONS[1],))
        with self.assertRaises(MigrationError):
            migrate(fresh(self), target=42)

    def test_history_gap_detected(self):
        conn = opened(self)
        conn.execute("DELETE FROM schema_migrations WHERE version = 2")
        with self.assertRaises(MigrationError):
            migrate(conn)

    def test_foreign_keys_and_checks_enforced(self):
        conn = opened(self)
        with self.assertRaises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO evidence(analysis_id, evidence_id, status, source_type, claim, provenance_json) "
                         "VALUES ('nao_existe','e','observed_visual','x','y','{}')")
        with self.assertRaises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO videos(content_sha256, duration_s, created_at) VALUES ('curto', 1, 'x')")
        with self.assertRaises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO videos(duration_s, created_at) VALUES (-1, 'x')")

    def test_production_name_refused(self):
        for name in ("catalog.sqlite", "CATALOG.SQLITE", "catalog.db"):
            with self.assertRaises(MigrationError):
                connect(Path(tempfile.gettempdir()) / name)

    def test_file_database_uses_wal(self):
        with tempfile.TemporaryDirectory() as d:
            conn = open_database(Path(d) / "ii_test.sqlite")
            self.assertEqual(conn.execute("PRAGMA journal_mode").fetchone()[0], "wal")
            conn.close()
            again = connect(Path(d) / "ii_test.sqlite")
            self.assertEqual(current_version(again), LATEST_VERSION)
            again.close()

    def test_checksums_are_stable(self):
        self.assertEqual(MIGRATIONS[0].checksum, Migration(1, "outro_nome", MIGRATIONS[0].statements).checksum)
        self.assertEqual(len({m.checksum for m in MIGRATIONS}), len(MIGRATIONS))


@unittest.skipUnless(os.environ.get("PROJETO_MVP_DIR"), "defina PROJETO_MVP_DIR para reproduzir o problema legado")
class LegacyNoSuchTableReproductionTest(unittest.TestCase):
    """Reproduz e corrige, em banco temporário, o 'no such table: instagram_items' da auditoria."""

    def setUp(self):
        self.projeto = Path(os.environ["PROJETO_MVP_DIR"]).resolve()
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "legacy_test.sqlite"

    def tearDown(self):
        self.tmp.cleanup()

    def test_reproduces_failure_without_base_table(self):
        from ii_mm.db.legacy_fixture import build_legacy_catalog  # noqa: F401 (garante sys.path)
        import sys
        sys.path.insert(0, str(self.projeto))
        from core import curation
        with self.assertRaises(sqlite3.OperationalError) as ctx:
            curation.run_preliminary_curation(self.db)
        self.assertIn("instagram_items", str(ctx.exception))

    def test_fixture_builds_schema_in_dependency_order(self):
        from ii_mm.db.legacy_fixture import build_legacy_catalog
        build_legacy_catalog(self.db, self.projeto)
        from core import content_miner, curation
        stats = curation.run_preliminary_curation(self.db)
        self.assertEqual(stats.total_items, 0)
        self.assertEqual(content_miner.mine_catalog_opportunities(self.db), 0)
        with sqlite3.connect(str(self.db)) as conn:
            cols = {r[1] for r in conn.execute("PRAGMA table_info(instagram_items)")}
        self.assertTrue({"canonical_shortcode", "media_status", "curation_category", "quality_rating"} <= cols)

    def test_fixture_refuses_production_name(self):
        from ii_mm.db.legacy_fixture import build_legacy_catalog
        with self.assertRaises(RuntimeError):
            build_legacy_catalog(Path(self.tmp.name) / "catalog.sqlite", self.projeto)


if __name__ == "__main__":
    unittest.main()

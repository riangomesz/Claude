"""Missão Suprema 02, Etapa C (T08/T09): concorrência, interrupções e filtros sem resultado."""
import json
import os
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from tests import _helpers  # noqa: F401
from ii_mm.catalog import Query, search
from ii_mm.db.migrations import open_database
from ii_mm.db.repository import Repository
from ii_mm.pipeline import STAGES, Pipeline
from ii_mm.synthetic import make_reference


class C1PipelineLeaseTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        db = Path(self.tmp.name) / "lease.sqlite"
        self.a, self.b = open_database(db), open_database(db)
        self.addCleanup(self.a.close); self.addCleanup(self.b.close)
        self.a.execute("INSERT INTO videos(video_pk, duration_s, created_at) VALUES (1, 10, 'x')")
        self.log = []
        self.now = [1000.0]

    def handlers(self, who, hook=None):
        def make(s):
            def h(ctx):
                self.log.append((who, s))
                if hook:
                    hook(s)
                return f"{s}:{who}"
            return h
        return {s: make(s) for s in STAGES}

    def test_second_runner_does_not_steal_a_live_stage(self):
        pb = Pipeline(self.b, self.handlers("B"), owner="runner-B", clock=lambda: self.now[0])
        reports = []
        pa = Pipeline(self.a, self.handlers("A", hook=lambda s: s == "audio_processed" and reports.append(pb.run(1))),
                      owner="runner-A", clock=lambda: self.now[0])
        pa.run(1)
        self.assertEqual(reports[0].state, "busy")
        self.assertIn("runner-A", reports[0].error)
        self.assertEqual([s for w, s in self.log if w == "B"], [])

    def test_crashed_runner_lease_expires_then_other_resumes(self):
        def crash(s):
            if s == "visual_processed":
                raise KeyboardInterrupt
        pa = Pipeline(self.a, self.handlers("A", hook=crash), owner="runner-A", lease_s=60, clock=lambda: self.now[0])
        with self.assertRaises(KeyboardInterrupt):
            pa.run(1)
        pb = Pipeline(self.b, self.handlers("B"), owner="runner-B", lease_s=60, clock=lambda: self.now[0])
        self.assertEqual(pb.run(1).state, "busy")
        self.now[0] += 61
        r = pb.run(1)
        self.assertEqual(r.executed[0], "visual_processed")
        self.assertNotIn(("B", "media_available"), self.log)

    def test_same_owner_resumes_immediately_after_crash(self):
        flag = {"crash": True}

        def crash(s):
            if s == "classified" and flag.pop("crash", False):
                raise KeyboardInterrupt
        pa = Pipeline(self.a, self.handlers("A", hook=crash), owner="runner-A", clock=lambda: self.now[0])
        with self.assertRaises(KeyboardInterrupt):
            pa.run(1)
        self.assertEqual(pa.run(1).executed[0], "classified")


class InterruptionRecoveryTest(unittest.TestCase):
    def test_keyboard_interrupt_during_save_rolls_back_and_db_stays_usable(self):
        conn = open_database(); self.addCleanup(conn.close)
        repo = Repository(conn)
        with mock.patch.object(Repository, "_insert_children", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                repo.save_analysis(make_reference(1))
        self.assertFalse(conn.in_transaction)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM refs").fetchone()[0], 0)
        self.assertTrue(repo.save_analysis(make_reference(1)).created)

    def test_interrupted_export_recovers_without_temp_files(self):
        from ii_mm.classifier import Classifier
        from ii_mm.obsidian_export import export_reference
        doc = Classifier().classify(make_reference(2))
        with tempfile.TemporaryDirectory() as t:
            stage = Path(t)
            real_replace = os.replace
            calls = {"n": 0}

            def flaky(src, dst):
                calls["n"] += 1
                if str(dst).endswith(".json"):
                    raise OSError("disco cheio (simulado)")
                return real_replace(src, dst)
            with mock.patch("ii_mm.obsidian_export.os.replace", side_effect=flaky):
                with self.assertRaises(OSError):
                    export_reference(doc, stage)
            self.assertEqual([p.name for p in stage.iterdir() if p.name.startswith(".ii_tmp_")], [])
            r = export_reference(doc, stage)
            self.assertEqual((r["markdown"], r["json"]), ("unchanged", "created"))
            self.assertEqual(json.loads(next(stage.glob("*.json")).read_text(encoding="utf-8"))["video"]["video_id"], doc["video"]["video_id"])

    def test_concurrent_writers_on_same_file(self):
        with tempfile.TemporaryDirectory() as t:
            db = Path(t) / "conc.sqlite"
            open_database(db).close()
            errors = []

            def worker(start):
                conn = open_database(db)
                try:
                    repo = Repository(conn)
                    for i in range(start, start + 40):
                        repo.save_analysis(make_reference(i))
                except Exception as exc:  # noqa: BLE001
                    errors.append(repr(exc))
                finally:
                    conn.close()
            threads = [threading.Thread(target=worker, args=(k * 40,)) for k in range(4)]
            for th in threads:
                th.start()
            for th in threads:
                th.join()
            self.assertEqual(errors, [])
            conn = open_database(db)
            try:
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM analyses").fetchone()[0], 160)
                self.assertEqual(conn.execute("PRAGMA integrity_check").fetchone()[0], "ok")
                self.assertEqual(conn.execute("PRAGMA foreign_key_check").fetchall(), [])
            finally:
                conn.close()


class T08ZeroResultFiltersTest(unittest.TestCase):
    def setUp(self):
        self.conn = open_database(); self.addCleanup(self.conn.close)
        repo = Repository(self.conn)
        for i in range(50):
            repo.save_analysis(make_reference(i))

    def test_absent_value_short_circuits_without_scanning_catalog(self):
        statements = []
        self.conn.set_trace_callback(statements.append)
        try:
            page = search(self.conn, Query(tool="Ferramenta Inexistente"))
        finally:
            self.conn.set_trace_callback(None)
        self.assertEqual((page.items, page.next_cursor), ([], None))
        self.assertFalse(any("FROM refs r" in s for s in statements), "varreu o catálogo para um filtro sem nenhum valor")

    def test_short_circuit_never_hides_real_results(self):
        for q in (Query(category="tutorial"), Query(platform="youtube"), Query(evidence_tag="ui_screen_visible")):
            with_check = [r["reference_id"] for r in search(self.conn, q, limit=200).items]
            raw = self.conn.execute("SELECT COUNT(*) FROM refs").fetchone()[0]
            self.assertLessEqual(len(with_check), raw)
        self.assertTrue(search(self.conn, Query(category="tutorial"), limit=200).items)


if __name__ == "__main__":
    unittest.main()

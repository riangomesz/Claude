"""Tarefa 22: a demonstração ponta a ponta é executável de novo com resultado idêntico."""
import json
import tempfile
import unittest
from pathlib import Path

from tests import _util  # noqa: F401
from ii_be.demo import run_demo


class DemoTest(unittest.TestCase):
    def test_reproducible_end_to_end(self):
        runs = []
        for _ in range(2):
            with tempfile.TemporaryDirectory(prefix="ii_be_demo_test_") as t:
                runs.append(json.dumps(run_demo(Path(t)), ensure_ascii=False, sort_keys=True, default=list))
        self.assertEqual(runs[0], runs[1])
        out = json.loads(runs[0])
        v = out["18_verification"]
        self.assertEqual((v["references"], v["stage_results_duplicated"], v["jobs_completed_twice"], v["pending_jobs"]), (4, 0, 0, 0))
        self.assertEqual(v["integrity_check"], "ok")
        self.assertTrue(v["events_consumed_once"])
        self.assertEqual(out["16_interruption"]["job_state"], "running")
        self.assertEqual(out["17_resumed"]["attempts"], ["lease_lost", "completed"])
        self.assertEqual(out["13_index_updated"]["reran"], ["index:completed", "export:completed"])
        self.assertTrue(out["3_dedup"]["meta_export_item_matched_existing"])
        self.assertNotIn("SYNTHcompartilhamento", runs[0])          # parâmetro de compartilhamento descartado
        self.assertTrue(out["synthetic"])


if __name__ == "__main__":
    unittest.main()

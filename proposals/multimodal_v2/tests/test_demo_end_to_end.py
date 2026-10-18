import importlib.util
import tempfile
import unittest
from pathlib import Path

from tests import _helpers  # noqa: F401
from ii_mm.demo import run_demo

ROOT = Path(__file__).resolve().parents[1]


class EndToEndTest(unittest.TestCase):
    def test_full_flow(self):
        with tempfile.TemporaryDirectory() as t:
            r = run_demo(Path(t))
            note = Path(r["note_path"]).read_text(encoding="utf-8")
            names = {p.name for p in Path(t).iterdir()}
            self.assertTrue({"demo_ii.sqlite", "obsidian_staging"} <= names)
            self.assertFalse({n for n in names if not n.startswith(("demo_ii.sqlite", "obsidian_staging"))})  # nada vaza fora
        self.assertEqual(r["normalization"]["rejected"], 0)
        self.assertEqual(r["normalization"]["adapter_errors"], 0)
        self.assertEqual(r["downgraded"], ["'animated_caption': movimento não se prova com frame_pair; registrado como inference"])
        self.assertEqual(r["categories"]["demonstracao_ferramenta"], "supported_visual")
        self.assertEqual(r["categories"]["tutorial"], "mentioned_speech")
        self.assertEqual(r["tools"], {"CapCut": "visually_identified"})
        self.assertIn(("legenda_animada", "hypothesis"), r["techniques"])
        self.assertIn(("punch_in", "frame_pair_difference"), r["techniques"])
        self.assertNotIn(("legenda_animada", "temporal_sequence"), r["techniques"])
        self.assertTrue(r["persist"]["created"])
        self.assertFalse(r["persist"]["idempotent_resave_created"])
        self.assertEqual(r["query_visual_tool_hits"], ["ref_DEMO01"])
        self.assertEqual(r["query_time_range_hits"], ["ref_DEMO01"])
        self.assertEqual(r["review"], {"history": 2, "tutorial_state": "accepted", "tool_after": "CapCut (desktop)", "original_untouched": True})
        self.assertEqual((r["export_first"], r["export_second"]), ("created", "unchanged"))
        self.assertEqual(r["n8n"], {"state": "awaiting_review", "next_action": "await_review", "replayed": True})
        self.assertIn("100% automático", note)
        self.assertIn("não verificado", note)
        self.assertIn("CapCut (desktop)", note)


class BenchmarkSmokeTest(unittest.TestCase):
    def test_benchmark_runs_on_tiny_load(self):
        spec = importlib.util.spec_from_file_location("ii_benchmark", ROOT / "tools" / "benchmark.py")
        bench = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(bench)
        with tempfile.TemporaryDirectory() as t:
            r = bench.run_size(25, seed=3, workdir=Path(t))
        self.assertEqual(r["duplicates_created"], 0)
        self.assertEqual(r["resave_new_rows"], 0)
        self.assertEqual(r["row_counts"]["refs"], 25)
        self.assertEqual(r["resume"]["repeated_executions"], 1)       # só a etapa interrompida roda de novo
        self.assertEqual(r["resume"]["rerun_all_done_calls"], 0)      # tudo concluído = nada a refazer
        self.assertEqual(r["scan_paginated"]["rows"], 25)


if __name__ == "__main__":
    unittest.main()

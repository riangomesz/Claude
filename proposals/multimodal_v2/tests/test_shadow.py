import hashlib
import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

from tests import _helpers  # noqa: F401
from ii_mm.shadow import compare_row, read_legacy_rows_readonly, render_markdown, run_shadow

ROWS = json.loads((Path(__file__).resolve().parents[1] / "fixtures" / "legacy" / "shadow_rows.json").read_text(encoding="utf-8"))


class ShadowReportTest(unittest.TestCase):
    def setUp(self):
        self.rep = run_shadow(ROWS)
        self.by = {i.get("item_id"): i for i in self.rep["items"]}

    def test_kinds(self):
        self.assertEqual(self.by["SYNTHsh01"]["kind"], "agree_plus_new")   # multi-rótulo: motion (legado) + tutorial
        self.assertEqual(sorted(self.by["SYNTHsh01"]["new"]), ["motion_design", "tutorial"])
        self.assertEqual(self.by["SYNTHsh02"]["kind"], "only_legacy")      # defeito legado conhecido (bot em robotics)
        self.assertEqual(self.by["SYNTHsh03"]["kind"], "agree_none")
        self.assertEqual(self.by["SYNTHsh06"]["kind"], "only_new")          # sem legenda, com fala
        self.assertEqual(self.by[None]["status"], "blocked")
        self.assertEqual(self.rep["writes_performed"], 0)

    def test_divergences_expose_responsible_evidence(self):
        d = self.by["SYNTHsh06"]
        ev = d["new"]["tutorial"]["evidence"][0]
        self.assertEqual(ev["status"], "transcript_claim")
        self.assertIn("passo a passo", ev["terms"])
        self.assertIn("termos_genericos", self.by["SYNTHsh02"]["legacy"]["curation_rule"])

    def test_human_labels_enable_fp_fn_inspection_without_accuracy(self):
        h = self.rep["human_reference"]
        self.assertEqual(h["rows_with_human_label"], 2)
        self.assertIn("SYNTHsh05", h["new_misses_human_label"])            # humano disse Design; novo vê automação
        self.assertIn("SYNTHsh05", h["new_adds_beyond_human"])
        self.assertNotIn("accuracy", json.dumps(self.rep))
        self.assertNotIn("%", json.dumps(self.rep["totals"]))
        self.assertIn("não há como dizer qual classificador acerta", self.rep["caveat"])

    def test_human_label_is_not_treated_as_legacy_prediction(self):
        self.assertIsNone(self.by["SYNTHsh04"]["legacy"]["label"])

    def test_markdown_render(self):
        md = render_markdown(self.rep)
        self.assertIn("SYNTHsh06 — only_new", md)
        self.assertIn("possível falso negativo", md)

    def test_injected_legacy_function(self):
        calls = []

        def fake_suggest(caption, hashtags, owner, post_type):
            calls.append(caption)
            return {"suggested_category": "Automação", "reason": "fake"}
        out = compare_row(ROWS[0], legacy_suggest=fake_suggest)
        self.assertEqual(out["legacy"]["label"], "Automação")
        self.assertEqual(out["kind"], "different")
        self.assertEqual(calls, [ROWS[0]["caption"]])


class ReadOnlyTest(unittest.TestCase):
    def test_reader_is_read_only_and_never_creates_files(self):
        with tempfile.TemporaryDirectory() as t:
            missing = Path(t) / "nao_existe.sqlite"
            with self.assertRaises(FileNotFoundError):
                read_legacy_rows_readonly(missing)
            self.assertFalse(missing.exists())
            db = Path(t) / "legacy.sqlite"
            c = sqlite3.connect(str(db))
            c.execute("CREATE TABLE instagram_items (id TEXT PRIMARY KEY, caption TEXT)")
            c.executemany("INSERT INTO instagram_items VALUES (?, ?)", [(f"SYNTHro{i:02d}", "tutorial") for i in range(5)])
            c.commit(); c.close()
            before = hashlib.sha256(db.read_bytes()).hexdigest()
            page1 = read_legacy_rows_readonly(db, limit=3)
            page2 = read_legacy_rows_readonly(db, limit=3, offset_id=page1[-1]["id"])
            self.assertEqual([r["id"] for r in page1 + page2], [f"SYNTHro{i:02d}" for i in range(5)])
            run_shadow(page1 + page2)
            self.assertEqual(hashlib.sha256(db.read_bytes()).hexdigest(), before)
            ro = sqlite3.connect(f"{db.as_uri()}?mode=ro", uri=True)
            with self.assertRaises(sqlite3.OperationalError):
                ro.execute("UPDATE instagram_items SET caption = 'x'")
            ro.close()


@unittest.skipUnless(os.environ.get("PROJETO_MVP_DIR"), "defina PROJETO_MVP_DIR para usar a função legada real")
class RealLegacyFunctionShadowTest(unittest.TestCase):
    def test_shadow_with_real_suggest_editorial_category(self):
        import sys
        sys.path.insert(0, str(Path(os.environ["PROJETO_MVP_DIR"]).resolve()))
        from core.curation import suggest_editorial_category
        rep = run_shadow(ROWS, legacy_suggest=suggest_editorial_category)
        by = {i.get("item_id"): i for i in rep["items"]}
        self.assertEqual(by["SYNTHsh02"]["legacy"]["label"], "Automação")   # o legado real reproduz o defeito
        self.assertEqual(by["SYNTHsh02"]["kind"], "only_legacy")
        self.assertEqual(rep["writes_performed"], 0)


if __name__ == "__main__":
    unittest.main()

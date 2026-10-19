"""Relatório de compatibilidade com o Projeto-MVP atual (opt-in: precisa de PROJETO_MVP_DIR)."""
import importlib.util
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from tests import _helpers

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("compat_report", ROOT / "tools" / "compat_report.py")
compat = importlib.util.module_from_spec(spec)
spec.loader.exec_module(compat)


@unittest.skipUnless(os.environ.get("PROJETO_MVP_DIR"), "defina PROJETO_MVP_DIR para comparar com o projeto atual")
class CompatReportTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import json
        cls.base = json.loads((ROOT / "handoff" / "baseline_contratos_c6845a4.json").read_text(encoding="utf-8"))

    def test_published_clone_matches_baseline(self):
        rep = compat.compare(self.base, compat.collect(_helpers.projeto_dir()))
        self.assertTrue(rep["compativel_com_baseline"], rep["acoes"])

    def test_detects_signature_column_and_value_drift(self):
        with tempfile.TemporaryDirectory() as t:
            mut = Path(t) / "mvp_mutado"
            shutil.copytree(_helpers.projeto_dir(), mut)
            cur = mut / "core" / "curation.py"
            text = cur.read_text(encoding="utf-8")
            text = text.replace("def suggest_editorial_category(\n    caption", "def suggest_editorial_category(\n    texto", 1)
            text = text.replace('source: str = "human"', 'source: str = "assistente"', 1)
            cur.write_text(text, encoding="utf-8")
            imp = mut / "core" / "instagram_importer.py"
            imp.write_text(imp.read_text(encoding="utf-8").replace("                fbid TEXT,", "                fbid TEXT,\n                coluna_nova_x TEXT,", 1), encoding="utf-8")
            rep = compat.compare(self.base, compat.collect(mut))
        self.assertFalse(rep["compativel_com_baseline"])
        self.assertEqual(rep["modules"]["core/curation.py"]["status"], "alterado")
        self.assertIn("def suggest_editorial_category", rep["modules"]["core/curation.py"]["mudancas"])
        self.assertEqual(rep["columns"]["novas"], ["coluna_nova_x"])
        self.assertEqual(rep["values"]["editorial_source_default_function"]["status"], "alterado")
        self.assertTrue(any("HUMAN_EDITORIAL_SOURCES" in a for a in rep["acoes"]))

    def test_refuses_to_write_report_inside_project(self):
        with self.assertRaises(SystemExit):
            compat.main(["--projeto", str(_helpers.projeto_dir()), "--out", str(_helpers.projeto_dir() / "relatorio.json")])


if __name__ == "__main__":
    unittest.main()

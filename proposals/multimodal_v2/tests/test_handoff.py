"""Missão Suprema 02, T14: pacote de integração verificável."""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests import _helpers  # noqa: F401
from ii_mm.contract import validate_document
from ii_mm.n8n_contract import validate_mission, validate_result

ROOT = Path(__file__).resolve().parents[1]
CONTRACTS = ROOT / "handoff" / "contratos"


def load(name):
    return json.loads((CONTRACTS / name).read_text(encoding="utf-8"))


class HandoffPackageTest(unittest.TestCase):
    def test_contract_examples_validate(self):
        self.assertEqual(validate_document(load("ii.reference_analysis.v2.exemplo.json")), [])
        self.assertEqual(validate_mission(load("ii.mission.v1.exemplo.json")), [])
        self.assertEqual(validate_result(load("ii.mission_result.v1.exemplo.json")), [])
        self.assertEqual(load("ii.shadow_report.v1.exemplo.json")["writes_performed"], 0)
        self.assertIn("findings", load("ii.temporal_quality.v1.exemplo.json"))

    def test_package_is_up_to_date_and_clean(self):
        spec = importlib.util.spec_from_file_location("build_handoff", ROOT / "tools" / "build_handoff.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        self.assertEqual(mod.main(check=True), 0, "rode: python3 tools/build_handoff.py")
        man = json.loads((ROOT / "handoff" / "MANIFESTO_PACOTE.json").read_text(encoding="utf-8"))
        paths = [f["path"] for f in man["files"]]
        self.assertFalse([p for p in paths if p.lower().endswith(mod.FORBIDDEN_SUFFIXES)])
        self.assertIn("multimodal_v2/ii_mm/contract.py", paths)
        self.assertIn("classification/text_matcher.py", paths)
        self.assertNotIn("Rian", json.dumps(man))

    def test_manifest_hash_is_stable_across_line_endings(self):
        spec = importlib.util.spec_from_file_location("build_handoff", ROOT / "tools" / "build_handoff.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        lf = b"linha 1\nlinha 2\n"
        self.assertEqual(mod.content_hash(lf), mod.content_hash(lf.replace(b"\n", b"\r\n")))
        self.assertNotEqual(mod.content_hash(lf), mod.content_hash(b"linha 1\nlinha 3\n"))

    def test_usage_example_runs_in_demo_mode_and_refuses_vault(self):
        with tempfile.TemporaryDirectory() as t:
            out = Path(t) / "saida"
            r = subprocess.run([sys.executable, str(ROOT / "handoff" / "exemplo_uso.py"), "--demo", "--out", str(out)],
                               capture_output=True, text=True, encoding="utf-8", timeout=60,
                               env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1"))
            self.assertEqual(r.returncode, 0, r.stderr[-500:])
            self.assertTrue((out / "relatorio_sombra.md").is_file())
            vault = Path(t) / "Cofre"; (vault / ".obsidian").mkdir(parents=True)
            r = subprocess.run([sys.executable, str(ROOT / "handoff" / "exemplo_uso.py"), "--demo", "--out", str(vault / "x")],
                               capture_output=True, text=True, encoding="utf-8", timeout=60,
                               env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1"))
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("cofre", r.stderr)


if __name__ == "__main__":
    unittest.main()

"""Missão Suprema 03: documentos do pacote coerentes com o código (inventário, categorias, scripts PowerShell)."""
import importlib.util
import re
import unittest
from pathlib import Path

from tests import _helpers  # noqa: F401
from ii_mm.evidence_rules import CATEGORIES

ROOT = Path(__file__).resolve().parents[1]


def _load_tool(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "tools" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class InventoryDocTest(unittest.TestCase):
    def test_generated_table_is_in_the_document(self):
        table = _load_tool("inventory").markdown(_load_tool("inventory").collect())
        doc = (ROOT / "INVENTARIO_COMPONENTES.md").read_text(encoding="utf-8")
        self.assertTrue(table in doc, "seção 1 do inventário desatualizada: rode python -X utf8 tools/build_handoff.py")

    def test_every_module_is_described_beyond_the_table(self):
        doc = (ROOT / "INVENTARIO_COMPONENTES.md").read_text(encoding="utf-8")
        described = doc.split("## 2.", 1)[1]
        for f in (ROOT / "ii_mm").rglob("*.py"):
            name = f.stem if f.parent.name == "ii_mm" else f"db.{f.stem}"
            if f.stem == "__init__" or f.stem.startswith("_"):
                continue
            self.assertRegex(described, rf"`{re.escape(name)}`|`{re.escape(f.stem)}`", name)


class PackageDocsTest(unittest.TestCase):
    def test_all_documents_in_the_package_exist(self):
        build = _load_tool("build_handoff")
        missing = [rel for rel in build.PACKAGE if not (ROOT / rel).exists()]
        self.assertEqual(missing, [])

    def test_evaluation_guide_lists_exactly_the_code_categories(self):
        doc = (ROOT / "AVALIACAO_HUMANA.md").read_text(encoding="utf-8")
        listed = re.findall(r"^\| `([a-z_]+)` \| ", doc, re.M)
        self.assertEqual(listed, list(CATEGORIES))


class PowerShellAsciiTest(unittest.TestCase):
    """O Windows PowerShell 5.1 lê .ps1 sem BOM como ANSI: em UTF-8, o travessão (E2 80 94) vira a aspa
    tipográfica 0x94, que o PowerShell trata como delimitador de string. Os scripts precisam ser ASCII."""

    def test_scripts_are_pure_ascii(self):
        scripts = sorted((ROOT / "handoff" / "windows").glob("*.ps1"))
        self.assertTrue(scripts)
        for s in scripts:
            data = s.read_bytes()
            bad = [i for i, b in enumerate(data) if b > 127]
            self.assertEqual(bad[:5], [], f"{s.name}: bytes não ASCII")


if __name__ == "__main__":
    unittest.main()

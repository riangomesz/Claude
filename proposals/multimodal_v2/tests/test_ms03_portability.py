"""Missão Suprema 03: portabilidade para Windows (o que dá para verificar fora do Windows)."""
import ast
import os
import re
import subprocess
import sys
import unittest
from pathlib import Path

from tests import _helpers  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]
PROPOSALS = ROOT.parent


class W2BenchmarkWithoutResourceModuleTest(unittest.TestCase):
    def test_benchmark_imports_where_resource_module_does_not_exist(self):
        """No Windows não existe o módulo `resource`; o benchmark (e seu smoke test) não podem depender dele."""
        code = ("import sys; sys.modules['resource'] = None; sys.path.insert(0, r'%s'); "
                "import importlib.util as u; s = u.spec_from_file_location('b', r'%s'); m = u.module_from_spec(s); "
                "s.loader.exec_module(m); print(m.environment()['python'])") % (ROOT, ROOT / "tools" / "benchmark.py")
        out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, encoding="utf-8", timeout=60,
                             env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
        self.assertEqual(out.returncode, 0, out.stderr[-400:])


class StaticPortabilityTest(unittest.TestCase):
    """Verificações estáticas sobre todo o pacote (núcleo, ferramentas e testes)."""

    def files(self):
        return [p for p in PROPOSALS.rglob("*.py") if "__pycache__" not in p.parts]

    def test_syntax_is_python_310_compatible(self):
        for p in self.files():
            ast.parse(p.read_text(encoding="utf-8"), feature_version=(3, 10))

    def test_no_posix_only_modules_or_paths(self):
        pattern = re.compile(r"^\s*import (resource|fcntl|termios|pwd|grp)\b|[\"']/(usr|proc|dev|tmp)/|os\.getuid|os\.fork\(")
        bad = [f"{p.relative_to(PROPOSALS)}:{i}" for p in self.files() if p.name != "test_ms03_portability.py"
               for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
               if pattern.search(line) and "try:" not in line and "optional" not in line]
        self.assertEqual(bad, [])

    def test_text_io_always_declares_encoding(self):
        """read_text/write_text/open em modo texto e subprocess(text=True) sem encoding usam cp1252 no Windows."""
        bad = []
        for p in self.files():
            tree = ast.parse(p.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                name = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
                kws = {k.arg for k in node.keywords}
                if name in ("read_text", "write_text") and "encoding" not in kws:
                    bad.append(f"{p.relative_to(PROPOSALS)}:{node.lineno}")
                if name == "run" and "text" in kws and "encoding" not in kws:
                    bad.append(f"{p.relative_to(PROPOSALS)}:{node.lineno}")
        self.assertEqual(bad, [])

    def test_repository_file_names_are_valid_on_windows(self):
        reserved = {"CON", "PRN", "AUX", "NUL"} | {f"COM{i}" for i in range(1, 10)} | {f"LPT{i}" for i in range(1, 10)}
        names = [p for p in PROPOSALS.rglob("*") if "__pycache__" not in p.parts]
        lowered = {}
        for p in names:
            rel = p.relative_to(PROPOSALS).as_posix()
            self.assertFalse(re.search(r'[<>:"\\|?*]', p.name), rel)
            self.assertNotIn(p.name.split(".")[0].upper(), reserved, rel)
            self.assertFalse(p.name.endswith((" ", ".")), rel)
            self.assertNotIn(rel.lower(), lowered, f"colisão de caixa: {rel} × {lowered.get(rel.lower())}")
            lowered[rel.lower()] = rel
        self.assertLess(max(len(p.relative_to(PROPOSALS).as_posix()) for p in names), 160, "caminho relativo longo para MAX_PATH")


if __name__ == "__main__":
    unittest.main()


class W6MissionUriWindowsTest(unittest.TestCase):
    """URIs de artefato que viram outro arquivo (ou dispositivo) quando resolvidas no NTFS."""

    def test_windows_specific_uri_tricks_are_rejected(self):
        from ii_mm.n8n_contract import _bad_uri
        for uri in ("missoes/x/transcricao.json:fluxo_oculto", "missoes/CON/x.json", "missoes/x/nul.json", "missoes/x/aux",
                    "missoes/x./arquivo.json", "missoes/x /arquivo.json", "missoes/x/arquivo.json.", "COM1.txt"):
            self.assertIsNotNone(_bad_uri(uri), uri)
        for ok in ("missoes/SYNTH01/transcricao.json", "missoes\\SYNTH01\\frames\\p01.jpg", "a/b.c/d-e_f.json"):
            self.assertIsNone(_bad_uri(ok), ok)

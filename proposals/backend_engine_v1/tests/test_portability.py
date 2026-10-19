"""Portabilidade para Windows do código do backend (mesmas regras estáticas da RC1, aplicadas a este pacote).

Achado real: a primeira versão de tools/bench_backend.py lia /proc/meminfo sem encoding e com caminho POSIX
literal; a varredura da RC1 (que cobre toda a árvore proposals/) acusou. Este teste mantém a regra aqui também."""
import ast
import re
import unittest

from tests._util import ROOT

POSIX_ONLY = {"resource", "fcntl", "pwd", "grp", "termios", "pty", "tty", "posix"}
WINDOWS_RESERVED = {"CON", "PRN", "AUX", "NUL"} | {f"COM{i}" for i in range(1, 10)} | {f"LPT{i}" for i in range(1, 10)}


def py_files():
    return [p for p in ROOT.rglob("*.py") if "__pycache__" not in p.parts]


class PortabilityTest(unittest.TestCase):
    def test_syntax_is_python_310_compatible(self):
        for p in py_files():
            ast.parse(p.read_text(encoding="utf-8"), filename=str(p), feature_version=(3, 10))

    def test_no_posix_only_modules_or_literal_paths(self):
        bad = []
        for p in py_files():
            src = p.read_text(encoding="utf-8")
            tree = ast.parse(src)
            for node in ast.walk(tree):
                names = [a.name.split(".")[0] for a in node.names] if isinstance(node, ast.Import) else \
                    [(node.module or "").split(".")[0]] if isinstance(node, ast.ImportFrom) else []
                bad += [f"{p.name}:{node.lineno}:{n}" for n in names if n in POSIX_ONLY]
            for i, line in enumerate(src.splitlines(), 1):
                if re.search(r"[\"'](/proc/|/dev/|/etc/|/tmp/)", line) and "test_" not in p.name:
                    bad.append(f"{p.name}:{i}")
        self.assertEqual(bad, [])

    def test_text_io_declares_encoding(self):
        bad = []
        for p in py_files():
            for node in ast.walk(ast.parse(p.read_text(encoding="utf-8"))):
                if not isinstance(node, ast.Call):
                    continue
                fn = node.func
                name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "")
                kws = {k.arg for k in node.keywords}
                if name in ("read_text", "write_text") and "encoding" not in kws:
                    bad.append(f"{p.name}:{node.lineno}")
                if name == "open" and isinstance(fn, ast.Name):
                    mode = node.args[1].value if len(node.args) > 1 and isinstance(node.args[1], ast.Constant) else \
                        next((k.value.value for k in node.keywords if k.arg == "mode" and isinstance(k.value, ast.Constant)), "r")
                    if "b" not in mode and "encoding" not in kws:
                        bad.append(f"{p.name}:{node.lineno}")
        self.assertEqual(bad, [])

    def test_file_names_are_valid_on_windows(self):
        seen = {}
        for p in ROOT.rglob("*"):
            if "__pycache__" in p.parts:
                continue
            rel = p.relative_to(ROOT).as_posix()
            for part in rel.split("/"):
                self.assertFalse(re.search(r'[<>:"|?*]', part), rel)
                self.assertNotIn(part.split(".")[0].upper(), WINDOWS_RESERVED, rel)
                self.assertFalse(part.endswith((" ", ".")), rel)
            self.assertNotIn(rel.lower(), seen, f"colisão por caixa: {rel} × {seen.get(rel.lower())}")
            seen[rel.lower()] = rel
            self.assertLess(len("proposals/backend_engine_v1/" + rel), 160, rel)


if __name__ == "__main__":
    unittest.main()

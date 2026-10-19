"""Inventário reproduzível dos componentes do ii_mm (Missão Suprema 03, Etapa 01).

Uso:  python -X utf8 tools/inventory.py            (tabela Markdown na saída padrão)
      python -X utf8 tools/inventory.py --json     (mesmos dados em JSON)

Tudo é extraído por AST, sem importar os módulos: linhas, dependências internas, módulos da stdlib,
API pública e quais arquivos de teste exercitam cada módulo.
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
TEST_FILES = ["test_multimodal_classifier.py", "test_regression_current.py", "test_verify_package.py"]


def _imports(tree: ast.Module, modules: set):
    internal, stdlib = set(), set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.level or (node.module or "").startswith("ii_mm"):
                base = (node.module or "").replace("ii_mm.", "")
                # "from . import X": X é submódulo ou um nome definido em ii_mm/__init__.py
                names = [a.name if a.name in modules else "__init__" for a in node.names] if not node.module else [base]
                internal.update(n for n in names if n)
            elif node.module:
                stdlib.add(node.module.split(".")[0])
        elif isinstance(node, ast.Import):
            stdlib.update(a.name.split(".")[0] for a in node.names if not a.name.startswith("ii_mm"))
    stdlib.discard("__future__")
    return sorted(internal), sorted(stdlib)


def collect(root: Path = HERE) -> list:
    tests = sorted((root / "tests").glob("test_*.py")) + [root / t for t in TEST_FILES if (root / t).is_file()]
    texts = {t.name: t.read_text(encoding="utf-8") for t in tests}
    files = sorted((root / "ii_mm").rglob("*.py"))
    modules = {f.stem for f in files}
    rows = []
    for f in files:
        src = f.read_text(encoding="utf-8")
        tree = ast.parse(src)
        mod = ".".join(f.relative_to(root).with_suffix("").parts)
        short = mod.split(".")[-1]
        doc = (ast.get_docstring(tree) or "").splitlines()
        internal, stdlib = _imports(tree, modules)
        pat = re.compile(rf"(from|import) {re.escape(mod)}\b|from ii_mm(\.db)? import [^\n]*\b{re.escape(short)}\b")
        rows.append({
            "module": mod,
            "file": f.relative_to(root).as_posix(),
            "lines": src.count("\n"),
            "summary": doc[0] if doc else "",
            "internal_deps": internal,
            "stdlib": stdlib,
            "public": [n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.ClassDef)) and not n.name.startswith("_")],
            "tests": sorted(name for name, t in texts.items() if pat.search(t)),
        })
    return rows


def markdown(rows: list) -> str:
    out = ["| Módulo | Linhas | Depende de (interno) | stdlib | API pública | Testes que o exercitam |", "|---|---|---|---|---|---|"]
    for r in rows:
        out.append("| `{}` | {} | {} | {} | {} | {} |".format(
            r["module"], r["lines"], ", ".join(r["internal_deps"]) or "—", ", ".join(r["stdlib"]) or "—",
            ", ".join(f"`{p}`" for p in r["public"]) or "—", len(r["tests"]) or "indireto"))
    return "\n".join(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    rows = collect()
    sys.stdout.write((json.dumps(rows, ensure_ascii=False, indent=2) if a.json else markdown(rows)) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

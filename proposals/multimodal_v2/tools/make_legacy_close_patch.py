"""Gera o patch demonstrativo que fecha as conexões SQLite do legado (achado L1), SEM alterar o clone.

Uso: python3 tools/make_legacy_close_patch.py <clone_projeto_mvp> <pasta_destino_da_copia> [--diff saida.diff]

Transformação (uma por ocorrência, só em core/*.py):
    with sqlite3.connect(X) as conn:      ->      with closing(sqlite3.connect(X)) as conn, conn:
A semântica de transação continua a mesma (o `conn` interno ainda faz commit/rollback); a diferença é que
`closing` fecha a conexão ao sair do bloco, em vez de esperar o coletor de ciclos do Python.
"""
from __future__ import annotations

import difflib
import re
import shutil
import sys
from pathlib import Path

PATTERN = re.compile(r"^(?P<ind>\s*)with sqlite3\.connect\((?P<arg>.*)\) as (?P<name>\w+):(?P<tail>\s*)$")


def transform(text: str) -> tuple:
    out, n = [], 0
    for line in text.splitlines(keepends=True):
        body = line.rstrip("\r\n")
        m = PATTERN.match(body)
        if m:
            nl = line[len(body):]
            out.append(f"{m['ind']}with closing(sqlite3.connect({m['arg']})) as {m['name']}, {m['name']}:{nl}")
            n += 1
        else:
            out.append(line)
    new = "".join(out)
    if n and not re.search(r"^from contextlib import .*\bclosing\b", new, re.M):
        new = re.sub(r"^import sqlite3\s*$", "import sqlite3\nfrom contextlib import closing", new, count=1, flags=re.M)
    return new, n


def build(clone: Path, dest: Path) -> tuple:
    clone, dest = Path(clone).resolve(), Path(dest).resolve()
    if dest == clone or clone in dest.parents:
        raise SystemExit("o destino não pode ser o clone nem ficar dentro dele")
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(clone, dest, ignore=shutil.ignore_patterns(".git", "*.bin", "storage", "__pycache__"))
    diffs, total = [], 0
    for src in sorted((clone / "core").glob("*.py")):
        old = src.read_text(encoding="utf-8")
        new, n = transform(old)
        if n:
            (dest / "core" / src.name).write_text(new, encoding="utf-8")
            total += n
            diffs.append("".join(difflib.unified_diff(old.splitlines(keepends=True), new.splitlines(keepends=True),
                                                      f"a/core/{src.name}", f"b/core/{src.name}")))
    return total, "".join(diffs)


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(2)
    total, diff = build(Path(sys.argv[1]), Path(sys.argv[2]))
    if "--diff" in sys.argv:
        Path(sys.argv[sys.argv.index("--diff") + 1]).write_text(diff, encoding="utf-8")
    print(f"{total} ocorrências transformadas")

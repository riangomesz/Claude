"""Cobertura de linhas só com a stdlib (`trace`), para ambientes sem o pacote `coverage`.

Uso (a partir de proposals/multimodal_v2):
    python3 tools/stdlib_coverage.py            # roda run_tests.py e mede os módulos do projeto
Conta como "executável" o que `trace` considera executável; docstrings e linhas de
continuação podem divergir levemente do coverage.py. Serve como indicador, não como métrica oficial.
"""
from __future__ import annotations

import os
import sys
import trace
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]


def measure(test_names, modules):
    sys.path[:0] = [str(HERE), str(HERE.parent / "classification")]
    tr = trace.Trace(count=1, trace=0, ignoredirs=[sys.prefix, sys.exec_prefix])
    result_box = {}

    def run():
        loader = unittest.defaultTestLoader
        suite = loader.loadTestsFromNames(test_names)
        with open(os.devnull, "w") as devnull:
            result_box["r"] = unittest.TextTestRunner(verbosity=0, stream=devnull).run(suite)

    tr.runfunc(run)
    counts = tr.results().counts
    rows = []
    for mod in modules:
        path = str(Path(mod).resolve())
        executable = {ln for ln in trace._find_executable_linenos(path) if isinstance(ln, int) and ln > 0}
        hit = {ln for (fn, ln), _ in counts.items() if fn and str(Path(fn).resolve()) == path}
        covered = executable & hit
        pct = 100.0 * len(covered) / len(executable) if executable else 100.0
        rows.append((mod, len(covered), len(executable), pct, sorted(executable - hit)))
    return result_box["r"], rows


if __name__ == "__main__":
    os.chdir(HERE)
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(HERE))
    from run_tests import TEST_MODULES, SOURCE_MODULES  # noqa: E402
    r, rows = measure(TEST_MODULES, SOURCE_MODULES)
    print(f"testes: {r.testsRun} | falhas: {len(r.failures)} | erros: {len(r.errors)} | pulados: {len(r.skipped)}")
    for mod, c, e, pct, missing in rows:
        print(f"{mod:48} {c:4}/{e:<4} {pct:5.1f}%  faltando: {missing[:12]}{' …' if len(missing) > 12 else ''}")

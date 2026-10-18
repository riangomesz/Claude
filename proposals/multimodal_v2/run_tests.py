"""Executor único da suíte isolada (stdlib). Uso: python3 run_tests.py [-v]
Variável opcional: PROJETO_MVP_DIR=<clone> ativa a regressão contra o código atual do Projeto-MVP."""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.dont_write_bytecode = True
sys.path[:0] = [str(HERE), str(HERE.parent / "classification")]

LEGACY_TEST_MODULES = [
    "test_text_matcher",
    "test_multimodal_classifier",
    "test_regression_current",
    "test_verify_package",
]
TEST_MODULES = LEGACY_TEST_MODULES + sorted(f"tests.{p.stem}" for p in (HERE / "tests").glob("test_*.py"))
SOURCE_MODULES = [
    "../classification/text_matcher.py",
    "multimodal_classifier.py",
    "verify_package.py",
] + sorted(f"ii_mm/{p.name}" for p in (HERE / "ii_mm").glob("*.py") if p.name != "__init__.py")

if __name__ == "__main__":
    os.chdir(HERE)
    verbosity = 2 if "-v" in sys.argv else 1
    suite = unittest.defaultTestLoader.loadTestsFromNames(TEST_MODULES)
    result = unittest.TextTestRunner(verbosity=verbosity).run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)

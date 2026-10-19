"""Executor da suíte do motor criativo (stdlib). Uso: python -X utf8 run_tests.py [-v]"""
import os
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(HERE))

if __name__ == "__main__":
    os.chdir(HERE)
    suite = unittest.defaultTestLoader.loadTestsFromNames(sorted(f"tests.{p.stem}" for p in (HERE / "tests").glob("test_*.py")))
    result = unittest.TextTestRunner(verbosity=2 if "-v" in sys.argv else 1).run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)

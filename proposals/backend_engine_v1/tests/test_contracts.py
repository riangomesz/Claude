"""Os exemplos publicados em contratos/ são exatamente os que o código gera (e continuam válidos)."""
import importlib.util
import json
import unittest
from pathlib import Path

from tests._util import ROOT
from ii_be.gateway import validate_request
from ii_be.ingest import validate_record


def _tool():
    spec = importlib.util.spec_from_file_location("be_contracts", ROOT / "tools" / "contracts.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class ContractsTest(unittest.TestCase):
    def test_published_examples_match_the_code(self):
        self.assertEqual(_tool().main(["--check"]), 0, "rode: python -X utf8 tools/contracts.py")

    def test_examples_validate(self):
        d = ROOT / "contratos"
        load = lambda n: json.loads((d / n).read_text(encoding="utf-8"))  # noqa: E731
        self.assertEqual(validate_record(load("ii.be.ingest.v1.exemplo.json")), [])
        self.assertEqual(validate_record(load("ii.be.ingest.v1.meta_export.exemplo.json")), [])
        self.assertEqual(validate_request(load("ii.be.analysis_request.v1.exemplo.json")), [])
        self.assertTrue(load("ii.be.api.v1.ingest_reference.response.json")["ok"])
        self.assertEqual(load("ii.be.api.v1.erro.exemplo.json")["error"]["code"], "VALIDATION_ERROR")
        self.assertFalse(load("ii.be.analysis_result.v1.exemplo.json")["provenance"]["merged_into_evidence"])


class PackageHygieneTest(unittest.TestCase):
    def test_no_media_databases_or_secrets_in_the_package(self):
        forbidden = (".sqlite", ".sqlite3", ".db", ".mp4", ".mov", ".jpg", ".jpeg", ".png", ".webp", ".wav", ".mp3", ".env", ".pem",
                     ".key", "-wal", "-shm")
        bad = [p.relative_to(ROOT).as_posix() for p in ROOT.rglob("*") if p.is_file() and "__pycache__" not in p.parts
               and p.name.lower().endswith(forbidden)]
        self.assertEqual(bad, [])


if __name__ == "__main__":
    unittest.main()

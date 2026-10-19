"""Missão Suprema 03, Etapa 04: JSON Schemas publicados em handoff/schemas (gerados por tools/schemas.py).

O schema é estrutural (para consumidores sem Python); a regra completa continua em `contract.validate_document`.
O teste garante que os dois não se contradizem: o que o código aceita, o schema aceita.
"""
import copy
import importlib.util
import json
import unittest
from pathlib import Path

from tests import _helpers  # noqa: F401
from ii_mm.contract import validate_document
from ii_mm.synthetic import make_reference

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("ii_schemas", ROOT / "tools" / "schemas.py")
S = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(S)


def schema(name):
    return json.loads((ROOT / "handoff" / "schemas" / f"{name}.schema.json").read_text(encoding="utf-8"))


def example(name):
    return json.loads((ROOT / "handoff" / "contratos" / f"{name}.exemplo.json").read_text(encoding="utf-8"))


class PublishedSchemasTest(unittest.TestCase):
    NAMES = ("ii.reference_analysis.v2", "ii.visual_observation.v1", "ii.mission.v1", "ii.mission_result.v1")

    def test_files_on_disk_are_the_generated_ones(self):
        self.assertEqual({f"{n}.schema.json" for n in self.NAMES}, set(S.schemas()))
        for n in self.NAMES:
            self.assertEqual(schema(n), S.schemas()[f"{n}.schema.json"], n)

    def test_every_published_example_validates(self):
        for n in self.NAMES:
            self.assertEqual(S.validate(example(n), schema(n)), [], n)

    def test_code_accepted_documents_are_schema_valid(self):
        sch = schema("ii.reference_analysis.v2")
        for i in range(40):
            doc = make_reference(i)
            self.assertEqual(validate_document(doc), [])
            self.assertEqual(S.validate(doc, sch), [], i)

    def test_mutations_are_rejected(self):
        sch = schema("ii.reference_analysis.v2")
        base = example("ii.reference_analysis.v2")
        cases = []
        m = copy.deepcopy(base); del m["reference"]; cases.append(("sem reference", m))
        m = copy.deepcopy(base); m["schema_version"] = "ii.reference_analysis.v1"; cases.append(("versão", m))
        m = copy.deepcopy(base); m["evidence"][0]["status"] = "confirmado"; cases.append(("status inventado", m))
        m = copy.deepcopy(base); m["evidence"] = {"nao": "lista"}; cases.append(("tipo", m))
        m = copy.deepcopy(base); m["video"]["duration_s"] = "trinta"; cases.append(("duração texto", m))
        for label, doc in cases:
            self.assertTrue(S.validate(doc, sch), label)
        res = example("ii.mission_result.v1")
        res["state"] = "aprovado_automaticamente"
        self.assertTrue(S.validate(res, schema("ii.mission_result.v1")))
        obs = example("ii.visual_observation.v1")
        del obs["observations"][0]["tag"]
        self.assertTrue(S.validate(obs, schema("ii.visual_observation.v1")))


if __name__ == "__main__":
    unittest.main()

"""Regressão da classificação ATUAL do Projeto-MVP (curation.py), em duas camadas.

1. Se PROJETO_MVP_DIR apontar para um clone, o código atual é reexecutado e comparado ao golden
   (detecta mudança de comportamento antes de qualquer integração). Sem a variável, é pulado.
2. Sempre: no modo sombra, o novo matcher não pode reproduzir os defeitos conhecidos do golden.
"""
import json
import os
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from multimodal_classifier import classify  # noqa: E402

GOLDEN = json.loads((HERE / "regression_golden.json").read_text(encoding="utf-8"))["cases"]


class CurrentBehaviourPinned(unittest.TestCase):
    @unittest.skipUnless(os.environ.get("PROJETO_MVP_DIR"), "defina PROJETO_MVP_DIR para fixar o comportamento atual")
    def test_current_code_matches_golden(self):
        sys.dont_write_bytecode = True
        sys.path.insert(0, str(Path(os.environ["PROJETO_MVP_DIR"]).resolve()))
        from core.curation import evaluate_item_curation, suggest_editorial_category  # noqa: E402
        for c in GOLDEN:
            with self.subTest(caption=c["caption"]):
                self.assertEqual(list(evaluate_item_curation(c["caption"], c["hashtags"], "", "")), c["curation"])
                sug = suggest_editorial_category(c["caption"], c["hashtags"], "", "")
                self.assertEqual((sug or {}).get("suggested_category"), c["suggested_category"])


class ShadowModeDoesNotRepeatKnownDefects(unittest.TestCase):
    def test_known_defect_inputs_do_not_trigger_spurious_categories(self):
        spurious = {"robotics demo": "automacao_ia", "both teams won the game": "automacao_ia"}
        for c in GOLDEN:
            if c["caption"] in spurious:
                doc = classify({"video_id": "S", "duration_s": 10, "caption": c["caption"]})
                names = {x["category"] for x in doc["categories"]}
                self.assertNotIn(spurious[c["caption"]], names, c["caption"])

    def test_new_classifier_never_marks_text_only_input_as_verified(self):
        for c in GOLDEN:
            doc = classify({"video_id": "S", "duration_s": 10, "caption": c["caption"], "hashtags": c["hashtags"]})
            for cat in doc["categories"]:
                self.assertNotEqual(cat["support"], "verified_visual", c["caption"])

    def test_golden_covers_known_defects(self):
        self.assertGreaterEqual(sum(1 for c in GOLDEN if c["known_defect"]), 5)


if __name__ == "__main__":
    unittest.main()

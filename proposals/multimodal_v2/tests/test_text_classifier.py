import json
import random
import unittest
from pathlib import Path

from tests import _helpers  # noqa: F401
from ii_mm.text_classifier import RULES, TextClassifier, compare_with_legacy, detect_language
from ii_mm._matcher import normalize

GOLDEN = json.loads((Path(__file__).resolve().parents[1] / "regression_golden.json").read_text(encoding="utf-8"))["cases"]
CLF = TextClassifier()


def strong(text):
    return CLF.classify(text).categories()


class LegacyRegressionTest(unittest.TestCase):
    def test_every_non_defect_golden_case_agrees_with_legacy(self):
        rows = compare_with_legacy(GOLDEN, CLF)
        bad = [r for r in rows if not r["known_defect"] and not r["agree"]]
        self.assertEqual(bad, [], "regressão em caso sem defeito conhecido")

    def test_known_defects_do_not_reappear(self):
        rows = {r["caption"]: r for r in compare_with_legacy(GOLDEN, CLF)}
        self.assertNotIn("automacao", rows["robotics demo"]["v2_strong"])
        self.assertNotIn("automacao", rows["both teams won the game"]["v2_strong"])
        self.assertEqual(rows["copy of my receipt"]["v2_strong"], [])
        self.assertEqual(rows["pizza do dev da esquina"]["v2_strong"], [])
        # Rule-order defect: motion vence por evidência, não pela posição da regra
        self.assertEqual(rows["motion design e keyframes, uma ia ajuda"]["v2_strong"], ["motion_design"])

    def test_golden_input_set_unchanged(self):
        self.assertEqual(len(GOLDEN), 17)


class AdversarialTest(unittest.TestCase):
    def test_portuguese_ia_and_ai_are_not_artificial_intelligence(self):
        for t in ("eu ia ao mercado ontem", "ai que saudade", "ela ia viajar", "ai ai ai"):
            r = CLF.classify(t)
            self.assertEqual(r.categories(include_weak=True), [], t)
            self.assertEqual(r.ai_topic_terms, [], t)
        self.assertEqual(CLF.classify("IA generativa no vídeo").ai_topic_terms, ["ia generativa"])
        self.assertIn("inteligencia artificial", CLF.classify("Inteligência Artificial!").ai_topic_terms)

    def test_exclusion_contexts(self):
        cases = {"corte de cabelo masculino": "edicao_audiovisual", "slow motion do gol": "motion_design",
                 "stop motion com massinha": "motion_design", "clínica de estética": "referencia_estetica",
                 "agente de viagens barato": "automacao", "edição limitada do tênis": "edicao_audiovisual"}
        for text, cat in cases.items():
            self.assertNotIn(cat, CLF.classify(text).categories(include_weak=True), text)
        self.assertIn("edicao_audiovisual:corte", CLF.classify("corte de cabelo").excluded)

    def test_exclusion_only_suppresses_inside_the_phrase(self):
        r = CLF.classify("corte de cabelo e um jump cut no capcut")
        self.assertIn("edicao_audiovisual", r.categories())

    def test_weak_terms_alone_do_not_assign(self):
        for t in ("edit do jogo", "app novo", "olha aqui", "primeiro dia de aula", "camera nova", "free"):
            self.assertEqual(strong(t), [], t)
        r = CLF.classify("edit do jogo")
        self.assertEqual([(m.category, m.strength) for m in r.matches], [("edicao_audiovisual", "weak_only")])

    def test_weak_terms_reinforce_strong(self):
        r = CLF.classify("edição no capcut com corte seco")
        m = next(x for x in r.matches if x.category == "edicao_audiovisual")
        self.assertEqual(m.strength, "strong")
        self.assertEqual(m.terms, ["capcut", "corte", "edicao"])

    def test_hashtag_compounds(self):
        self.assertEqual(strong("#motiondesign"), ["motion_design"])
        self.assertEqual(strong("#passoapasso #linknabio"), ["tutorial", "marketing_vendas"])
        self.assertEqual(strong("#colorgrading"), ["edicao_audiovisual"])

    def test_longer_phrase_subsumes_shorter(self):
        m = next(x for x in CLF.classify("motion design").matches if x.category == "motion_design")
        self.assertEqual(m.terms, ["motion design"])

    def test_accents_punctuation_and_case(self):
        variants = ["AUTOMAÇÃO com N8N!!!", "automacao, com n8n.", "Automação—com—n8n", "(automação) [n8n]"]
        for v in variants:
            self.assertEqual(strong(v), ["automacao"], v)

    def test_substring_inside_words_never_matches(self):
        for t in ("robotics", "motionless", "leadsheet music", "promotional", "edition", "transitional government"):
            self.assertNotIn("automacao", strong(t), t)
        self.assertEqual(strong("motionless"), [])
        self.assertEqual(strong("promotional"), [])

    def test_order_independence_of_rules(self):
        items = list(RULES.items())
        random.Random(42).shuffle(items)
        shuffled = TextClassifier(dict(items))
        text = "tutorial de motion design com desconto, workflow no n8n e color grading cinematic"
        a, b = CLF.classify(text), shuffled.classify(text)
        self.assertEqual([(m.category, m.terms) for m in a.matches], [(m.category, m.terms) for m in b.matches])
        self.assertEqual(a.categories(), ["tutorial", "automacao", "motion_design", "edicao_audiovisual", "marketing_vendas", "cinematografia"])

    def test_multilabel_bilingual(self):
        self.assertEqual(strong("step by step video editing tutorial with a discount"), ["tutorial", "edicao_audiovisual", "marketing_vendas"])

    def test_unknown_category_rejected(self):
        with self.assertRaises(ValueError):
            TextClassifier({"inventada": {"strong": ["x"]}})

    def test_hits_have_positions_in_normalized_text(self):
        r = CLF.classify("Olha só essa ferramenta")
        h = r.matches[0].hits[0]
        self.assertEqual(normalize("Olha só essa ferramenta")[h.start:h.end], h.term)

    def test_language_detection(self):
        self.assertEqual(detect_language(normalize("olha isso aqui que eu fiz para voce")), "pt")
        self.assertEqual(detect_language(normalize("this is how you do it with the tool")), "en")
        self.assertEqual(detect_language(normalize("n8n webhook")), "undetermined")

    def test_empty_and_garbage(self):
        for t in ("", "   ", "!!!", "\x00\x01", "😀😀"):
            r = CLF.classify(t)
            self.assertEqual(r.matches, [])


if __name__ == "__main__":
    unittest.main()

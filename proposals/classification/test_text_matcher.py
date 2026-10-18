import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from text_matcher import RankedMatcher, has_any, normalize  # noqa: E402

RULES = {
    "Ferramentas de IA": ["chatgpt", "midjourney", "comfyui", "claude", "ia", "ai", "inteligencia artificial"],
    "Automação": ["n8n", "zapier", "automacao", "webhook", "workflow", "bot", "rpa"],
    "Marketing e Conteúdo": ["copywriting", "copy", "viral", "hook", "storytelling"],
    "Design e Motion": ["after effects", "motion design", "motion", "keyframes", "tipografia"],
}


class TextMatcherTest(unittest.TestCase):
    def setUp(self):
        self.m = RankedMatcher(RULES)

    def test_substring_false_positives_do_not_match(self):
        # Todos esses disparavam rótulo com `kw in texto`.
        for text in ["robotics demo", "both teams won the game", "copywriter freelancer",
                     "ciao amigos", "maintain the chain", "motionless scene"]:
            self.assertIsNone(self.m.best(text), text)

    def test_whole_word_still_matches(self):
        self.assertEqual(self.m.best("bot de atendimento")[0], "Automação")
        self.assertEqual(self.m.best("minha IA favorita")[0], "Ferramentas de IA")
        self.assertEqual(self.m.best("#ai #chatgpt")[0], "Ferramentas de IA")

    def test_accent_insensitive(self):
        self.assertEqual(self.m.best("Automação com n8n")[0], "Automação")
        self.assertEqual(self.m.best("INTELIGÊNCIA ARTIFICIAL")[0], "Ferramentas de IA")

    def test_ranks_by_evidence_not_rule_order(self):
        # Antes: "Ferramentas de IA" ganhava só por vir primeiro na lista.
        label, matched = self.m.best("motion design e keyframes no after effects, uma ia ajuda")
        self.assertEqual(label, "Design e Motion")
        self.assertGreaterEqual(len(matched), 3)

    def test_ties_follow_rule_order_and_are_deterministic(self):
        r1 = self.m.rank("ia e motion")
        r2 = self.m.rank("ia e motion")
        self.assertEqual(r1, r2)
        self.assertEqual([l for l, _ in r1], ["Ferramentas de IA", "Design e Motion"])

    def test_non_ascii_punctuation_does_not_glue_words(self):
        self.assertEqual(normalize("automação—com—n8n"), "automacao com n8n")
        self.assertEqual(normalize("“motion”…design🔥ok"), "motion design ok")
        self.assertEqual(self.m.best("Automação—n8n")[0], "Automação")
        self.assertEqual(normalize("veja make.com... e n8n. Fim."), "veja make.com e n8n fim")

    def test_phrases_and_helpers(self):
        self.assertEqual(has_any("Aprenda After  Effects hoje", ["after effects"]), ["after effects"])
        self.assertEqual(normalize("Ação!"), "acao")


if __name__ == "__main__":
    unittest.main()

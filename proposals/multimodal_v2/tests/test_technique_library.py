import unittest

from tests import _helpers  # noqa: F401
from ii_mm import adapters as A
from ii_mm.classifier import Classifier
from ii_mm.db.migrations import open_database
from ii_mm.db.repository import Repository
from ii_mm.normalize import Normalizer
from ii_mm.synthetic import sha
from ii_mm.technique_library import (references_with_ai_tool_interface, references_with_caption_style, references_with_technique,
                                     reproduction_guide, technique_overview)
from ii_mm.techniques import build_techniques


def make(name, observations, suggestions=()):
    n = Normalizer(f"ref_{name}", "instagram", f"SYNTH{name}", 30.0, content_sha256=sha(name),
                   origin_url=f"https://www.instagram.com/reel/SYNTH{name}/")
    n.add_frames(A.frames_from_manifest({"frames": [{"pacote_id": f"P{i}", "t_s": 5 + i * 0.04, "sha256": sha(f"{name}{i}")} for i in range(3)]}))
    res = A.observations_from_json([dict(t_s=5, **o) for o in observations], "agent:lib")
    assert not [e for e in res.errors if "atributo" in e], res.errors
    n.add_observations(res)
    doc = Classifier().classify(n.build())
    doc["techniques"] = build_techniques(doc, suggestions)
    return doc


class TechniqueLibraryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.conn = open_database()
        repo = Repository(cls.conn)
        repo.save_analysis(make("lib01", [
            {"frame_refs": ["P0"], "tag": "split_screen", "text": "tela dividida"},
            {"frame_refs": ["P0"], "tag": "burned_caption", "text": "uma palavra grande no centro",
             "attributes": {"size": "large", "words_per_caption": 1, "position": "center"}},
            {"frame_refs": ["P1"], "tag": "tool_name_visible", "text": "nome ChatGPT legível"}],
            suggestions=[{"technique": "split_screen", "text": "gravar tela e rosto e compor 9:16", "requires": ["editor com camadas"], "author": "agent:lib"}]))
        repo.save_analysis(make("lib02", [
            {"frame_refs": ["P0"], "tag": "split_screen", "text": "possível tela dividida", "kind": "hypothesis"},
            {"frame_refs": ["P0"], "tag": "burned_caption", "text": "legenda pequena", "attributes": {"size": "small", "words_per_caption": 4}},
            {"frame_refs": ["P0"], "tag": "ui_screen_visible", "text": "interface parecida com o Midjourney"}]))
        repo.save_analysis(make("lib03", [{"frame_refs": ["P0", "P1"], "tag": "kinetic_typography", "text": "texto muda entre quadros"}]))

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()

    def test_split_screen_distinguishes_demonstrated_from_hypothesis(self):
        res = references_with_technique(self.conn, "split_screen")
        got = {(r["reference_id"], r["level"], r["demonstrated"]) for r in res}
        self.assertIn(("ref_lib01", "observed_in_frame", True), got)
        self.assertIn(("ref_lib02", "hypothesis", False), got)
        self.assertIn(("ref_lib01", "reproduction_suggestion", False), got)
        r1 = next(r for r in res if r["reference_id"] == "ref_lib01" and r["level"] == "observed_in_frame")
        self.assertEqual(r1["evidence"][0]["observer"], "agent:lib")
        self.assertTrue(r1["does_not_prove"])

    def test_large_single_word_captions(self):
        res = references_with_caption_style(self.conn, size="large", words_per_caption=1)
        self.assertEqual([r["reference_id"] for r in res], ["ref_lib01"])
        self.assertEqual(res[0]["evidence"][0]["attributes"]["size"], "large")
        self.assertIn("animação", res[0]["limitation"])
        self.assertEqual(references_with_caption_style(self.conn, size="large", words_per_caption=4), [])

    def test_ai_tool_interfaces_keep_identification_status(self):
        res = {(r["reference_id"], r["tool"], r["identification"]) for r in references_with_ai_tool_interface(self.conn)}
        self.assertEqual(res, {("ref_lib01", "ChatGPT", "visually_identified"), ("ref_lib02", "Midjourney", "inferred")})

    def test_overview_demonstrated_vs_hypothesis(self):
        ov = technique_overview(self.conn)
        self.assertEqual(ov["split_screen"], {"demonstrated": 1, "hypothesis_only": 1, "suggestions": 1})
        self.assertEqual(ov["tipografia_cinetica"], {"demonstrated": 0, "hypothesis_only": 1, "suggestions": 0})

    def test_reproduction_guide_is_labelled_as_creative_proposal(self):
        g = reproduction_guide(self.conn, "split_screen")
        self.assertEqual(g["status"], "proposta_criativa")
        self.assertIn("Não reconstroem", g["disclaimer"])
        self.assertEqual(g["ideas"][0]["requires"], ["editor com camadas"])
        self.assertEqual([o["reference_id"] for o in g["observed_examples"]], ["ref_lib01"])
        self.assertEqual(g["still_needs_continuous_video"], ["ref_lib01"])

    def test_attribute_validation(self):
        res = A.observations_from_json([{"frame_refs": ["P0"], "t_s": 1, "tag": "burned_caption", "text": "x",
                                         "attributes": {"size": "gigante", "fonte": "Arial", "words_per_caption": 0}}], "agent:t")
        self.assertEqual(res.records[0]["attributes"], {})
        self.assertEqual(len([e for e in res.errors if "atribut" in e or "valor inválido" in e]), 3)

    def test_unknown_technique(self):
        with self.assertRaises(ValueError):
            references_with_technique(self.conn, "teletransporte")


if __name__ == "__main__":
    unittest.main()

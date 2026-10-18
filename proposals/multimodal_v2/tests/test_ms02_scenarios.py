"""Missão Suprema 02, T10: classificação por múltiplas evidências em cenários combinados (dados sintéticos)."""
import unittest

from tests import _helpers  # noqa: F401
from ii_mm import adapters as A
from ii_mm.classifier import Classifier
from ii_mm.contract import validate_document
from ii_mm.narrative import suggest_blocks
from ii_mm.normalize import Normalizer
from ii_mm.synthetic import sha
from ii_mm.techniques import build_techniques


class Scenario:
    def __init__(self, name):
        self.n = Normalizer(f"ref_{name}", "instagram", f"SYNTH{name}", 40.0, content_sha256=sha(name))
        self.n.add_frames(A.frames_from_manifest({"frames": [{"pacote_id": f"P{i}", "t_s": 10 + i * 0.04, "sha256": sha(f"{name}{i}")} for i in range(4)]}))

    def say(self, *texts):
        self.n.add_transcript(A.transcript_from_segments([{"start": i * 4, "end": i * 4 + 3, "text": t} for i, t in enumerate(texts)]))
        return self

    def meta(self, caption, tags=()):
        self.n.add_metadata(caption, list(tags))
        return self

    def see(self, tag, text, refs=("P0",), kind="observation"):
        self.n.add_observations(A.observations_from_json([{"frame_refs": list(refs), "t_s": 10, "tag": tag, "text": text, "kind": kind}], "agent:t"))
        return self

    def cuts(self, *ts):
        self.n.add_scene_candidates(A.scenes_from_candidates_json({"candidatos": [{"t_s": t, "score": 0.6} for t in ts]}))
        return self

    def run(self):
        doc = Classifier().classify(self.n.build())
        doc["techniques"] = build_techniques(doc)
        doc["narrative_blocks"] = suggest_blocks(doc)
        assert validate_document(doc) == [], validate_document(doc)
        return doc


def cats(doc):
    return {c["category"]: c["support"] for c in doc["categories"]}


def tools(doc):
    return {t["name"]: t["status"] for t in doc["tools"]}


class MultiEvidenceScenariosTest(unittest.TestCase):
    def test_no_caption_but_visual_evidence(self):
        d = Scenario("s01").see("split_screen", "tela dividida").see("burned_caption", "legenda grande").run()
        self.assertEqual(cats(d), {"edicao_audiovisual": "supported_visual"})
        self.assertFalse(any(e["status"] == "metadata_claim" for e in d["evidence"]))

    def test_tool_cited_without_interface(self):
        d = Scenario("s02").say("eu edito tudo no capcut").run()
        self.assertEqual(tools(d), {"CapCut": "mentioned_only"})
        self.assertNotIn("demonstracao_ferramenta", cats(d))   # citar não é demonstrar
        self.assertEqual(cats(d).get("edicao_audiovisual"), "mentioned_speech")

    def test_interface_without_legible_name(self):
        d = Scenario("s03").see("ui_screen_visible", "tela de edição com timeline, sem nome legível").run()
        self.assertEqual(cats(d), {"demonstracao_ferramenta": "supported_visual"})
        self.assertEqual(tools(d), {})

    def test_cinematic_video_without_speech(self):
        d = Scenario("s04").see("cinematic_composition", "plano aberto com profundidade de campo rasa").see("shallow_depth_of_field", "fundo desfocado", refs=("P1",)).run()
        self.assertEqual(cats(d), {"cinematografia": "supported_visual"})
        self.assertEqual(d["transcript"], [])
        self.assertEqual(d["narrative_blocks"], [])   # sem fala não há bloco narrativo inventado
        self.assertEqual({t["technique"] for t in d["techniques"]}, {"composicao_cinematografica"})

    def test_tutorial_without_tool(self):
        d = Scenario("s05").say("passo a passo para organizar sua rotina").run()
        self.assertEqual(cats(d), {"tutorial": "mentioned_speech"})
        self.assertEqual(tools(d), {})

    def test_advertising_disguised_as_tutorial_shows_both(self):
        d = (Scenario("s06").say("tutorial passo a passo", "comenta e clica no link na bio")
             .meta("curso com 50% de desconto").see("price_or_discount_on_screen", "selo de 50% off", refs=("P2",)).run())
        c = cats(d)
        self.assertEqual(c["tutorial"], "mentioned_speech")
        self.assertEqual(c["marketing_vendas"], "supported_visual")   # a oferta é vista; o tutorial é só dito
        self.assertTrue({"oferta", "cta"} <= {b["type"] for b in d["narrative_blocks"]})

    def test_motion_design_only_suggested(self):
        d = Scenario("s07").meta("#motiondesign").run()
        self.assertEqual(cats(d), {"motion_design": "suggested_metadata"})
        d = Scenario("s07b").see("kinetic_typography", "texto parece animado", refs=("P0", "P1")).run()
        self.assertEqual(cats(d), {"motion_design": "hypothesis"})
        self.assertEqual([(t["technique"], t["level"]) for t in d["techniques"]], [("tipografia_cinetica", "hypothesis")])

    def test_detected_cut_without_technique_confirmation(self):
        d = Scenario("s08").cuts(5.0, 12.3, 20.1).run()
        self.assertEqual(d["categories"], [])
        self.assertEqual(d["techniques"], [])
        self.assertEqual(sum(e["tag"] == "scene_candidate" for e in d["evidence"]), 3)

    def test_multiple_valid_categories(self):
        d = (Scenario("s09").say("tutorial de motion design no after effects", "automatizo a entrega com n8n")
             .see("tool_name_visible", "nome After Effects legível").run())
        self.assertEqual(set(cats(d)), {"tutorial", "demonstracao_ferramenta", "automacao", "motion_design"})
        self.assertEqual(tools(d)["Adobe After Effects"], "visually_identified")
        self.assertEqual(tools(d)["n8n"], "mentioned_only")

    def test_contradictory_evidence(self):
        d = Scenario("s10").say("olha so essa ferramenta incrível").see("no_ui_visible", "só o rosto do apresentador", refs=("P3",)).run()
        demo = next(c for c in d["categories"] if c["category"] == "demonstracao_ferramenta")
        self.assertTrue(demo["contested"])
        self.assertEqual(demo["support"], "mentioned_speech")
        self.assertEqual(len(demo["contradicting_evidence_ids"]), 1)


if __name__ == "__main__":
    unittest.main()

import unittest

from tests import _helpers  # noqa: F401
from ii_mm import adapters as A
from ii_mm.classifier import Classifier, ClassifierConfig, MeasuredRule
from ii_mm.contract import validate_document
from ii_mm.normalize import Normalizer
from ii_mm.synthetic import sha

FA, FB, FC = sha("fa"), sha("fb"), sha("fc")


def base():
    n = Normalizer("ref_S", "instagram", "S", 60.0, content_sha256=sha("c-s"))
    n.add_frames(A.frames_from_manifest({"frames": [
        {"pacote_id": "P01", "t_s": 20.0, "sha256": FA}, {"pacote_id": "P02", "t_s": 20.033, "sha256": FB},
        {"pacote_id": "P03", "t_s": 20.066, "sha256": FC}]}))
    return n


def say(n, *texts):
    segs = [{"start": i * 3, "end": i * 3 + 2.5, "text": t} for i, t in enumerate(texts)]
    return n.add_transcript(A.transcript_from_segments(segs))


def see(n, tag, *refs, text=None, kind="observation", observer="agent:t"):
    return n.add_observations(A.observations_from_json(
        [{"frame_refs": list(refs or ["P01"]), "t_s": 20.0, "tag": tag, "text": text or f"obs {tag}", "kind": kind}], observer))


def run(n, **cfg):
    doc = Classifier(ClassifierConfig(**cfg) if cfg else None).classify(n.build())
    problems = validate_document(doc)
    assert problems == [], problems
    return doc


def cat(doc, name):
    return next((c for c in doc["categories"] if c["category"] == name), None)


class SupportStatesTest(unittest.TestCase):
    def test_all_six_support_states_reachable(self):
        n = base()
        see(n, "ui_screen_visible")                                    # supported_visual
        say(n, "tutorial passo a passo")                               # mentioned_speech
        n.add_metadata("link na bio com desconto")                     # suggested_metadata
        see(n, "cinematic_look", "P02", kind="hypothesis")             # hypothesis
        say(n, "edit rapidinho")                                       # insufficient (fraco)
        n.add_scene_candidates(A.scenes_from_candidates_json({"candidatos": [{"t_s": t, "score": 0.5} for t in (5, 9, 14)]}))
        doc = run(n, measured_rules=[MeasuredRule("edicao_audiovisual", "scene_candidate", 0.3, 3)])
        got = {c["category"]: c["support"] for c in doc["categories"]}
        self.assertEqual(got["demonstracao_ferramenta"], "supported_visual")
        self.assertEqual(got["tutorial"], "mentioned_speech")
        self.assertEqual(got["marketing_vendas"], "suggested_metadata")
        self.assertEqual(got["cinematografia"], "hypothesis")
        self.assertEqual(got["edicao_audiovisual"], "supported_measured")
        self.assertIn("não calibrada", cat(doc, "edicao_audiovisual")["notes"][0])

    def test_weak_only_text_is_insufficient(self):
        n = base(); say(n, "edit rapidinho")
        c = cat(run(n), "edicao_audiovisual")
        self.assertEqual((c["support"], c["evidence_ids"]), ("insufficient", []))
        self.assertEqual(c["weak_signals"][0]["terms"], ["edit"])


class MeasurementRulesTest(unittest.TestCase):
    def scenes(self, n, k, score=0.5):
        n.add_scene_candidates(A.scenes_from_candidates_json({"candidatos": [{"t_s": 2 + i, "score": score} for i in range(k)]}))

    def test_measurement_alone_creates_nothing_by_default(self):
        n = base(); self.scenes(n, 10)
        self.assertEqual(run(n)["categories"], [])

    def test_measurement_is_context_when_category_exists(self):
        n = base(); self.scenes(n, 2); say(n, "edição no capcut")
        c = cat(run(n), "edicao_audiovisual")
        self.assertEqual(c["support"], "mentioned_speech")
        self.assertEqual(len(c["context_evidence_ids"]), 2)

    def test_measured_rule_thresholds(self):
        n = base(); self.scenes(n, 2)
        self.assertEqual(run(n, measured_rules=[MeasuredRule("edicao_audiovisual", "scene_candidate", 0.3, 3)])["categories"], [])
        n = base(); self.scenes(n, 5, score=0.1)
        self.assertEqual(run(n, measured_rules=[MeasuredRule("edicao_audiovisual", "scene_candidate", 0.3, 3)])["categories"], [])

    def test_invalid_rule_rejected(self):
        with self.assertRaises(ValueError):
            Classifier(ClassifierConfig(measured_rules=[MeasuredRule("inventada", "x", 0, 1)]))


class EvidenceSemanticsTest(unittest.TestCase):
    def test_speech_about_screen_does_not_make_visual_support(self):
        n = base(); say(n, "olha essa ferramenta na tela aqui em cima")
        self.assertEqual(cat(run(n), "demonstracao_ferramenta")["support"], "mentioned_speech")

    def test_contradictions_are_preserved_and_flagged(self):
        n = base(); say(n, "olha so essa ferramenta"); see(n, "no_ui_visible", "P02")
        doc = run(n)
        c = cat(doc, "demonstracao_ferramenta")
        self.assertTrue(c["contested"])
        self.assertEqual(len(c["contradicting_evidence_ids"]), 1)
        self.assertEqual(c["support"], "mentioned_speech")
        self.assertTrue(any(p["pending_id"] == "auto:contested:demonstracao_ferramenta" for p in doc["pending"]))

    def test_contradiction_only(self):
        n = base(); see(n, "no_offer_on_screen")
        c = cat(run(n), "marketing_vendas")
        self.assertEqual((c["support"], c["evidence_ids"]), ("insufficient", []))

    def test_multiple_evidence_types_in_one_category(self):
        n = base(); say(n, "tutorial completo"); n.add_metadata("#passoapasso"); see(n, "step_sequence_visible", "P01", "P02", "P03")
        c = cat(run(n), "tutorial")
        self.assertEqual(c["support"], "supported_visual")
        self.assertEqual(len(c["evidence_ids"]), 3)
        self.assertEqual({b["rule"] for b in c["basis"]}, {"text_v2", "visual_tag"})

    def test_motion_from_two_frames_is_only_hypothesis(self):
        n = base(); see(n, "kinetic_typography", "P01", "P02")
        self.assertEqual(cat(run(n), "motion_design")["support"], "hypothesis")
        n = base(); see(n, "kinetic_typography", "P01", "P02", "P03")
        self.assertEqual(cat(run(n), "motion_design")["support"], "supported_visual")

    def test_no_numeric_confidence_and_canonical_order(self):
        n = base(); say(n, "desconto no tutorial de motion design com n8n")
        doc = run(n)
        order = [c["category"] for c in doc["categories"]]
        self.assertEqual(order, ["tutorial", "automacao", "motion_design", "marketing_vendas"])

    def test_deterministic(self):
        def build():
            n = base(); say(n, "tutorial", "n8n workflow"); see(n, "split_screen"); n.add_metadata("#motiondesign")
            return run(n)
        self.assertEqual(build(), build())


class ToolsTest(unittest.TestCase):
    def test_mentioned_vs_visually_identified(self):
        n = base(); say(n, "eu uso o capcut e o n8n"); see(n, "ui_screen_visible", text="interface do CapCut com timeline")
        tools = {t["name"]: t["status"] for t in run(n)["tools"]}
        self.assertEqual(tools, {"CapCut": "visually_identified", "n8n": "mentioned_only"})

    def test_metadata_only_and_inferred(self):
        n = base(); n.add_metadata("feito no #canva"); see(n, "ui_screen_visible", text="parece o Figma", kind="hypothesis")
        tools = {t["name"]: t["status"] for t in run(n)["tools"]}
        self.assertEqual(tools, {"Canva": "metadata_only", "Figma": "inferred"})

    def test_tool_name_in_non_ui_observation_is_not_identification(self):
        n = base(); see(n, "burned_caption", text="legenda diz CapCut")
        self.assertEqual(run(n)["tools"], [])

    def test_ai_topic_facet(self):
        n = base(); say(n, "usei o chatgpt e inteligência artificial", "eu ia sair")
        self.assertEqual(run(n)["topic_facets"]["ai_terms"], ["chatgpt", "inteligencia artificial"])


class ReclassificationTest(unittest.TestCase):
    def test_human_review_state_survives_reclassification(self):
        n = base(); say(n, "tutorial")
        clf = Classifier()
        doc = clf.classify(n.build())
        doc["categories"][0]["review_state"] = "accepted"
        doc["categories"][0]["review_ref"] = "rv_1"
        again = clf.classify(doc)
        self.assertEqual(again["categories"][0]["review_state"], "accepted")
        self.assertEqual(again["categories"][0]["review_ref"], "rv_1")
        self.assertEqual(len(again["classification_runs"]), 2)
        self.assertEqual(sum(1 for p in again["pending"] if p["pending_id"].startswith("auto:")), 0)

    def test_rejects_wrong_schema(self):
        with self.assertRaises(ValueError):
            Classifier().classify({"schema_version": "x"})


if __name__ == "__main__":
    unittest.main()

import copy
import unittest

from tests import _helpers  # noqa: F401
from ii_mm import adapters as A
from ii_mm.classifier import Classifier
from ii_mm.db.migrations import open_database
from ii_mm.db.repository import Repository
from ii_mm.normalize import Normalizer
from ii_mm.review import ReviewConflict, ReviewError, ReviewService
from ii_mm.synthetic import sha


def analysed_doc(extra_speech=None):
    n = Normalizer("ref_R1", "instagram", "SYNTHrev01", 30.0, content_sha256=sha("rev"),
                   origin_url="https://www.instagram.com/reel/SYNTHrev01/")
    n.add_frames(A.frames_from_manifest({"frames": [{"pacote_id": "P01", "t_s": 5, "sha256": sha("p1")}]}))
    n.add_transcript(A.transcript_from_segments([{"start": 0, "end": 3, "text": "tutorial passo a passo no capcut"}] + (extra_speech or [])))
    n.add_observations(A.observations_from_json([{"frame_refs": ["P01"], "t_s": 5, "tag": "ui_screen_visible",
                                                  "text": "interface do CapCut"}], "agent:t"))
    return Classifier().classify(n.build())


class ReviewTest(unittest.TestCase):
    def setUp(self):
        conn = open_database()
        self.addCleanup(conn.close)
        self.repo = Repository(conn)
        self.doc = analysed_doc()
        self.res = self.repo.save_analysis(self.doc)
        self.ref = self.res.reference_id
        self.rv = ReviewService(self.repo)

    def test_accept_reject_add_and_history(self):
        self.rv.accept_category(self.ref, "tutorial", "human:ana")
        self.assertIn("edicao_audiovisual", {c["category"] for c in self.doc["categories"]})  # "capcut" é termo forte
        self.rv.reject_category(self.ref, "edicao_audiovisual", "human:ana", "capcut citado, mas sem edição visível")
        self.rv.add_category(self.ref, "conhecimento", "human:ana", "explica conceito no início")
        view = self.rv.reviewed_document(self.ref)
        cats = {c["category"]: c for c in view["categories"]}
        self.assertEqual(cats["tutorial"]["review_state"], "accepted")
        self.assertTrue(cats["conhecimento"]["added_by_human"])
        self.assertEqual(cats["conhecimento"]["support"], "insufficient")
        self.assertEqual(cats["edicao_audiovisual"]["review_state"], "rejected")
        self.assertGreaterEqual(len(view["review_history"]), 2)

    def test_original_analysis_never_changes(self):
        before = self.repo.get_document(self.res.analysis_id)
        self.rv.reject_category(self.ref, "tutorial", "human:ana", "na verdade é demonstração")
        self.rv.correct_tool_name(self.ref, "CapCut", "CapCut Pro", "human:ana", "versão Pro visível")
        self.assertEqual(self.repo.get_document(self.res.analysis_id), before)
        self.assertEqual(self.repo.conn.execute("SELECT auto_review_state FROM categories WHERE category='tutorial'").fetchone()[0], "pending")

    def test_successive_reviews_keep_full_history(self):
        self.rv.accept_category(self.ref, "tutorial", "human:ana")
        self.rv.reject_category(self.ref, "tutorial", "human:beto", "é demonstração, não tutorial")
        self.rv.accept_category(self.ref, "tutorial", "human:ana", "revisado de novo com o vídeo")
        hist = self.rv.history(self.ref)
        self.assertEqual([h["seq"] for h in hist], [1, 2, 3])
        self.assertEqual([h["action"] for h in hist], ["accept_category", "reject_category", "accept_category"])
        self.assertIn('"rejected"', hist[2]["before_json"])
        self.assertEqual(self.rv.decisions(self.ref)["category:tutorial"]["state"], "accepted")

    def test_optimistic_conflict(self):
        seen = self.rv.last_seq(self.ref)
        self.rv.accept_category(self.ref, "tutorial", "human:ana", expected_seq=seen)
        with self.assertRaises(ReviewConflict):
            self.rv.reject_category(self.ref, "tutorial", "human:beto", "discordo", expected_seq=seen)
        self.assertEqual(len(self.rv.history(self.ref)), 1)

    def test_justification_and_validation(self):
        with self.assertRaises(ReviewError):
            self.rv.reject_category(self.ref, "tutorial", "human:ana", "  ")
        with self.assertRaises(ReviewError):
            self.rv.accept_category(self.ref, "cinematografia", "human:ana")
        with self.assertRaises(ReviewError):
            self.rv.add_category(self.ref, "inventada", "human:ana", "x")
        with self.assertRaises(ReviewError):
            self.rv.correct_tool_name(self.ref, "Inexistente", "X", "human:ana", "x")
        with self.assertRaises(ReviewError):
            self.rv.accept_category(self.ref, "tutorial", "")
        with self.assertRaises(ReviewError):
            self.rv.accept_category("ref_que_nao_existe", "tutorial", "human:ana")

    def test_tool_correction_overlay(self):
        self.rv.correct_tool_name(self.ref, "CapCut", "CapCut Desktop", "human:ana", "versão desktop na tela")
        tool = self.rv.reviewed_document(self.ref)["tools"][0]
        self.assertEqual((tool["name"], tool["corrected_from"], tool["status"]), ("CapCut Desktop", "CapCut", "visually_identified"))

    def test_mark_observation_as_hypothesis_recomputes_support(self):
        vis = next(e for e in self.doc["evidence"] if e["status"] == "observed_visual")
        self.rv.mark_evidence_hypothesis(self.ref, vis["evidence_id"], "human:ana", "frame borrado, não dá para afirmar")
        view = self.rv.reviewed_document(self.ref)
        ev = next(e for e in view["evidence"] if e["evidence_id"] == vis["evidence_id"])
        self.assertEqual((ev["status"], ev["original_status"]), ("inference", "observed_visual"))
        demo = next(c for c in view["categories"] if c["category"] == "demonstracao_ferramenta")
        self.assertEqual(demo["support"], "hypothesis")
        tool = view["tools"][0]
        self.assertEqual((tool["name"], tool["status"], tool["visual_evidence_ids"]), ("CapCut", "mentioned_only", []))

    def test_speech_evidence_cannot_be_marked(self):
        sp = next(e for e in self.doc["evidence"] if e["status"] == "transcript_claim")
        with self.assertRaises(ReviewError):
            self.rv.mark_evidence_hypothesis(self.ref, sp["evidence_id"], "human:ana", "x")

    def test_decisions_survive_reprocessing_and_orphans_reported(self):
        vis = next(e for e in self.doc["evidence"] if e["status"] == "observed_visual")
        self.rv.accept_category(self.ref, "tutorial", "human:ana")
        self.rv.mark_evidence_hypothesis(self.ref, vis["evidence_id"], "human:ana", "duvidoso")
        new_doc = analysed_doc(extra_speech=[{"start": 10, "end": 12, "text": "link na bio"}])
        new_doc["evidence"] = [e for e in new_doc["evidence"] if e["evidence_id"] != vis["evidence_id"]]
        new_doc = Classifier().classify(new_doc)
        new_doc["tools"] = [t for t in new_doc["tools"]]
        res2 = self.repo.save_analysis(new_doc)
        self.assertTrue(res2.created)
        view = self.rv.reviewed_document(self.ref)
        cats = {c["category"]: c for c in view["categories"]}
        self.assertEqual(cats["tutorial"]["review_state"], "accepted")
        self.assertIn(f"evidence:{vis['evidence_id']}", view["orphan_decisions"])


if __name__ == "__main__":
    unittest.main()

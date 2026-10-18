import copy
import json
import unittest

from tests import _helpers  # noqa: F401
from ii_mm import SCHEMA_VERSION
from ii_mm.contract import (
    ContractError, V1_TO_V2_STATUS, assert_valid, empty_document, evidence_id, make_evidence, validate_document,
)
from ii_mm.evidence_rules import SUPPORT_LEVELS, category_support
from ii_mm.synthetic import make_reference, sha

FRAME_SHA = sha("frame-x")


def doc_with(*evidence, frames=None, transcript=None):
    d = empty_document("ref_X", "instagram", "SYNTHX", 30.0, content_sha256=sha("c"))
    d["frames"] = frames if frames is not None else [{"frame_id": "F01", "t_s": 5.0, "sha256": FRAME_SHA}]
    d["transcript"] = transcript if transcript is not None else [{"segment_id": "s1", "t_start_s": 0, "t_end_s": 3, "text": "oi"}]
    d["evidence"] = list(evidence)
    return d


def vis(basis="static_frame", t=5.0, ref="F01", claim="tela visível", **kw):
    return make_evidence("SYNTHX", status="observed_visual", source_type="agent_observation", claim=claim,
                         t_start_s=t, ref=ref, basis=basis, provenance={"source": "test", "artifact_sha256": FRAME_SHA}, **kw)


def speech(claim="essa ferramenta faz tudo", ref="s1"):
    return make_evidence("SYNTHX", status="transcript_claim", source_type="whisper", claim=claim,
                         t_start_s=0, t_end_s=3, ref=ref, provenance={"source": "whisper"})


class ContractTest(unittest.TestCase):
    def test_synthetic_fixtures_are_valid(self):
        for i in range(60):
            self.assertEqual(validate_document(make_reference(i)), [], i)

    def test_fixture_file_is_valid_and_matches_generator(self):
        from pathlib import Path
        path = Path(__file__).resolve().parents[1] / "fixtures" / "synthetic_reference_v2.json"
        doc = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(validate_document(doc), [])
        self.assertEqual(doc, make_reference(3))

    def test_evidence_id_is_content_based_and_order_independent(self):
        a = evidence_id("v", "transcript_claim", "whisper", 1.0, 2.0, "s1", "x")
        self.assertEqual(a, evidence_id("v", "transcript_claim", "whisper", 1.0000001, 2.0, "s1", "x"))
        self.assertNotEqual(a, evidence_id("w", "transcript_claim", "whisper", 1.0, 2.0, "s1", "x"))
        self.assertNotEqual(a, evidence_id("v", "metadata_claim", "whisper", 1.0, 2.0, "s1", "x"))

    def test_speech_cannot_be_observed_visual(self):
        bad = make_evidence("SYNTHX", status="observed_visual", source_type="whisper", claim="disse que tem tela",
                            t_start_s=1, basis="static_frame", provenance={"source": "x", "artifact_sha256": FRAME_SHA})
        self.assertTrue(any("não pode sustentar" in p for p in validate_document(doc_with(bad))))

    def test_observed_visual_requires_basis_artifact_and_known_frame(self):
        e = vis(); e["basis"] = None
        self.assertTrue(any("exige basis" in p for p in validate_document(doc_with(e))))
        e = vis(); e["provenance"] = {"source": "t"}
        self.assertTrue(any("artifact_sha256" in p for p in validate_document(doc_with(e))))
        self.assertTrue(any("não corresponde a frame" in p for p in validate_document(doc_with(vis(ref="F99")))))

    def test_timestamps_bounded_by_duration(self):
        self.assertTrue(any("excede a duração" in p for p in validate_document(doc_with(vis(t=99.0)))))
        e = speech(); e["t_start_s"], e["t_end_s"] = 3, 1
        self.assertTrue(any("intervalo inválido" in p for p in validate_document(doc_with(e))))

    def test_forbidden_confidence_keys_anywhere(self):
        d = doc_with(speech())
        d["categories"] = [{"category": "tutorial", "support": "mentioned_speech", "evidence_ids": [d["evidence"][0]["evidence_id"]],
                            "extra": {"confidence": 0.9}}]
        self.assertTrue(any("confiança" in p for p in validate_document(d)))

    def test_support_must_match_evidence(self):
        d = doc_with(speech())
        d["categories"] = [{"category": "tutorial", "support": "supported_visual", "evidence_ids": [d["evidence"][0]["evidence_id"]]}]
        self.assertTrue(any("incoerente" in p for p in validate_document(d)))

    def test_contradiction_cannot_be_both_sides(self):
        s = speech(); d = doc_with(s)
        d["categories"] = [{"category": "tutorial", "support": "mentioned_speech", "evidence_ids": [s["evidence_id"]],
                            "contradicting_evidence_ids": [s["evidence_id"]]}]
        self.assertTrue(any("a favor e contra" in p for p in validate_document(d)))

    def test_tool_visual_status_requires_visual_evidence(self):
        s = speech(); d = doc_with(s)
        d["tools"] = [{"name": "ToolAlpha", "status": "visually_identified", "visual_evidence_ids": [s["evidence_id"]]}]
        probs = validate_document(d)
        self.assertTrue(any("sem evidência observed_visual" in p for p in probs))
        self.assertTrue(any("contém evidência não visual" in p for p in probs))

    def test_technique_levels_require_matching_basis(self):
        pair = vis(basis="frame_pair"); d = doc_with(pair)
        d["techniques"] = [{"technique": "transicao", "level": "temporal_sequence", "evidence_ids": [pair["evidence_id"]]}]
        self.assertTrue(any("par de quadros não prova movimento" in p for p in validate_document(d)))
        d["techniques"][0]["level"] = "frame_pair_difference"
        self.assertEqual(validate_document(d), [])
        single = vis(); d2 = doc_with(single)
        d2["techniques"] = [{"technique": "transicao", "level": "frame_pair_difference", "evidence_ids": [single["evidence_id"]]}]
        self.assertTrue(any("frame_pair ou superior" in p for p in validate_document(d2)))

    def test_dangling_references(self):
        d = doc_with(speech())
        d["categories"] = [{"category": "tutorial", "support": "insufficient", "evidence_ids": ["ev_nao_existe"]}]
        self.assertTrue(any("inexistente" in p for p in validate_document(d)))

    def test_malformed_documents_never_raise(self):
        for bad in (None, [], "x", {"schema_version": SCHEMA_VERSION}, {"schema_version": SCHEMA_VERSION, "reference": {}, "video": {}, "evidence": "x"}):
            self.assertTrue(validate_document(bad))
        d = doc_with(speech()); d["evidence"].append({"evidence_id": "e2"})
        self.assertTrue(validate_document(d))
        d = doc_with(); d["video"]["content_sha256"] = "XYZ"
        self.assertTrue(any("SHA-256" in p for p in validate_document(d)))

    def test_duplicates_detected(self):
        s = speech(); d = doc_with(s, s)
        self.assertTrue(any("duplicado" in p for p in validate_document(d)))

    def test_assert_valid(self):
        with self.assertRaises(ContractError):
            assert_valid({})
        assert_valid(make_reference(1))

    def test_category_support_ordering(self):
        self.assertEqual(category_support([]), "insufficient")
        self.assertEqual(category_support([speech(), vis()]), "supported_visual")
        self.assertEqual(category_support([{"status": "unverified"}]), "insufficient")
        self.assertEqual(len(SUPPORT_LEVELS), 6)

    def test_v1_status_mapping_complete(self):
        self.assertEqual(set(V1_TO_V2_STATUS), {"verified_visual", "measured", "claimed_transcript", "claimed_metadata", "hypothesis"})


if __name__ == "__main__":
    unittest.main()

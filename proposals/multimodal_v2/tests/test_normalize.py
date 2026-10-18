import unittest

from tests import _helpers  # noqa: F401
from ii_mm import adapters as A
from ii_mm.contract import validate_document
from ii_mm.normalize import Normalizer
from ii_mm.synthetic import sha

FA, FB, FC = sha("fa"), sha("fb"), sha("fc")


def norm():
    n = Normalizer("ref_SYNTH1", "instagram", "SYNTH1", 30.0, content_sha256=sha("conteudo"))
    n.add_frames(A.frames_from_manifest({"frames": [
        {"pacote_id": "P01", "t_s": 10.0, "sha256": FA}, {"pacote_id": "P02", "t_s": 10.033, "sha256": FB},
        {"pacote_id": "P03", "t_s": 10.066, "sha256": FC}]}))
    return n


def obs(*refs, tag="ui_screen_visible", kind="observation", basis=None, observer="agent:t"):
    o = {"frame_refs": list(refs), "t_s": 10.0, "tag": tag, "text": f"obs {tag}", "kind": kind}
    if basis:
        o["basis"] = basis
    return A.observations_from_json([o], observer=observer)


class NormalizerTest(unittest.TestCase):
    def test_full_document_is_contract_valid(self):
        n = norm()
        n.add_transcript(A.transcript_from_segments([{"start": 0, "end": 3, "text": "essa ferramenta faz tudo"}]))
        n.add_scene_candidates(A.scenes_from_candidates_json({"candidatos": [{"t_s": 10.05, "score": 0.3}]}))
        n.add_metadata("legenda #ia", ["#ia", "#motion"])
        n.add_observations(obs("P01"))
        n.add_legacy_label("relevante", "metadados: palavras_chave (ia)")
        doc = n.build()
        self.assertEqual(validate_document(doc), [])
        statuses = {e["status"] for e in doc["evidence"]}
        self.assertEqual(statuses, {"transcript_claim", "measured_signal", "metadata_claim", "observed_visual", "inference"})

    def test_transcript_never_becomes_visual(self):
        n = norm()
        n.add_transcript(A.transcript_from_segments([{"start": 0, "end": 3, "text": "olha a tela da ferramenta aqui em cima"}]))
        doc = n.build()
        self.assertTrue(all(e["status"] == "transcript_claim" for e in doc["evidence"]))
        self.assertTrue(all(e["provenance"]["untrusted_text"] for e in doc["evidence"]))

    def test_basis_derived_from_frame_count_and_overclaims_downgraded(self):
        n = norm()
        n.add_observations(obs("P01", basis="video_clip", tag="split_screen"))
        n.add_observations(obs("P01", "P02", tag="layered_composition"))
        n.add_observations(obs("P01", "P02", "P03", tag="b_roll_visible"))
        bases = {e["tag"]: e["basis"] for e in n.build()["evidence"]}
        self.assertEqual(bases, {"split_screen": "static_frame", "layered_composition": "frame_pair", "b_roll_visible": "frame_sequence"})
        self.assertTrue(any("rebaixada" in d for d in n.report["downgraded"]))

    def test_motion_from_one_or_two_frames_becomes_inference(self):
        n = norm()
        n.add_observations(obs("P01", "P02", tag="kinetic_typography"))
        n.add_observations(obs("P01", "P02", "P03", tag="motion_text_in_clip"))
        ev = {e["tag"]: e["status"] for e in n.build()["evidence"]}
        self.assertEqual(ev["kinetic_typography"], "inference")
        self.assertEqual(ev["motion_text_in_clip"], "observed_visual")
        self.assertEqual(validate_document(n.build()), [])

    def test_unknown_frame_reference_is_rejected(self):
        n = norm()
        n.add_observations(obs("P99"))
        self.assertEqual(n.build()["evidence"], [])
        self.assertTrue(any("não está registrado" in r for r in n.report["rejected"]))

    def test_duplicates_merged_keeping_second_origin(self):
        n = norm()
        seg = [{"start": 0, "end": 3, "text": "mesma fala"}]
        n.add_transcript(A.transcript_from_segments(seg, source="whisper_local"))
        n.add_scene_candidates(A.scenes_from_candidates_json({"candidatos": [{"t_s": 1, "score": 0.2}]}))
        n.add_scene_candidates(A.scenes_from_ffmpeg_metadata("pts_time:1.0\nlavfi.scene_score=0.2", threshold=0.04))
        doc = n.build()
        scene = [e for e in doc["evidence"] if e["tag"] == "scene_candidate"]
        self.assertEqual(len(scene), 1)
        self.assertEqual(n.report["merged_duplicates"], 1)
        self.assertEqual(scene[0]["provenance"]["also_from"][0]["source"], "ffmpeg_metadata_print")

    def test_out_of_range_and_conflicting_frames_rejected(self):
        n = norm()
        n.add_transcript(A.transcript_from_segments([{"start": 50, "end": 55, "text": "depois do fim"}]))
        n.add_frames(A.frames_from_manifest({"frames": [{"pacote_id": "P01", "t_s": 10, "sha256": sha("outro")}]}))
        n.add_scene_candidates(A.scenes_from_candidates_json({"candidatos": [{"t_s": 99, "score": 0.5}]}))
        rej = " | ".join(n.report["rejected"])
        self.assertIn("fora da duração", rej)
        self.assertIn("SHA-256 diferente", rej)
        self.assertEqual(n.build()["transcript"], [])

    def test_segment_id_collision_rejected(self):
        n = norm()
        n.add_transcript(A.transcript_from_segments([{"id": 1, "start": 0, "end": 1, "text": "a"}]))
        n.add_transcript(A.transcript_from_segments([{"id": 1, "start": 2, "end": 3, "text": "b"}]))
        self.assertTrue(any("já registrado" in r for r in n.report["rejected"]))

    def test_adapter_errors_propagate_to_report(self):
        n = norm()
        n.add_transcript(A.transcript_from_segments([{"start": 1, "text": "x"}]))
        self.assertTrue(n.report["adapter_errors"])

    def test_probe_duration_mismatch_rejected_and_match_accepted(self):
        n = norm()
        bad = A.probe_from_ffprobe_json({"streams": [{"codec_type": "video", "width": 1, "height": 1, "avg_frame_rate": "30/1"}], "format": {"duration": "45"}})
        self.assertIsNone(n.add_probe(bad))
        ok = A.probe_from_ffprobe_json({"streams": [{"codec_type": "video", "width": 1080, "height": 1920, "avg_frame_rate": "30/1"}], "format": {"duration": "30.1"}})
        self.assertIsNotNone(n.add_probe(ok))
        self.assertEqual(n.build()["video"]["fps"], 30.0)

    def test_human_vs_agent_and_hypothesis(self):
        n = norm()
        n.add_observations(obs("P01", observer="human:curador"))
        n.add_observations(obs("P02", tag="cinematic_look", kind="hypothesis"))
        ev = {e["tag"]: e for e in n.build()["evidence"]}
        self.assertEqual(ev["ui_screen_visible"]["source_type"], "human_observation")
        self.assertEqual(ev["cinematic_look"]["status"], "inference")

    def test_visual_metrics_are_measurements_not_techniques(self):
        n = norm()
        res = A.metrics_from_frame_pairs([{"timestamp_anterior_s": 10.0, "timestamp_atual_s": 10.033, "diff_absoluta_global": 31.2},
                                          {"timestamp_anterior_s": 40.0, "timestamp_atual_s": 40.5, "ssim_global": 0.4}])
        ids = n.add_visual_metrics(res)
        doc = n.build()
        self.assertEqual(len(ids), 1)
        self.assertEqual(doc["evidence"][0]["status"], "measured_signal")
        self.assertEqual(doc["evidence"][0]["extra"]["metrics"], {"diff_absoluta_global": 31.2})
        self.assertEqual(doc["techniques"], [])
        self.assertTrue(any("fora da duração" in r for r in n.report["rejected"]))

    def test_output_order_is_deterministic(self):
        def build(order):
            n = norm()
            steps = {"t": lambda: n.add_transcript(A.transcript_from_segments([{"start": 0, "end": 3, "text": "a"}])),
                     "o": lambda: n.add_observations(obs("P01")),
                     "m": lambda: n.add_metadata("legenda")}
            for k in order:
                steps[k]()
            return n.build()["evidence"]
        self.assertEqual(build("tom"), build("mot"))


if __name__ == "__main__":
    unittest.main()

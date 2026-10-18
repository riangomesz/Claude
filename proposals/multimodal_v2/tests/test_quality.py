import unittest

from tests import _helpers  # noqa: F401
from ii_mm import adapters as A
from ii_mm.normalize import Normalizer
from ii_mm.quality import temporal_quality
from ii_mm.synthetic import sha


def codes(rep):
    return {f["code"] for f in rep["findings"]}


def doc_with(frames=(), segs=(), duration=57.167528, fps=None):
    n = Normalizer("ref_Q", "instagram", "SYNTHq", duration, content_sha256=sha("q"))
    fr = A.frames_from_manifest({"frames": [{"pacote_id": f"F{i:02d}", "t_s": t, "sha256": sha(f"q{i}")} for i, t in enumerate(frames)]})
    n.add_frames(fr)
    tr = A.transcript_from_segments([{"start": a, "end": b, "text": f"s{i}"} for i, (a, b) in enumerate(segs)])
    n.add_transcript(tr)
    d = n.build()
    if fps:
        d["video"]["fps"] = fps
    return d, [fr, tr]


class TemporalQualityTest(unittest.TestCase):
    def test_pilot_like_gap_is_reported_with_interval(self):
        # padrão da 1ª análise do piloto: frames concentrados antes de 19 s e depois de 49 s (tempos sintéticos)
        d, _ = doc_with(frames=[0.5, 3, 6, 9, 12, 15, 18.9, 49.2, 53, 56])
        gaps = [f for f in temporal_quality(d)["findings"] if f["code"] == "large_sampling_gap"]
        self.assertEqual(gaps[0]["interval_s"], [18.9, 49.2])

    def test_negative_beyond_duplicates_and_unsorted_inputs(self):
        d, raw = doc_with(frames=[5.0, 5.0004, -1, 70, 2.0], duration=30)
        rep = temporal_quality(d, raw)
        # o adaptador já recusa tempo negativo na entrada (vira invalid_time_input); 70 s passa pelo adaptador
        # (que não conhece a duração) e é apontado aqui antes de a normalização rejeitá-lo
        self.assertTrue({"invalid_time_input", "beyond_duration", "duplicate_frame_timestamp"} <= codes(rep))
        self.assertEqual([f["t_s"] for f in d["frames"]], sorted(f["t_s"] for f in d["frames"]))  # ordem normalizada

    def test_overlapping_segments_and_missing_transcript(self):
        d, _ = doc_with(frames=[1, 2], segs=[(0, 3), (2.5, 5), (5, 6)], duration=10)
        self.assertIn("overlapping_segments", codes(temporal_quality(d)))
        d, _ = doc_with(frames=[1, 2], duration=10)
        self.assertIn("no_transcript", codes(temporal_quality(d)))

    def test_variable_frame_rate_and_av_desync_from_ffprobe(self):
        probe = A.probe_from_ffprobe_json({"streams": [
            {"codec_type": "video", "width": 1080, "height": 1920, "avg_frame_rate": "2997/100", "r_frame_rate": "60/1", "duration": "20.0"},
            {"codec_type": "audio", "duration": "21.4"}], "format": {"duration": "20.0"}}).records[0]
        self.assertTrue(probe["vfr_suspected"])
        d, _ = doc_with(frames=[1, 2], duration=20.0)
        self.assertTrue({"variable_frame_rate", "av_duration_mismatch"} <= codes(temporal_quality(d, probe=probe)))

    def test_rounding_off_frame_grid_is_info_only(self):
        d, _ = doc_with(frames=[1.0, 1.0333, 1.05], duration=5, fps=30.0)
        f = next(x for x in temporal_quality(d)["findings"] if x["code"] == "off_frame_grid")
        self.assertEqual(f["severity"], "info")
        self.assertIn("F02", f["detail"])

    def test_clean_input_and_no_percentages(self):
        d, raw = doc_with(frames=[float(t) for t in range(0, 30, 3)], segs=[(0, 2), (2, 4)], duration=30, fps=30.0)
        rep = temporal_quality(d, raw)
        self.assertEqual(rep["findings"], [])
        self.assertNotIn("%", str(rep))


if __name__ == "__main__":
    unittest.main()

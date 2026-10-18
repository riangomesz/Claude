import json
import unittest

from tests import _helpers  # noqa: F401
from ii_mm import adapters as A
from ii_mm.synthetic import sha

FFMPEG_STDOUT = """frame:0    pts:12345  pts_time:3.2
lavfi.scene_score=0.512000
frame:1    pts:23456  pts_time:7.94
lavfi.scene_score=0.081000
frame:2    pts:23456  pts_time:7.94
lavfi.scene_score=0.090000
lavfi.scene_score=0.999   # sem pts_time antes: ignorado
"""

SRT = """1
00:00:00,000 --> 00:00:02,500
Primeira fala

2
00:00:02,500 --> 00:00:05,100
Segunda
fala em duas linhas
"""


class TimestampTest(unittest.TestCase):
    def test_formats(self):
        cases = {"1.5": 1.5, 2: 2.0, "00:01.200": 1.2, "01:02": 62.0, "00:00:01,200": 1.2, "1:00:00.5": 3600.5}
        for raw, want in cases.items():
            self.assertAlmostEqual(A.parse_timestamp(raw), want, msg=raw)
        for bad in ("abc", None, "", "nan", float("inf"), True, "1:2:3:4"):
            self.assertIsNone(A.parse_timestamp(bad), repr(bad))


class TranscriptAdapterTest(unittest.TestCase):
    def test_faster_whisper_and_mission_and_core_formats(self):
        fw = A.transcript_from_segments([{"start": 0.0, "end": 1.5, "text": " oi  pessoal "}])
        self.assertEqual(fw.records[0]["text"], "oi pessoal")
        mi = A.transcript_from_segments({"segmentos": [{"id": 6, "inicio_s": 19.0, "fim_s": 21.0, "texto": "x"}]})
        self.assertEqual(mi.records[0]["segment_id"], "s6")
        core = A.transcript_from_segments({"segments": [{"index": 1, "start_time": "00:00:01,200", "end_time": "00:00:02,000", "text": "y"}]})
        self.assertEqual((core.records[0]["t_start_s"], core.records[0]["t_end_s"]), (1.2, 2.0))

    def test_srt(self):
        r = A.transcript_from_srt(SRT)
        self.assertTrue(r.ok, r.errors)
        self.assertEqual([s["text"] for s in r.records], ["Primeira fala", "Segunda fala em duas linhas"])
        self.assertFalse(A.transcript_from_srt("lixo").ok)
        self.assertFalse(A.transcript_from_srt(None).ok)

    def test_incomplete_duplicate_malformed(self):
        r = A.transcript_from_segments([
            {"start": 0, "end": 1, "text": "a"}, {"start": 0, "end": 1, "text": "a"},     # duplicado
            {"start": 2, "text": "sem fim"}, {"start": 3, "end": 2, "text": "invertido"},
            {"start": 4, "end": 5, "text": "   "}, "não objeto"])
        self.assertEqual(len(r.records), 1)
        self.assertEqual(len(r.errors), 5)
        self.assertFalse(A.transcript_from_segments("{nope").ok)
        self.assertFalse(A.transcript_from_segments({"x": 1}).ok)

    def test_records_sorted(self):
        r = A.transcript_from_segments([{"start": 5, "end": 6, "text": "b"}, {"start": 1, "end": 2, "text": "a"}])
        self.assertEqual([x["text"] for x in r.records], ["a", "b"])


class SceneAdapterTest(unittest.TestCase):
    def test_ffmpeg_metadata(self):
        r = A.scenes_from_ffmpeg_metadata(FFMPEG_STDOUT, threshold=0.04)
        self.assertEqual(r.records, [{"t_s": 3.2, "score": 0.512}, {"t_s": 7.94, "score": 0.09}])
        self.assertTrue(any("duplicado" in e for e in r.errors))

    def test_candidates_json(self):
        doc = {"schema_version": "ii.scene_candidates.v1", "limiar": 0.04, "candidatos": [{"t_s": 1, "score": 0.2}, {"t_s": -1, "score": 0.3}, {"x": 1}]}
        r = A.scenes_from_candidates_json(json.dumps(doc))
        self.assertEqual(len(r.records), 1)
        self.assertEqual(len(r.errors), 2)
        self.assertEqual(r.source["threshold"], 0.04)
        self.assertFalse(A.scenes_from_candidates_json({"candidatos": "x"}).ok)
        self.assertFalse(A.scenes_from_ffmpeg_metadata(None).ok)


class ProbeAndMetricsTest(unittest.TestCase):
    def test_ffprobe(self):
        payload = {"streams": [{"codec_type": "video", "width": 1080, "height": 1920, "avg_frame_rate": "30000/1001", "codec_name": "h264"},
                               {"codec_type": "audio"}], "format": {"duration": "57.167528"}}
        r = A.probe_from_ffprobe_json(payload)
        self.assertTrue(r.ok)
        self.assertEqual(r.records[0]["fps"], 29.97)
        self.assertTrue(r.records[0]["has_audio"])
        self.assertFalse(A.probe_from_ffprobe_json({"streams": [], "format": {}}).ok)
        self.assertFalse(A.probe_from_ffprobe_json("[").ok)

    def test_metric_pairs(self):
        pairs = [{"timestamp_anterior_s": 1.0, "timestamp_atual_s": 1.033, "diff_absoluta_global": 22.1, "ssim_global": 0.61, "outro": 1},
                 {"timestamp_anterior_s": 2.0, "timestamp_atual_s": 2.0, "ssim_global": 0.9},
                 {"timestamp_anterior_s": 3.0, "timestamp_atual_s": 3.1}]
        r = A.metrics_from_frame_pairs({"pares": pairs})
        self.assertEqual(len(r.records), 1)
        self.assertNotIn("outro", r.records[0]["metrics"])
        self.assertEqual(len(r.errors), 2)


class FramesAndObservationsTest(unittest.TestCase):
    def test_package_and_coverage_manifests(self):
        pkg = {"schema_version": "ii.evidence_package.v1", "video_sha256": sha("v"), "frames": [
            {"pacote_id": "P02", "t_s": 20.5, "sha256": sha("b"), "papel": "corte_depois", "par_com": "P01"},
            {"pacote_id": "P01", "t_s": 20.467, "sha256": sha("a"), "papel": "corte_antes", "par_com": "P02"},
            {"pacote_id": "P01", "t_s": 1, "sha256": sha("z")},
            {"pacote_id": "P03", "t_s": 2, "sha256": "curto"}]}
        r = A.frames_from_manifest(pkg)
        self.assertEqual([f["frame_id"] for f in r.records], ["P01", "P02"])
        self.assertEqual(len(r.errors), 2)
        cov = {"schema_version": "ii.coverage.manifest.v1", "video": {"sha256": sha("v")},
               "frames": [{"frame_id": "F01", "t_actual_s": 0.0, "sha256": sha("c"), "selection_origin": "grade"}]}
        r2 = A.frames_from_manifest(cov)
        self.assertEqual(r2.records[0]["role"], "grade")
        self.assertEqual(r2.source["video_sha256"], sha("v"))

    def test_observations(self):
        r = A.observations_from_json({"observations": [
            {"frame_refs": ["P01"], "t_s": 3, "tag": "ui_screen_visible", "text": "tela"},
            {"frame_ref": "P02", "t_s": 4, "tag": "burned_caption", "text": "legenda", "kind": "hypothesis"},
            {"frame_refs": [], "t_s": 3, "tag": "x", "text": "y"},
            {"frame_refs": ["P01"], "t_s": 3, "tag": "x", "text": "y", "kind": "certeza"}]}, observer="agent:test")
        self.assertEqual(len(r.records), 2)
        self.assertEqual(r.records[1]["frame_refs"], ["P02"])
        self.assertEqual(len(r.errors), 2)


if __name__ == "__main__":
    unittest.main()

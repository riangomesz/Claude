"""Missão Suprema 02, T15: ponta a ponta com interrupção e reenvio (dados sintéticos, banco temporário).

missão n8n assinada → gateway idempotente → pipeline com lease → adaptadores → normalização →
classificação → persistência → busca → revisão humana → exportação para staging.
"""
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from tests import _helpers  # noqa: F401
from ii_mm import adapters as A
from ii_mm import demo as D
from ii_mm.catalog import Query, search
from ii_mm.classifier import Classifier
from ii_mm.db.migrations import open_database
from ii_mm.db.repository import Repository
from ii_mm.dedup import analysis_input_hash
from ii_mm.n8n_contract import MISSION_SCHEMA, MissionGateway, build_result, compute_mission_id, sign
from ii_mm.narrative import suggest_blocks
from ii_mm.normalize import Normalizer
from ii_mm.obsidian_export import export_reference
from ii_mm.pipeline import STAGES, Pipeline
from ii_mm.review import ReviewService
from ii_mm.synthetic import sha
from ii_mm.techniques import build_techniques

SECRET = b"segredo-e2e-nao-real"
URL = "https://www.instagram.com/reel/SYNTHdemo01/"


def build_doc():
    n = Normalizer("ref_DEMO01", "instagram", "SYNTHdemo01", 24.0, content_sha256=sha("demo-video"), origin_url=URL, author_handle="autor_demo")
    n.add_frames(A.frames_from_manifest(D.FRAMES))
    n.add_probe(A.probe_from_ffprobe_json(D.FFPROBE))
    n.add_transcript(A.transcript_from_srt(D.SRT))
    n.add_scene_candidates(A.scenes_from_ffmpeg_metadata(D.FFMPEG, threshold=0.1))
    n.add_observations(A.observations_from_json(D.OBSERVATIONS, observer="agent:e2e"))
    doc = Classifier().classify(n.build())
    doc["narrative_blocks"] = suggest_blocks(doc)
    doc["techniques"] = build_techniques(doc)
    return doc


class EndToEndRecoveryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.conn = open_database(self.dir / "e2e.sqlite"); self.addCleanup(self.conn.close)
        self.repo = Repository(self.conn)
        self.stage = self.dir / "staging"
        self.crash_at = None
        self.calls = []

    def handlers(self):
        def h(stage):
            def run(ctx):
                self.calls.append(stage)
                if stage == self.crash_at:
                    self.crash_at = None
                    raise KeyboardInterrupt  # queda do processo no meio da etapa
                if stage == "discovered":
                    return "instagram:SYNTHdemo01"
                if stage == "media_available":
                    return sha("demo-video")
                if stage in ("metadata_extracted", "audio_processed", "visual_processed"):
                    return f"{stage}:ok"
                if stage == "evidence_normalized":
                    return analysis_input_hash(build_doc())          # determinístico: refazer dá o mesmo hash
                if stage == "classified":
                    return self.repo.save_analysis(build_doc()).analysis_id
                if stage == "awaiting_review":
                    rid = self.repo.resolve_reference(URL)
                    hist = ReviewService(self.repo).history(rid)
                    return hist[-1]["review_id"] if hist else None
                if stage == "completed":
                    rid = self.repo.resolve_reference(URL)
                    return export_reference(ReviewService(self.repo).reviewed_document(rid), self.stage)["path"]
            return run
        return {s: h(s) for s in STAGES}

    def executor(self, msg):
        if not self.conn.execute("SELECT 1 FROM videos").fetchone():
            self.conn.execute("INSERT INTO videos(video_pk, content_sha256, duration_s, created_at) VALUES (1, ?, 24.0, 'e2e')", (sha("demo-video"),))
        r = Pipeline(self.conn, self.handlers(), owner="gateway-1").run(1)
        state = r.state if r.state in STAGES + ("busy",) else "failed"
        return build_result(msg["mission_id"], state, executed=r.executed, skipped=r.skipped,
                            error_code="TRANSIENT" if state == "failed" else None, error_message=r.error)

    def mission(self, stages, url=URL):
        m = {"schema_version": MISSION_SCHEMA, "reference": {"platform": "instagram", "url": url}, "requested_stages": stages,
             "artifacts": [{"kind": "srt", "sha256": sha(D.SRT), "uri": "missions/SYNTHdemo01/transcricao.srt"}],
             "requested_by": "n8n:e2e", "created_at": "2026-10-18T00:00:00Z"}
        m["mission_id"] = compute_mission_id(m)
        return json.dumps(m).encode()

    def send(self, gw, body):
        return gw.receive(body, sign(body, SECRET))

    def test_crash_resend_alias_review_and_completion(self):
        gw = MissionGateway(self.conn, self.executor, SECRET)
        first = self.mission(["evidence_normalized", "classified", "awaiting_review"])

        self.crash_at = "classified"
        with self.assertRaises(KeyboardInterrupt):
            self.send(gw, first)                                     # 1ª entrega: cai no meio da classificação
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM analyses").fetchone()[0], 0)

        self.calls.clear()
        r = self.send(gw, first)                                     # n8n reenvia a mesma missão
        self.assertEqual(r["state"], "awaiting_review")
        self.assertEqual(self.calls[0], "classified")                # retoma na etapa interrompida
        self.assertNotIn("media_available", self.calls)

        self.calls.clear()
        again = self.send(gw, self.mission(["evidence_normalized", "classified", "awaiting_review"],
                                           url="https://m.instagram.com/p/SYNTHdemo01/?igsh=x"))
        self.assertTrue(again["replayed"])                           # outra URL da mesma publicação = mesma missão
        self.assertEqual(self.calls, [])

        rid = self.repo.resolve_reference(URL)
        self.assertEqual([h["reference_id"] for h in search(self.conn, Query(tool="CapCut", tool_visual_only=True)).items], [rid])
        ReviewService(self.repo).accept_category(rid, "demonstracao_ferramenta", "human:e2e", "nome legível e interface no frame")

        done = self.send(gw, self.mission(["completed"]))
        self.assertEqual(done["state"], "completed")
        note = Path(self.conn.execute("SELECT output_ref FROM processing_state WHERE stage = 'completed'").fetchone()[0])
        before = note.read_text(encoding="utf-8")
        self.assertIn("accepted", before)

        self.calls.clear()
        self.assertTrue(self.send(gw, self.mission(["completed"]))["replayed"])
        self.assertEqual(self.calls, [])
        self.assertEqual(note.read_text(encoding="utf-8"), before)

        counts = {t: self.conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("refs", "analyses", "reviews", "missions")}
        self.assertEqual(counts, {"refs": 1, "analyses": 1, "reviews": 1, "missions": 2})
        self.assertEqual({r[0] for r in self.conn.execute("SELECT status FROM processing_state")}, {"done"})
        self.assertEqual(self.conn.execute("PRAGMA integrity_check").fetchone()[0], "ok")
        self.assertEqual(self.conn.execute("PRAGMA foreign_key_check").fetchall(), [])
        self.assertEqual([p.name for p in self.stage.iterdir() if p.name.startswith(".ii_tmp_")], [])


if __name__ == "__main__":
    unittest.main()

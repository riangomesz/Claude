import unittest

from tests import _helpers  # noqa: F401
from ii_mm.db.migrations import open_database
from ii_mm.pipeline import STAGES, Pipeline


class Calls:
    def __init__(self):
        self.log = []
        self.outputs = {s: f"{s}:v1" for s in STAGES}
        self.fail = {}
        self.interrupt = set()
        self.review_done = False

    def handlers(self):
        def make(stage):
            def h(ctx):
                self.log.append((stage, ctx.attempt))
                if stage in self.interrupt:
                    self.interrupt.discard(stage)
                    raise KeyboardInterrupt
                if self.fail.get(stage, 0) > 0:
                    self.fail[stage] -= 1
                    raise RuntimeError(f"falha em {stage}")
                if stage == "awaiting_review" and not self.review_done:
                    return None
                return self.outputs[stage]
            return h
        return {s: make(s) for s in STAGES}


class PipelineTest(unittest.TestCase):
    def setUp(self):
        self.conn = open_database()
        self.addCleanup(self.conn.close)
        self.conn.execute("INSERT INTO videos(video_pk, duration_s, created_at) VALUES (1, 10, 'x')")
        self.calls = Calls()
        self.p = Pipeline(self.conn, self.calls.handlers())

    def stages_run(self):
        return [s for s, _ in self.calls.log]

    def test_stops_at_review_then_completes(self):
        r = self.p.run(1)
        self.assertEqual(r.state, "awaiting_review")
        self.assertEqual(r.executed, list(STAGES[:8]))
        self.calls.log.clear()
        self.calls.review_done = True
        r = self.p.run(1)
        self.assertEqual(r.state, "completed")
        self.assertEqual(self.stages_run(), ["awaiting_review", "completed"])

    def test_completed_run_is_not_repeated(self):
        self.calls.review_done = True
        self.p.run(1)
        self.calls.log.clear()
        r = self.p.run(1)
        self.assertEqual(self.stages_run(), [])
        self.assertEqual(r.skipped, list(STAGES))

    def test_interruption_resumes_at_same_stage(self):
        self.calls.review_done = True
        self.calls.interrupt = {"visual_processed"}
        with self.assertRaises(KeyboardInterrupt):
            self.p.run(1)
        self.assertEqual(self.p.state(1)["visual_processed"]["status"], "running")
        self.calls.log.clear()
        r = self.p.run(1)
        self.assertEqual(r.state, "completed")
        self.assertEqual(self.calls.log[0], ("visual_processed", 2))
        self.assertNotIn("media_available", self.stages_run())

    def test_failure_retries_until_limit(self):
        self.calls.fail = {"audio_processed": 5}
        for expected_attempt in (1, 2, 3):
            r = self.p.run(1)
            self.assertEqual(r.state, "failed")
            self.assertEqual(self.p.state(1)["audio_processed"]["attempt"], expected_attempt)
        self.calls.log.clear()
        r = self.p.run(1)
        self.assertIn("limite", r.error)
        self.assertEqual(self.stages_run(), [])

    def test_transient_failure_recovers(self):
        self.calls.fail = {"classified": 1}
        self.calls.review_done = True
        self.assertEqual(self.p.run(1).state, "failed")
        self.assertIn("RuntimeError", self.p.state(1)["classified"]["error"])
        r = self.p.run(1)
        self.assertEqual(r.state, "completed")
        self.assertEqual(r.executed[0], "classified")

    def test_upstream_change_reruns_downstream_only(self):
        self.calls.review_done = True
        self.p.run(1)
        self.calls.log.clear()
        self.calls.outputs["audio_processed"] = "audio_processed:v2"
        self.p.run(1, force={"audio_processed"})
        self.assertEqual(self.stages_run(), list(STAGES[STAGES.index("audio_processed"):]))

    def test_same_output_after_forced_rerun_keeps_downstream(self):
        self.calls.review_done = True
        self.p.run(1)
        self.calls.log.clear()
        self.p.run(1, force={"classified"})
        self.assertEqual(self.stages_run()[0], "classified")
        self.assertNotIn("metadata_extracted", self.stages_run())

    def test_handler_without_output_fails(self):
        self.calls.outputs["metadata_extracted"] = None
        r = self.p.run(1)
        self.assertEqual(r.state, "failed")
        self.assertIn("sem saída", r.error)

    def test_configuration_errors(self):
        with self.assertRaises(ValueError):
            Pipeline(self.conn, {"discovered": lambda c: "x"})
        with self.assertRaises(ValueError):
            self.p.run(1, force={"inexistente"})

    def test_videos_are_independent(self):
        self.conn.execute("INSERT INTO videos(video_pk, duration_s, created_at) VALUES (2, 10, 'x')")
        self.calls.review_done = True
        self.p.run(1)
        self.calls.log.clear()
        self.p.run(2)
        self.assertEqual(self.stages_run(), list(STAGES))


if __name__ == "__main__":
    unittest.main()

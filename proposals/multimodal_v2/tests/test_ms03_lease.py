"""Missão Suprema 03, Etapa 13: etapa mais longa que o lease precisa renovar a posse (heartbeat)."""
import tempfile
import unittest
from pathlib import Path

from tests import _helpers  # noqa: F401
from ii_mm.db.migrations import open_database
from ii_mm.pipeline import STAGES, Pipeline


class LeaseHeartbeatTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        db = Path(self.tmp.name) / "hb.sqlite"
        self.a, self.b = open_database(db), open_database(db)
        self.addCleanup(self.a.close); self.addCleanup(self.b.close)
        self.a.execute("INSERT INTO videos(video_pk, duration_s, created_at) VALUES (1, 10, 'x')")
        self.now = [1000.0]
        self.log = []

    def runner(self, conn, who, slow_stage=None, heartbeat=False, other=None):
        def make(s):
            def h(ctx):
                self.log.append((who, s))
                if s == slow_stage:
                    for _ in range(3):                    # etapa longa: 3 × 300 s > lease de 600 s
                        self.now[0] += 300
                        if heartbeat:
                            ctx.heartbeat()
                        if other is not None:
                            self.reports.append(other.run(1))
                return f"{s}:{who}"
            return h
        return Pipeline(conn, {s: make(s) for s in STAGES}, owner=who, lease_s=600, clock=lambda: self.now[0])

    def test_long_stage_with_heartbeat_is_never_stolen(self):
        self.reports = []
        pb = self.runner(self.b, "B")
        pa = self.runner(self.a, "A", slow_stage="audio_processed", heartbeat=True, other=pb)
        ra = pa.run(1)
        self.assertEqual(len(self.reports), 3)
        self.assertTrue(all(r.state == "busy" for r in self.reports), [r.state for r in self.reports])
        self.assertFalse([s for w, s in self.log if w == "B"])
        self.assertEqual(ra.state, "completed")

    def test_without_heartbeat_the_lease_expires_mid_stage(self):
        """Documenta o comportamento: sem heartbeat, etapa > lease pode ser assumida por outro executor."""
        self.reports = []
        pb = self.runner(self.b, "B")
        pa = self.runner(self.a, "A", slow_stage="audio_processed", heartbeat=False, other=pb)
        ra = pa.run(1)
        self.assertIn(("B", "audio_processed"), self.log)
        # A terminou depois de perder a posse: não pode sobrescrever o estado gravado por B
        self.assertEqual(ra.state, "failed")
        self.assertIn("posse", ra.error)
        row = self.a.execute("SELECT owner FROM processing_state WHERE video_pk = 1 AND stage = 'audio_processed'").fetchone()
        self.assertEqual(row["owner"], "B")

    def test_heartbeat_fails_loudly_if_ownership_was_lost(self):
        from ii_mm.pipeline import LeaseLost
        pb = self.runner(self.b, "B")
        state = {}

        def steal_then_beat(ctx):
            self.now[0] += 700                                # lease expira…
            pb.run(1)                                         # …B assume a etapa
            ctx.heartbeat()                                   # A percebe que perdeu a posse
            return "nunca"
        handlers = {s: (steal_then_beat if s == "media_available" else (lambda s: lambda ctx: f"{s}:A")(s)) for s in STAGES}
        pa = Pipeline(self.a, handlers, owner="A", lease_s=600, clock=lambda: self.now[0])
        r = pa.run(1)
        self.assertEqual(r.state, "failed")
        self.assertIn("posse", r.error)


if __name__ == "__main__":
    unittest.main()

"""Tarefa 10: registro de artefatos (caminho seguro, versões, integridade, parciais, limpeza controlada)."""
import os
import tempfile
import unittest
from pathlib import Path

from tests._util import TempEngine
from ii_be import artifacts as A
from ii_be.errors import DependencyMissing, InvalidInput
from ii_be.synthetic import fake_video, seed_media_reference


class SafePathTest(unittest.TestCase):
    def test_dangerous_paths_are_refused(self):
        for bad in ("../fora.mp4", "a/../../b", "/etc/passwd", "C:/Windows/win.ini", "c:\\x\\y", "\\\\srv\\c$\\x", "media/v.mp4:ads",
                    "media/CON", "media/nota.", "", "media//x", "./x", "file:///etc/passwd", "a\nb", "x" * 300):
            with self.assertRaises(InvalidInput, msg=bad):
                A.safe_relpath(bad)
        self.assertEqual(A.safe_relpath("media\\sub\\v.mp4"), "media/sub/v.mp4")

    def test_symlink_escaping_the_root_is_refused(self):
        with tempfile.TemporaryDirectory() as t:
            store = A.ArtifactStore.create(Path(t) / "store")
            outside = Path(t) / "segredo.txt"
            outside.write_text("privado", encoding="utf-8")
            try:
                os.symlink(outside, store.root / "atalho.txt")
            except (OSError, NotImplementedError):
                self.skipTest("sem permissão para criar symlink neste sistema")
            with self.assertRaises(InvalidInput):
                store.inspect("atalho.txt")

    def test_store_never_adopts_an_unmanaged_folder(self):
        with tempfile.TemporaryDirectory() as t:
            alheia = Path(t) / "alheia"
            alheia.mkdir()
            (alheia / "importante.txt").write_text("x", encoding="utf-8")
            with self.assertRaises(InvalidInput):
                A.ArtifactStore.create(alheia)
            with self.assertRaises(InvalidInput):
                A.ArtifactStore(alheia)
            self.assertTrue((alheia / "importante.txt").exists())


class RegistryTest(unittest.TestCase):
    def test_versions_idempotence_and_corruption(self):
        with TempEngine(memory=True) as t:
            e = t.engine
            s = seed_media_reference(e, "https://www.instagram.com/reel/SYNTHart01/", "art01")
            ref = s["ingest"].reference_id
            again = e.register_artifact(ref, "srt", "tools/art01/srt.srt", origin="tool:srt")
            self.assertFalse(again["new"])                                # mesmo conteúdo: idempotente
            e.store.write_bytes("tools/art01/srt2.srt", b"1\n00:00:00,000 --> 00:00:01,000\noutro\n")
            v2 = e.register_artifact(ref, "srt", "tools/art01/srt2.srt", origin="tool:srt")
            self.assertEqual(v2["version"], 2)
            states = [r[0] for r in e.conn.execute("SELECT state FROM be_artifacts WHERE reference_id=? AND kind='srt' ORDER BY version", (ref,))]
            self.assertEqual(states, ["superseded", "verified"])
            bad = e.register_artifact(ref, "ffprobe", "tools/art01/ffprobe.json", origin="tool:ffprobe", expected_sha256="0" * 64)
            self.assertEqual(bad["state"], "corrupt")
            self.assertEqual(A.current(e.conn, ref, "ffprobe")["version"], 1)  # versão boa continua corrente

    def test_file_changed_after_registration_is_detected_at_use_time(self):
        with TempEngine() as t:
            e = t.engine
            s = seed_media_reference(e, "https://www.instagram.com/reel/SYNTHart02/", "art02")
            ref = s["ingest"].reference_id
            e.store.write_bytes(s["video_relpath"], fake_video("adulterado"))
            done = e.run()
            acquire = [d for d in done if d["stage"] == "acquire"][0]
            self.assertEqual(acquire["outcome"], "waiting_dependency")
            self.assertEqual(A.latest(e.conn, ref, "video")["state"], "corrupt")
            self.assertEqual(A.media_state(e.conn, ref), "corrupt")
            self.assertEqual(e.conn.execute("SELECT COUNT(*) FROM analyses").fetchone()[0], 0)   # nada classificado com mídia divergente

    def test_missing_and_partial(self):
        with TempEngine(memory=True) as t:
            e = t.engine
            r = e.ingest({"schema_version": "ii.be.ingest.v1", "source_kind": "manual", "url": "https://www.instagram.com/reel/SYNTHart03/"})
            miss = e.register_artifact(r.reference_id, "srt", "tools/nao_existe.srt", origin="tool:srt")
            self.assertEqual(miss["state"], "missing")
            e.store.write_bytes("tools/v.mp4", fake_video("p", 500))
            part = e.register_artifact(r.reference_id, "video", "tools/v.mp4", origin="tool:download", expected_size=4096)
            self.assertEqual(part["state"], "partial")
            self.assertEqual(e.conn.execute("SELECT COUNT(*) FROM be_outbox WHERE type='media.available'").fetchone()[0], 0)

    def test_cleanup_only_touches_temp_artifacts_inside_the_managed_root(self):
        with TempEngine(memory=True) as t:
            e = t.engine
            s = seed_media_reference(e, "https://www.instagram.com/reel/SYNTHart04/", "art04")
            ref = s["ingest"].reference_id
            e.store.write_bytes("tmp/intermediario.bin", b"temporario")
            e.register_artifact(ref, "temp", "tmp/intermediario.bin", origin="tool:x", temp=True)
            removed = A.cleanup_temp(e.conn, e.store, "2026-01-01T00:00:00+00:00")
            self.assertEqual(removed, ["tmp/intermediario.bin"])
            self.assertTrue(e.store.path(s["video_relpath"]).is_file())           # mídia intocada
            self.assertTrue(e.store.path("tools/art04/srt.srt").is_file())
            self.assertEqual(A.latest(e.conn, ref, "temp")["state"], "missing")   # registro preservado


if __name__ == "__main__":
    unittest.main()

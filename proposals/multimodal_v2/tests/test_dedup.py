import tempfile
import unittest
from pathlib import Path

from tests import _helpers  # noqa: F401
from ii_mm.dedup import IdentityError, analysis_input_hash, canonical_reference_key, file_sha256, parse_reference
from ii_mm.synthetic import make_reference


class CanonicalKeyTest(unittest.TestCase):
    def test_instagram_url_variants_collapse(self):
        variants = ["https://www.instagram.com/reel/SYNTHabc12/", "instagram.com/reels/SYNTHabc12",
                    "https://m.instagram.com/p/SYNTHabc12/?igsh=xyz&utm_source=ig", "http://instagram.com/autor/reel/SYNTHabc12/",
                    "https://www.instagram.com/tv/SYNTHabc12"]
        self.assertEqual({canonical_reference_key(v) for v in variants}, {"instagram:SYNTHabc12"})

    def test_shortcode_case_is_preserved(self):
        self.assertNotEqual(canonical_reference_key("https://instagram.com/reel/SYNTHAbC12/"),
                            canonical_reference_key("https://instagram.com/reel/synthabc12/"))

    def test_youtube_and_tiktok(self):
        yt = {canonical_reference_key(u) for u in ("https://youtu.be/SYNTH12345", "https://www.youtube.com/watch?v=SYNTH12345&t=3",
                                                     "https://youtube.com/shorts/SYNTH12345")}
        self.assertEqual(yt, {"youtube:SYNTH12345"})
        self.assertEqual(canonical_reference_key("https://www.tiktok.com/@a/video/99990000000001?lang=pt"), "tiktok:99990000000001")

    def test_bare_ids_need_platform(self):
        self.assertEqual(canonical_reference_key("SYNTHabc12", platform_hint="instagram"), "instagram:SYNTHabc12")
        with self.assertRaises(IdentityError):
            canonical_reference_key("SYNTHabc12")

    def test_rejections(self):
        for bad in ("", "   ", "https://example.com/reel/x", "https://instagram.com/explore/", "https://youtube.com/watch?x=1",
                    "id com espaço", "https://instagram.com/reel/a/"):
            with self.assertRaises(IdentityError, msg=bad):
                parse_reference(bad, platform_hint="instagram")

    def test_platform_hint_conflict(self):
        with self.assertRaises(IdentityError):
            canonical_reference_key("https://youtu.be/SYNTH12345", platform_hint="instagram")


class HashesTest(unittest.TestCase):
    def test_input_hash_ignores_review_history_only(self):
        d = make_reference(1)
        h = analysis_input_hash(d)
        d["review_history"].append({"review_id": "r1"})
        d.setdefault("classification_runs", []).append({"x": 1})
        self.assertEqual(analysis_input_hash(d), h)
        d["evidence"][0]["claim"] += " (editado)"
        self.assertNotEqual(analysis_input_hash(d), h)

    def test_file_sha256(self):
        with tempfile.TemporaryDirectory() as t:
            p = Path(t) / "a.bin"
            p.write_bytes(b"abc")
            self.assertEqual(file_sha256(p), "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad")


if __name__ == "__main__":
    unittest.main()

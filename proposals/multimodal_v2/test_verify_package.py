import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from verify_package import verify  # noqa: E402


def build(tmp: Path, n=2, tamper=False, extra=False, escape=False):
    (tmp / "frames").mkdir()
    frames = []
    for i in range(n):
        data = f"conteudo-sintetico-{i}".encode()
        name = f"frames/p{i+1:02d}_x.jpg"
        (tmp / name).write_bytes(data + (b"X" if tamper and i == 0 else b""))
        frames.append({"pacote_id": f"P{i+1:02d}", "file": name, "sha256": hashlib.sha256(data).hexdigest()})
    if escape:
        frames[0]["file"] = "../fora.jpg"
    if extra:
        (tmp / "frames" / "solto.jpg").write_bytes(b"?")
    (tmp / "manifesto_pacote.json").write_text(json.dumps({"frames": frames}), encoding="utf-8")
    for n_ in ("perguntas_de_verificacao.json", "segmentos_transcricao.json", "cortes_detectados.json"):
        (tmp / n_).write_text("{}", encoding="utf-8")


class VerifyPackageTest(unittest.TestCase):
    def run_case(self, **kw):
        with tempfile.TemporaryDirectory() as d:
            build(Path(d), **kw)
            return verify(Path(d))

    def test_intact(self):
        self.assertEqual(self.run_case(), [])

    def test_tampered_frame(self):
        self.assertTrue(any("SHA-256 diverge" in p for p in self.run_case(tamper=True)))

    def test_unlisted_file(self):
        self.assertTrue(any("não listado" in p for p in self.run_case(extra=True)))

    def test_path_escape(self):
        self.assertTrue(any("fora do pacote" in p for p in self.run_case(escape=True)))

    def test_missing_manifest(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertIn("ausente: manifesto_pacote.json", verify(Path(d)))

    def test_too_many_frames(self):
        self.assertTrue(any("mais de 12" in p for p in self.run_case(n=13)))


if __name__ == "__main__":
    unittest.main()


class VerifyPackageMalformedTest(unittest.TestCase):
    """Defeitos B1/B2 da BASELINE_ATUAL.md."""

    def _pkg(self, d, manifest_text):
        p = Path(d)
        (p / "manifesto_pacote.json").write_text(manifest_text, encoding="utf-8")
        for n_ in ("perguntas_de_verificacao.json", "segmentos_transcricao.json", "cortes_detectados.json"):
            (p / n_).write_text("{}", encoding="utf-8")
        return p

    def test_invalid_json_is_reported_not_raised(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertTrue(any("ilegível" in x for x in verify(self._pkg(d, "["))))

    def test_non_object_manifest(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertTrue(any("fora do formato" in x for x in verify(self._pkg(d, "[1,2]"))))

    def test_frame_without_file_field(self):
        with tempfile.TemporaryDirectory() as d:
            probs = verify(self._pkg(d, json.dumps({"frames": [{"pacote_id": "P01"}]})))
            self.assertTrue(any("sem campo 'file'" in x for x in probs))
            self.assertFalse(any("fora do pacote" in x for x in probs))

    def test_duplicate_frame_entry(self):
        with tempfile.TemporaryDirectory() as d:
            p = self._pkg(d, "{}")
            (p / "frames").mkdir()
            (p / "frames" / "a.jpg").write_bytes(b"a")
            h = hashlib.sha256(b"a").hexdigest()
            entry = {"pacote_id": "P01", "file": "frames/a.jpg", "sha256": h}
            (p / "manifesto_pacote.json").write_text(json.dumps({"frames": [entry, dict(entry, pacote_id="P02")]}), encoding="utf-8")
            self.assertTrue(any("duplicidade" in x for x in verify(p)))

    def test_missing_frame_and_empty_manifest(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertIn("manifesto sem frames", verify(self._pkg(d, json.dumps({"frames": []}))))
        with tempfile.TemporaryDirectory() as d:
            probs = verify(self._pkg(d, json.dumps({"frames": [{"pacote_id": "P01", "file": "frames/x.jpg", "sha256": "0"}]})))
            self.assertTrue(any("frame ausente" in x for x in probs))

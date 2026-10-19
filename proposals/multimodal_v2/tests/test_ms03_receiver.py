"""Missão Suprema 03, Etapas 04 e 05: pacote autossuficiente e validador de recebimento adversarial.

Cada teste monta o zip determinístico num diretório temporário, extrai e adultera a CÓPIA extraída.
"""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

from tests import _helpers  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]
SELFTEST_ENV = "II_RC_AUTOTESTE"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


BUILD = _load(ROOT / "tools" / "build_handoff.py", "build_handoff_rc")
CHECK = _load(ROOT / "handoff" / "verificar_recebimento.py", "verificar_recebimento_rc")


class _Extracted:
    def __enter__(self):
        self._tmp = tempfile.TemporaryDirectory()
        t = Path(self._tmp.name)
        z = t / "rc.zip"
        self.zip_sha = BUILD.build_zip(z)
        with zipfile.ZipFile(z) as zf:
            zf.extractall(t / "x")
        self.proposals = next((t / "x").iterdir()) / "proposals"
        self.pkg = self.proposals / "multimodal_v2"
        self.manifest = self.pkg / "handoff" / "MANIFESTO_PACOTE.json"
        return self

    def __exit__(self, *exc):
        self._tmp.cleanup()

    def rewrite_manifest(self, change):
        man = json.loads(self.manifest.read_text(encoding="utf-8"))
        change(man)
        self.manifest.write_text(json.dumps(man), encoding="utf-8")


class ReceiverValidatorTest(unittest.TestCase):
    def test_clean_package_passes_and_reports_versions(self):
        with _Extracted() as e:
            rep = CHECK.check(e.proposals, BUILD.content_hash(e.manifest.read_bytes()))
            self.assertEqual((rep["integrity"], rep["environment"], rep.get("fatal")), ([], [], None))
            self.assertEqual(rep["rc_id"], "ii_mm-1.0.0-rc1")
            self.assertGreater(rep["files_checked"], 100)
            self.assertTrue(rep["sqlite"] and rep["python"])

    def test_zip_is_deterministic(self):
        with _Extracted() as a, _Extracted() as b:
            self.assertEqual(a.zip_sha, b.zip_sha)

    def test_missing_modified_and_extra_files(self):
        with _Extracted() as e:
            (e.pkg / "ii_mm" / "quality.py").unlink()
            with open(e.pkg / "ii_mm" / "contract.py", "a", encoding="utf-8") as f:
                f.write("\n# adulterado\n")
            (e.pkg / "tools" / "intruso.py").write_text("print('x')\n", encoding="utf-8")
            rep = CHECK.check(e.proposals)
            joined = "\n".join(rep["integrity"])
            self.assertIn("ausente: multimodal_v2/ii_mm/quality.py", joined)
            self.assertIn("modificado: multimodal_v2/ii_mm/contract.py", joined)
            self.assertIn("arquivo extra não listado: multimodal_v2/tools/intruso.py", joined)

    def test_crlf_checkout_is_not_a_modification_but_bytecode_is_only_a_warning(self):
        with _Extracted() as e:
            p = e.pkg / "ii_mm" / "contract.py"
            p.write_bytes(p.read_bytes().replace(b"\n", b"\r\n"))       # git com core.autocrlf=true
            cache = e.pkg / "ii_mm" / "__pycache__"
            cache.mkdir()
            (cache / "contract.cpython-313.pyc").write_bytes(b"\0")
            rep = CHECK.check(e.proposals)
            self.assertEqual(rep["integrity"], [])
            self.assertTrue(any("bytecode" in w for w in rep["warnings"]))

    def test_published_hash_mismatch_detects_manifest_forgery(self):
        with _Extracted() as e:
            published = BUILD.content_hash(e.manifest.read_bytes())
            target = e.pkg / "ii_mm" / "contract.py"
            target.write_text(target.read_text(encoding="utf-8") + "\n# adulterado\n", encoding="utf-8")
            e.rewrite_manifest(lambda m: [f.update(sha256_lf=BUILD.content_hash(target.read_bytes()))
                                          for f in m["files"] if f["path"].endswith("ii_mm/contract.py")])
            self.assertEqual(CHECK.check(e.proposals)["integrity"], [])       # manifesto forjado engana sem o hash
            rep = CHECK.check(e.proposals, published)
            self.assertTrue(any("hash publicado" in p for p in rep["integrity"]))

    def test_invalid_or_unknown_manifest_is_fatal(self):
        with _Extracted() as e:
            e.manifest.write_text("{quebrado", encoding="utf-8")
            self.assertIn("ilegível", CHECK.check(e.proposals)["fatal"])
            e.manifest.write_text(json.dumps({"schema_version": "ii.handoff_manifest.v9"}), encoding="utf-8")
            self.assertIn("não suportada", CHECK.check(e.proposals)["fatal"])
            e.manifest.write_text(json.dumps(["lista"]), encoding="utf-8")
            self.assertIn("não suportada", CHECK.check(e.proposals)["fatal"])

    def test_incompatible_versions_are_environment_errors(self):
        with _Extracted() as e:
            def bump(m):
                m["requirements"]["python_min"] = "9.0"
                m["requirements"]["sqlite_min"] = "99.0.0"
                m["rc_id"] = "versao-qualquer"
            e.rewrite_manifest(bump)
            rep = CHECK.check(e.proposals)
            self.assertTrue(any("Python" in p for p in rep["environment"]))
            self.assertTrue(any("SQLite" in p for p in rep["environment"]))
            self.assertTrue(any("rc_id inválido" in p for p in rep["integrity"]))

    def test_dangerous_paths_in_manifest(self):
        with _Extracted() as e:
            evil = ["../../fora.py", "C:/Windows/win.ini", "/etc/passwd", "multimodal_v2/CON.py", "multimodal_v2/a.py:ads",
                    "multimodal_v2/nota.", "multimodal_v2/" + "x" * 220, "multimodal_v2/II_MM/CONTRACT.PY"]
            e.rewrite_manifest(lambda m: m["files"].extend({"path": p, "sha256_lf": "0" * 64} for p in evil))
            joined = "\n".join(CHECK.check(e.proposals)["integrity"])
            for needle in ("contém '..'", "absoluto ou com unidade", "nome reservado", "caractere inválido",
                           "termina em espaço/ponto", "caracteres (>", "colisão de maiúsculas"):
                self.assertIn(needle, joined)

    def test_managed_dir_outside_package_is_refused_not_scanned(self):
        with _Extracted() as e:
            e.rewrite_manifest(lambda m: m["managed_dirs"].extend(["../..", "C:/"]))
            rep = CHECK.check(e.proposals)
            refused = [p for p in rep["integrity"] if p.startswith("pasta gerenciada recusada")]
            self.assertEqual(len(refused), 2)
            self.assertFalse(any("arquivo extra" in p for p in rep["integrity"]))

    def test_validator_does_not_write_anything(self):
        with _Extracted() as e:
            before = sorted((p.relative_to(e.proposals).as_posix(), p.stat().st_size) for p in e.proposals.rglob("*"))
            r = subprocess.run([sys.executable, "-I", "-B", str(e.pkg / "handoff" / "verificar_recebimento.py"), "--json"],
                               capture_output=True, text=True, encoding="utf-8", timeout=60)
            self.assertEqual(r.returncode, 0, r.stdout[-800:])
            after = sorted((p.relative_to(e.proposals).as_posix(), p.stat().st_size) for p in e.proposals.rglob("*"))
            self.assertEqual(before, after)


@unittest.skipIf(os.environ.get(SELFTEST_ENV), "já dentro do autoteste do pacote extraído")
class SelfContainedPackageTest(unittest.TestCase):
    """O zip extraído roda a própria suíte sem nada da árvore original (prova de que o pacote é autossuficiente)."""

    def test_extracted_package_runs_its_own_suite(self):
        with _Extracted() as e:
            env = {k: v for k, v in os.environ.items() if k != "PROJETO_MVP_DIR"}
            env.update({SELFTEST_ENV: "1", "PYTHONUTF8": "1"})
            r = subprocess.run([sys.executable, "-I", "-B", str(e.pkg / "run_tests.py")], cwd=str(e.pkg),
                               capture_output=True, text=True, encoding="utf-8", timeout=600, env=env)
            self.assertEqual(r.returncode, 0, r.stderr[-3000:])
            self.assertRegex(r.stderr, r"\nOK")
            leftovers = [p for p in e.proposals.rglob("*") if "__pycache__" in p.parts]
            self.assertEqual(leftovers, [], "a suíte gravou bytecode dentro do pacote")
            rep = CHECK.check(e.proposals)
            self.assertEqual(rep["integrity"], [], "a suíte alterou arquivos do pacote")


if __name__ == "__main__":
    unittest.main()

"""Missão Suprema 02, Etapa C: conexões SQLite (achado L1 confirmado) e isolamento das fixtures legadas."""
import gc
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path

from tests import _helpers

ROOT = Path(__file__).resolve().parents[1]
PROJETO = os.environ.get("PROJETO_MVP_DIR")  # só decide se roda; o código vem da cópia de _helpers.projeto_dir()


@contextmanager
def tracked_connections():
    """Substitui sqlite3.connect por uma fábrica que conta conexões vivas; desliga o GC cíclico para medir
    o que a contagem de referências libera de fato ao sair da função."""
    stats = {"alive": 0}

    class Tracked(sqlite3.Connection):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            stats["alive"] += 1

        def __del__(self):
            stats["alive"] -= 1

    real = sqlite3.connect
    gc.collect()
    sqlite3.connect = lambda *a, **k: real(*a, factory=Tracked, **k)
    gc.disable()
    try:
        yield stats
    finally:
        gc.enable()
        sqlite3.connect = real
        gc.collect()


def snapshot(root: Path):
    return sorted(str(p.relative_to(root)) for p in root.rglob("*") if ".git" not in p.parts and "__pycache__" not in p.parts)


class IiMmClosesItsConnectionsTest(unittest.TestCase):
    def test_full_demo_leaves_no_connection_alive(self):
        from ii_mm.demo import run_demo
        with tempfile.TemporaryDirectory() as t, tracked_connections() as stats:
            run_demo(Path(t))
            alive = stats["alive"]
        self.assertEqual(alive, 0, "o ii_mm deixou conexão SQLite viva após a demonstração")

    def test_shadow_reader_closes(self):
        from ii_mm.shadow import read_legacy_rows_readonly
        with tempfile.TemporaryDirectory() as t:
            db = Path(t) / "x.sqlite"
            c = sqlite3.connect(str(db)); c.execute("CREATE TABLE instagram_items (id TEXT)"); c.commit(); c.close()
            with tracked_connections() as stats:
                read_legacy_rows_readonly(db)
                alive = stats["alive"]
        self.assertEqual(alive, 0)


@unittest.skipUnless(PROJETO, "defina PROJETO_MVP_DIR para medir o legado")
class LegacyConnectionLeakTest(unittest.TestCase):
    """L1: `with sqlite3.connect(...) as c` não fecha; a conexão sobrevive ao retorno até o GC de ciclos."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.projeto = _helpers.projeto_dir()
        cls.patched = Path(cls.tmp.name) / "patched_mvp"
        spec = __import__("importlib.util").util.spec_from_file_location("mkpatch", ROOT / "tools" / "make_legacy_close_patch.py")
        mod = __import__("importlib.util").util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        cls.transformed, cls.diff = mod.build(cls.projeto, cls.patched)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def _measure_in_subprocess(self, code_root: Path) -> str:
        """Roda num processo novo para não misturar módulos `core` do original e da cópia corrigida."""
        import subprocess
        script = f"""
import sys, gc, sqlite3, tempfile
sys.path.insert(0, {str(ROOT)!r}); sys.path.insert(0, {str(code_root)!r})
from pathlib import Path
from ii_mm.db.legacy_fixture import build_legacy_catalog
from tests.test_ms02_sqlite import tracked_connections
with tempfile.TemporaryDirectory() as t:
    db = Path(t) / "leak.sqlite"
    build_legacy_catalog(db, Path({str(code_root)!r}))
    from core import curation, trash_manager
    with tracked_connections() as s:
        curation.run_preliminary_curation(db)
        curation.get_curation_summary(db)
        trash_manager.list_trash_items(db_path=db)
        print(s["alive"])
"""
        out = subprocess.run([sys.executable, "-W", "ignore", "-c", script], capture_output=True, text=True, encoding="utf-8", timeout=120,
                             env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
        self.assertEqual(out.returncode, 0, out.stderr[-800:])
        return out.stdout.strip().splitlines()[-1]

    def test_original_legacy_leaks_until_gc(self):
        self.assertGreater(int(self._measure_in_subprocess(self.projeto)), 0)

    def test_patched_copy_closes_everything(self):
        self.assertEqual(self.transformed, 25)
        self.assertEqual(int(self._measure_in_subprocess(self.patched)), 0)

    def test_committed_patch_matches_generator(self):
        committed = (ROOT / "patches" / "legacy_close_sqlite_connections.diff").read_text(encoding="utf-8")
        self.assertEqual(committed, self.diff, "patch versionado desatualizado em relação ao clone")


@unittest.skipUnless(PROJETO, "defina PROJETO_MVP_DIR para verificar o isolamento das fixtures")
class LegacyFixtureIsolationTest(unittest.TestCase):
    def test_fixture_does_not_create_anything_inside_the_project_tree(self):
        """Roda a fixture sobre uma CÓPIA do clone, em processo novo (independe da ordem dos testes)."""
        import subprocess
        with tempfile.TemporaryDirectory() as t:
            copy = Path(t) / "mvp_copia"
            shutil.copytree(_helpers.projeto_dir(), copy, ignore=shutil.ignore_patterns(".git", "*.bin", "__pycache__"))
            before = snapshot(copy)
            script = (f"import sys; sys.path.insert(0, {str(ROOT)!r}); sys.path.insert(0, {str(copy)!r});"
                      f"from pathlib import Path; from ii_mm.db.legacy_fixture import build_legacy_catalog;"
                      f"build_legacy_catalog(Path({str(Path(t) / 'iso.sqlite')!r}), Path({str(copy)!r}))")
            out = subprocess.run([sys.executable, "-W", "ignore", "-c", script], capture_output=True, text=True, encoding="utf-8", timeout=120,
                                 env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
            self.assertEqual(out.returncode, 0, out.stderr[-800:])
            created = sorted(set(snapshot(copy)) - set(before))
        self.assertEqual(created, [], "a fixture criou caminhos dentro da árvore do projeto")


if __name__ == "__main__":
    unittest.main()

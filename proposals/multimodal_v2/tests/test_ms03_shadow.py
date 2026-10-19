"""Missão Suprema 03, Etapa 08: modo sombra adversarial, snapshot somente leitura e exportação para revisão."""
import csv
import hashlib
import io
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path

from tests import _helpers  # noqa: F401
from ii_mm.shadow import export_review_csv, render_markdown, run_shadow, snapshot_readonly

EVIL = {"id": "SYNTHinj", "caption": 'tutorial <img src="https://evil.example/t.gif"> ![x](https://evil.example/p.png) [[Senhas]]',
        "editorial_category": '=HYPERLINK("https://evil.example","clique")', "editorial_category_source": "sugestao_automatica",
        "curation_rule": "+cmd|' /C calc'!A0"}


def make_catalog(path: Path, rows=3):
    c = sqlite3.connect(str(path))
    try:
        c.execute("CREATE TABLE instagram_items (id TEXT PRIMARY KEY, caption TEXT, editorial_category TEXT, editorial_category_source TEXT, triage_decision TEXT)")
        c.executemany("INSERT INTO instagram_items VALUES (?,?,?,?,?)",
                      [(f"SYNTHsnap{i}", "tutorial passo a passo", "Criativo", "human", "manter") for i in range(rows)])
        c.commit()
    finally:
        c.close()


class D3ReportInjectionTest(unittest.TestCase):
    def test_markdown_report_neutralizes_external_text(self):
        md = render_markdown(run_shadow([EVIL]))
        for bad in ("<img", "![x](", "[[Senhas]]"):
            self.assertNotIn(bad, md)

    def test_csv_export_neutralizes_formulas_and_keeps_text(self):
        with tempfile.TemporaryDirectory() as t:
            out = Path(t) / "revisao.csv"
            export_review_csv(run_shadow([EVIL]), out)
            rows = list(csv.DictReader(io.StringIO(out.read_text(encoding="utf-8-sig"))))
        self.assertEqual(len(rows), 1)
        for v in rows[0].values():
            self.assertFalse(v[:1] in ("=", "+", "-", "@", "\t", "\r"), v)
        self.assertIn("HYPERLINK", rows[0]["legado_rotulo"])
        self.assertEqual(rows[0]["decisao_revisor"], "")
        self.assertIn("comentario_revisor", rows[0])


class SnapshotReadOnlyTest(unittest.TestCase):
    def test_snapshot_is_consistent_and_source_untouched(self):
        with tempfile.TemporaryDirectory() as t:
            src, dst = Path(t) / "catalogo_origem.sqlite", Path(t) / "trabalho" / "snapshot.sqlite"
            make_catalog(src, rows=5)
            before = hashlib.sha256(src.read_bytes()).hexdigest()
            info = snapshot_readonly(src, dst)
            self.assertEqual(info["rows_instagram_items"], 5)
            self.assertEqual(hashlib.sha256(src.read_bytes()).hexdigest(), before)
            self.assertEqual(sorted(p.name for p in src.parent.iterdir() if p.is_file()), ["catalogo_origem.sqlite"])

    def test_snapshot_while_another_connection_holds_a_write_lock(self):
        with tempfile.TemporaryDirectory() as t:
            src, dst = Path(t) / "vivo.sqlite", Path(t) / "snap.sqlite"
            make_catalog(src, rows=2)
            writer = sqlite3.connect(str(src), isolation_level=None)
            try:
                writer.execute("BEGIN IMMEDIATE")              # pipeline vivo com transação de escrita aberta
                writer.execute("INSERT INTO instagram_items (id) VALUES ('SYNTHnovo')")
                info = snapshot_readonly(src, dst)            # leitura não espera o commit
                self.assertEqual(info["rows_instagram_items"], 2)   # vê só o que estava confirmado
                writer.execute("COMMIT")
            finally:
                writer.close()

    def test_writer_can_commit_while_snapshot_is_in_progress(self):
        """D-RC5: a cópia em passo único segurava o bloqueio compartilhado durante todo o backup (1,7 s para
        139 MB medidos); no journal padrão do legado, um escritor com timeout de 5 s falharia num catálogo grande."""
        with tempfile.TemporaryDirectory() as t:
            src, dst = Path(t) / "vivo.sqlite", Path(t) / "snap.sqlite"
            c = sqlite3.connect(str(src))
            try:
                c.execute("CREATE TABLE instagram_items (id TEXT PRIMARY KEY, caption TEXT)")
                c.executemany("INSERT INTO instagram_items VALUES (?, ?)", [(f"SYNTHbig{i:04d}", "x" * 2000) for i in range(200)])
                c.commit()
            finally:
                c.close()
            commits = []

            def during(remaining, total):
                if remaining > 0 and not commits:
                    w = sqlite3.connect(str(src), timeout=0, isolation_level=None)  # timeout 0: falha se houver bloqueio
                    try:
                        w.execute("BEGIN IMMEDIATE")
                        w.execute("INSERT INTO instagram_items (id) VALUES ('SYNTHdurante')")
                        w.execute("COMMIT")
                        commits.append(remaining)
                    finally:
                        w.close()

            info = snapshot_readonly(src, dst, pages=8, on_step=during)
            self.assertEqual(len(commits), 1, "o escritor não conseguiu gravar no meio da cópia")
            self.assertEqual(info["rows_instagram_items"], 201)  # a cópia recomeça e termina consistente

    def test_snapshot_gives_up_instead_of_waiting_forever_on_exclusive_lock(self):
        with tempfile.TemporaryDirectory() as t:
            src, dst = Path(t) / "vivo.sqlite", Path(t) / "snap.sqlite"
            make_catalog(src, rows=2)
            writer = sqlite3.connect(str(src), isolation_level=None)
            try:
                writer.execute("BEGIN EXCLUSIVE")
                with self.assertRaises(TimeoutError):
                    snapshot_readonly(src, dst, max_seconds=0.3)
                self.assertFalse(dst.exists(), "snapshot parcial deixado para trás")
                writer.execute("INSERT INTO instagram_items (id) VALUES ('SYNTHdepois')")
                writer.execute("COMMIT")
            finally:
                writer.close()

    def test_snapshot_refuses_bad_paths(self):
        with tempfile.TemporaryDirectory() as t:
            src = Path(t) / "a.sqlite"
            make_catalog(src)
            with self.assertRaises(FileNotFoundError):
                snapshot_readonly(Path(t) / "nao_existe.sqlite", Path(t) / "s.sqlite")
            with self.assertRaises(ValueError):
                snapshot_readonly(src, src)
            existing = Path(t) / "existente.sqlite"; existing.write_bytes(b"x")
            with self.assertRaises(FileExistsError):
                snapshot_readonly(src, existing)

    def test_human_decisions_survive_shadow_run_unchanged(self):
        with tempfile.TemporaryDirectory() as t:
            src = Path(t) / "c.sqlite"
            make_catalog(src, rows=4)
            from ii_mm.shadow import read_legacy_rows_readonly
            rows = read_legacy_rows_readonly(src)
            run_shadow(rows)
            c = sqlite3.connect(f"{src.as_uri()}?mode=ro", uri=True)
            try:
                self.assertEqual({r[0] for r in c.execute("SELECT triage_decision FROM instagram_items")}, {"manter"})
                self.assertEqual({r[0] for r in c.execute("SELECT editorial_category_source FROM instagram_items")}, {"human"})
            finally:
                c.close()


if __name__ == "__main__":
    unittest.main()

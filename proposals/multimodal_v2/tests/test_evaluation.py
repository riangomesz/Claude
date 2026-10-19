"""Fluxo de avaliação humana. Os rótulos usados aqui são SINTÉTICOS e servem só para conferir a matemática."""
import csv
import tempfile
import unittest
from pathlib import Path

from tests import _helpers  # noqa: F401
from ii_mm.evaluation import LabelError, agreement_report, export_labeling_sheet, load_labels, predictions_from_shadow, select_sample
from ii_mm.evidence_rules import CATEGORIES
from ii_mm.shadow import run_shadow


def synthetic_rows(n):
    texts = ["tutorial passo a passo", "link na bio com desconto", "motion design no after effects", "bom dia", "n8n workflow"]
    return [{"id": f"SYNTHev{i:03d}", "caption": texts[i % len(texts)], "url": f"https://www.instagram.com/reel/SYNTHev{i:03d}/"} for i in range(n)]


class SampleTest(unittest.TestCase):
    def test_stratified_reproducible_and_bounded(self):
        rep = run_shadow(synthetic_rows(120))
        a, b = select_sample(rep["items"], n=40), select_sample(rep["items"], n=40)
        self.assertEqual(a["selected"], b["selected"])
        self.assertEqual(len(a["selected"]), 40)
        self.assertEqual(len(set(a["selected"])), 40)
        self.assertGreaterEqual(len({i["kind"] for i in a["items"]}), 2)
        with self.assertRaises(ValueError):
            select_sample(rep["items"], n=10)

    def test_small_pool_warns(self):
        s = select_sample(run_shadow(synthetic_rows(12))["items"], n=30)
        self.assertEqual(len(s["selected"]), 12)
        self.assertTrue(s["warnings"])


class SheetTest(unittest.TestCase):
    def test_blind_sheet_hides_suggestions_and_neutralizes_cells(self):
        rows = synthetic_rows(35)
        rows[0]["caption"] = "=1+1 tutorial"
        rep = run_shadow(rows)
        s = select_sample(rep["items"], n=35)
        with tempfile.TemporaryDirectory() as t:
            p = Path(t) / "rotulos.csv"
            export_labeling_sheet(s, p, {r["id"]: r for r in rows})
            header = next(csv.reader(p.open(encoding="utf-8-sig")))
            text = p.read_text(encoding="utf-8-sig")
        self.assertNotIn("sugestao_nova", header)
        self.assertEqual(header[3:3 + len(CATEGORIES)], list(CATEGORIES))
        self.assertIn("'=1+1", text)


class LabelsAndAgreementTest(unittest.TestCase):
    def write(self, t, lines):
        p = Path(t) / "preenchida.csv"
        with p.open("w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow(["item_id", "url", "legenda", *CATEGORIES, "observacoes", "revisor", "data"])
            for item, cats, rev in lines:
                w.writerow([item, "", ""] + [cats.get(c, "") for c in CATEGORIES] + ["", rev, ""])
        return p

    def test_validation_errors(self):
        with tempfile.TemporaryDirectory() as t:
            p = self.write(t, [("SYNTHev001", {"tutorial": "talvez"}, "human:a"), ("SYNTHev002", {"tutorial": "1"}, ""),
                               ("SYNTHev003", {"tutorial": "1"}, "human:a"), ("SYNTHev003", {"tutorial": "0"}, "human:a")])
            with self.assertRaises(LabelError) as ctx:
                load_labels(p)
        msg = str(ctx.exception)
        for frag in ("inválidos", "revisor ausente", "duas vezes"):
            self.assertIn(frag, msg)

    def test_unreviewed_rows_are_excluded(self):
        with tempfile.TemporaryDirectory() as t:
            p = self.write(t, [("SYNTHev001", {"tutorial": "1"}, "human:a"), ("SYNTHev002", {}, "")])
            self.assertEqual(load_labels(p), {"SYNTHev001": {"tutorial"}})

    def test_counts_only_below_30_and_rates_from_30(self):
        labels = {"A": {"tutorial"}, "B": set(), "C": {"tutorial", "marketing_vendas"}}
        preds = {"novo": {"A": {"tutorial"}, "B": {"tutorial"}, "C": {"tutorial"}}}
        r = agreement_report(labels, preds)
        t = r["per_classifier"]["novo"]["por_categoria"]["tutorial"]
        self.assertEqual((t["concorda_presente"], t["falso_positivo"], t["falso_negativo"], t["concorda_ausente"]), (2, 1, 0, 0))
        self.assertNotIn("taxa_concordancia", t)
        self.assertIn("sem taxa", r["warning"])
        self.assertEqual(r["per_classifier"]["novo"]["itens_identicos_ao_humano"], 1)
        big = {f"I{i}": {"tutorial"} for i in range(30)}
        r30 = agreement_report(big, {"novo": {k: {"tutorial"} for k in big}})
        self.assertEqual(r30["per_classifier"]["novo"]["por_categoria"]["tutorial"]["taxa_concordancia"], 1.0)

    def test_predictions_from_shadow(self):
        preds = predictions_from_shadow(run_shadow(synthetic_rows(5)))
        self.assertEqual(set(preds), {"atual", "novo"})
        self.assertIn("tutorial", preds["novo"]["SYNTHev000"])


if __name__ == "__main__":
    unittest.main()


class EvaluationCliTest(unittest.TestCase):
    """tools/avaliacao.py sobre um modo sombra real (snapshot de catálogo sintético): amostra → planilha → concordância."""

    def test_end_to_end_from_shadow_snapshot(self):
        import io
        import json
        import sqlite3
        from contextlib import redirect_stdout
        from handoff import exemplo_uso
        from tools import avaliacao
        with tempfile.TemporaryDirectory() as t:
            t = Path(t)
            cat = t / "catalogo.sqlite"
            c = sqlite3.connect(str(cat))
            try:
                c.execute("CREATE TABLE instagram_items (id TEXT PRIMARY KEY, url TEXT, caption TEXT)")
                c.executemany("INSERT INTO instagram_items VALUES (?, ?, ?)", [(r["id"], r["url"], r["caption"]) for r in synthetic_rows(60)])
                c.commit()
            finally:
                c.close()
            sombra = t / "trabalho" / "sombra"
            with redirect_stdout(io.StringIO()):
                self.assertEqual(exemplo_uso.main(["--legacy-db", str(cat), "--out", str(sombra), "--limit", "60"]), 0)
                planilha = t / "trabalho" / "planilha.csv"
                self.assertEqual(avaliacao.main(["amostra", "--sombra", str(sombra), "--out", str(planilha), "--n", "30"]), 0)
                with self.assertRaises(SystemExit):  # nunca sobrescreve
                    avaliacao.main(["amostra", "--sombra", str(sombra), "--out", str(planilha), "--n", "30"])
            with open(planilha, encoding="utf-8-sig", newline="") as f:
                rows = list(csv.DictReader(f))
            self.assertEqual(len(rows), 30)
            self.assertTrue(all(r["url"].startswith("https://") and r["legenda"] for r in rows))  # veio do snapshot
            self.assertNotIn("sugestao_nova", rows[0])  # cega
            for r in rows:  # rótulo SINTÉTICO, só para exercitar o caminho
                for cat_name in CATEGORIES:
                    r[cat_name] = "1" if cat_name == CATEGORIES[0] else "0"
                r["revisor"] = "revisor_sintetico"
            with open(planilha, "w", encoding="utf-8-sig", newline="") as f:
                w = csv.DictWriter(f, fieldnames=list(rows[0]))
                w.writeheader()
                w.writerows(rows)
            out = t / "trabalho" / "concordancia.json"
            with redirect_stdout(io.StringIO()):
                self.assertEqual(avaliacao.main(["concordancia", "--sombra", str(sombra), "--rotulos", str(planilha), "--out", str(out)]), 0)
            rep = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(rep["n_labeled"], 30)
            self.assertEqual(set(rep["per_classifier"]), {"atual", "novo"})
            self.assertTrue((t / "trabalho" / "planilha.amostra.json").is_file())

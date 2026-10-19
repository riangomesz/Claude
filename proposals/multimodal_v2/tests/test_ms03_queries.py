"""Missão Suprema 03, Etapa 14: plano de TODAS as consultas de leitura e escrita de um fluxo real.

Em vez de benchmark (já em BENCHMARK.md para o catálogo), captura cada SQL executado ao gravar, reprocessar,
revisar e consultar o histórico, e confere com EXPLAIN QUERY PLAN que nenhuma consulta varre uma tabela
que cresce com o catálogo. Ordenação temporária só é aceita onde o conjunto é limitado a uma referência.
"""
import copy
import re
import unittest

from tests import _helpers  # noqa: F401
from ii_mm.db.migrations import open_database
from ii_mm.db.repository import Repository
from ii_mm.review import ReviewService
from ii_mm.synthetic import make_reference

GROWING = {"refs", "ref_aliases", "videos", "ref_videos", "analyses", "evidence", "segments", "categories",
           "category_evidence", "tools", "techniques", "reviews", "review_state", "processing_state", "issues", "missions"}


def full_scans(conn, sql):
    """Linhas `SCAN` sobre tabelas que crescem, resolvendo apelidos (`FROM analyses a` aparece como `SCAN a`)."""
    alias = {a: t for t, a in re.findall(r"(?:FROM|JOIN)\s+(\w+)\s+(?:AS\s+)?(?!ON\b|USING\b|WHERE\b|JOIN\b|CROSS\b|LEFT\b|ORDER\b)(\w+)", sql, re.I)}
    out = []
    for line in (r[-1] for r in conn.execute("EXPLAIN QUERY PLAN " + sql)):
        m = re.match(r"SCAN (\w+)", line)
        if m and alias.get(m.group(1), m.group(1)) in GROWING and "COVERING INDEX" not in line:
            out.append(line)
    return out


class QueryPlanAuditTest(unittest.TestCase):
    def test_detector_catches_a_real_scan_even_through_an_alias(self):
        conn = open_database()
        self.addCleanup(conn.close)
        self.assertTrue(full_scans(conn, "SELECT a.analysis_id FROM analyses a WHERE a.classifier_version = 'x'"))
        self.assertEqual(full_scans(conn, "SELECT analysis_id FROM analyses WHERE analysis_id = 'x'"), [])

    def test_no_full_scan_on_growing_tables_in_save_review_and_history(self):
        conn = open_database()
        self.addCleanup(conn.close)
        repo, statements = Repository(conn), []
        docs = [make_reference(i) for i in range(30)]
        for d in docs:
            repo.save_analysis(d)
        conn.set_trace_callback(statements.append)
        changed = copy.deepcopy(docs[3])
        changed["x_reprocessado"] = True                      # nova entrada → nova análise, a anterior fica no histórico
        res = repo.save_analysis(changed)
        repo.save_analysis(changed)                           # reenvio idempotente
        rv = ReviewService(repo)
        cat = (changed.get("categories") or [{"category": "tutorial"}])[0]["category"]
        rv.accept_category(res.reference_id, cat, "human:revisor")
        rv.history(res.reference_id)
        rv.reviewed_document(res.reference_id)
        repo.current_analysis_id(res.reference_id)
        repo.analysis_history(res.video_pk)
        repo.references_for_video(res.video_pk)
        repo.resolve_reference(changed["reference"]["origin_url"])
        repo.open_issues(res.video_pk)
        conn.set_trace_callback(None)

        checked, problems = 0, []
        for sql in statements:
            if not re.match(r"\s*(SELECT|UPDATE|DELETE)", sql, re.I):
                continue
            checked += 1
            problems += [f"{line} <- {sql[:140]}" for line in full_scans(conn, sql)]
            temp = [r[-1] for r in conn.execute("EXPLAIN QUERY PLAN " + sql) if "TEMP B-TREE" in r[-1]]
            if temp:  # ordenação/UNION em memória só sobre o conjunto de UMA referência, UM vídeo ou UMA chave
                self.assertRegex(sql, r"(reference_id|video_pk|canonical_key|alias_key) = ", sql[:140])
        self.assertGreater(checked, 15)
        self.assertEqual(problems, [])


if __name__ == "__main__":
    unittest.main()

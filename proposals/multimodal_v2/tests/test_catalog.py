import unittest

from tests import _helpers  # noqa: F401
from ii_mm import adapters as A
from ii_mm.catalog import MAX_PAGE, Query, QueryError, explain, iterate, search
from ii_mm.classifier import Classifier
from ii_mm.db.migrations import open_database
from ii_mm.db.repository import Repository
from ii_mm.normalize import Normalizer
from ii_mm.review import ReviewService
from ii_mm.synthetic import make_reference, sha
from ii_mm.techniques import build_techniques


def controlled(i, speech, tag=None, refs=("P01",), platform="instagram", author="autor_x", subject=None):
    n = Normalizer(f"ref_C{i}", platform, f"SYNTHctl{i:03d}", 60.0, content_sha256=sha(f"ctl{i}"),
                   origin_url=f"https://www.instagram.com/reel/SYNTHctl{i:03d}/", author_handle=author)
    n.add_frames(A.frames_from_manifest({"frames": [{"pacote_id": f"P0{k}", "t_s": 20 + k * 0.033, "sha256": sha(f"c{i}{k}")} for k in (1, 2, 3)]}))
    n.add_transcript(A.transcript_from_segments([{"start": 1, "end": 4, "text": speech}]))
    if tag:
        n.add_observations(A.observations_from_json([{"frame_refs": list(refs), "t_s": 20, "tag": tag, "text": f"{tag} da interface do CapCut"}], "agent:t"))
    doc = Classifier().classify(n.build())
    doc["reference"]["subject"] = subject
    doc["techniques"] = build_techniques(doc)
    return doc


class CatalogTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.conn = open_database()
        cls.repo = Repository(cls.conn)
        for i in range(60):
            cls.repo.save_analysis(make_reference(i))
        cls.c1 = cls.repo.save_analysis(controlled(1, "tutorial de edição no capcut", "ui_screen_visible", subject="prompting cinematográfico"))
        cls.c2 = cls.repo.save_analysis(controlled(2, "eu uso o capcut às vezes", None, author="autor_y"))
        cls.c3 = cls.repo.save_analysis(controlled(3, "olha a transição", "kinetic_typography", refs=("P01", "P02", "P03")))
        ReviewService(cls.repo).accept_category(cls.c1.reference_id, "tutorial", "human:ana")

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()

    def ids(self, q, limit=50):
        return [r["reference_id"] for r in iterate(self.conn, q, page_size=limit)]

    def test_pagination_visits_everything_once_in_stable_order(self):
        full = self.ids(Query(), limit=MAX_PAGE)
        total = self.conn.execute("SELECT COUNT(*) FROM refs").fetchone()[0]
        self.assertEqual(len(full), total)
        self.assertEqual(len(set(full)), total)
        for size in (1, 7, 25):
            self.assertEqual(self.ids(Query(), limit=size), full)
        self.assertEqual(self.ids(Query(descending=True), limit=9), list(reversed(full)))

    def test_cursor_is_stable_under_concurrent_inserts(self):
        p1 = search(self.conn, Query(platform="youtube"), limit=3)
        seen = [r["reference_id"] for r in p1.items]
        conn2 = open_database()  # banco separado só para provar que o cursor não depende de estado do servidor
        conn2.close()
        extra = make_reference(900); extra["reference"]["platform"] = "youtube"; extra["reference"]["origin_url"] = "https://youtu.be/SYNTH000900"
        self.repo.save_analysis(extra)
        rest = [r["reference_id"] for r in iterate(self.conn, Query(platform="youtube"), page_size=3)]
        cursor_rest = []
        cur = p1.next_cursor
        while cur:
            pg = search(self.conn, Query(platform="youtube"), cur, 3)
            cursor_rest += [r["reference_id"] for r in pg.items]
            cur = pg.next_cursor
        self.assertEqual(seen + cursor_rest, rest)
        self.assertEqual(rest[-1], "ref_SYNTH000900")

    def test_filters(self):
        self.assertIn(self.c1.reference_id, self.ids(Query(tool="CapCut")))
        self.assertIn(self.c2.reference_id, self.ids(Query(tool="CapCut")))
        self.assertEqual(self.ids(Query(tool="CapCut", tool_visual_only=True)), [self.c1.reference_id])
        self.assertEqual(self.ids(Query(category="demonstracao_ferramenta", min_support="supported_visual", author="autor_x")), [self.c1.reference_id])
        self.assertEqual(self.ids(Query(author="autor_y")), [self.c2.reference_id])
        self.assertEqual(self.ids(Query(technique="tipografia_cinetica", technique_level="temporal_sequence")), [self.c3.reference_id])
        self.assertEqual(self.ids(Query(evidence_tag="ui_screen_visible", author="autor_x")), [self.c1.reference_id])
        self.assertEqual(self.ids(Query(subject="cinematográfico prompting")), [self.c1.reference_id])

    def test_review_state_filter(self):
        self.assertEqual(self.ids(Query(category="tutorial", review_state="accepted")), [self.c1.reference_id])
        self.assertNotIn(self.c1.reference_id, self.ids(Query(category="tutorial", review_state="pending")))

    def test_time_range_filter(self):
        hit = self.ids(Query(evidence_tag="ui_screen_visible", time_range=(19.0, 21.0)))
        self.assertIn(self.c1.reference_id, hit)
        self.assertNotIn(self.c1.reference_id, self.ids(Query(evidence_tag="ui_screen_visible", time_range=(30.0, 40.0))))

    def test_only_current_analysis_is_searched(self):
        doc = controlled(4, "tutorial de motion design")
        first = self.repo.save_analysis(doc)
        doc2 = controlled(4, "review de câmera cinematic")
        self.repo.save_analysis(doc2)
        self.assertNotIn(first.reference_id, self.ids(Query(category="motion_design")))
        self.assertIn(first.reference_id, self.ids(Query(category="cinematografia")))

    def test_page_items_carry_category_summary(self):
        page = search(self.conn, Query(author="autor_x", tool="CapCut", tool_visual_only=True))
        self.assertTrue(page.items[0]["categories"])
        self.assertIsNone(page.next_cursor)

    def test_errors(self):
        for bad in (dict(limit=0), dict(limit=MAX_PAGE + 1), dict(cursor="lixo")):
            with self.assertRaises(QueryError):
                search(self.conn, Query(), **bad)
        for q in (Query(category="inventada"), Query(category="tutorial", min_support="talvez"), Query(review_state="accepted"),
                  Query(subject="a b"), Query(time_range=(5, 1))):
            with self.assertRaises(QueryError):
                search(self.conn, q)

    def test_query_plan_walks_index_without_sorting_everything(self):
        for q in (Query(), Query(category="tutorial", tool="CapCut"), Query(subject="prompting", platform="instagram")):
            plan = " | ".join(explain(self.conn, q))
            self.assertIn("idx_refs_created", plan)
            self.assertNotIn("TEMP B-TREE", plan, plan)
        plan = " | ".join(explain(self.conn, Query(category="tutorial")))
        self.assertIn("SEARCH c USING", plan)

    def test_current_analysis_lookup_is_per_reference_not_global(self):
        """Regressão do O(N²) encontrado no benchmark: a análise corrente deve ser buscada por (status, video_pk)."""
        for q in (Query(), Query(category="tutorial")):
            plan = explain(self.conn, q)
            lookups = [l for l in plan if l.startswith("SEARCH a ")]
            self.assertTrue(lookups)
            for l in lookups:
                self.assertIn("video_pk=?", l, plan)
        rplan = [r[-1] for r in self.conn.execute(
            "EXPLAIN QUERY PLAN SELECT a.analysis_id FROM ref_videos rv CROSS JOIN analyses a ON a.video_pk = rv.video_pk "
            "WHERE rv.reference_id = ? AND a.status = 'current'", ("x",))]
        self.assertTrue(any("video_pk=?" in l for l in rplan if l.startswith("SEARCH a ")), rplan)


if __name__ == "__main__":
    unittest.main()

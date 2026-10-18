import copy
import sqlite3
import unittest

from tests import _helpers  # noqa: F401
from ii_mm.classifier import Classifier
from ii_mm.contract import ContractError
from ii_mm.db.migrations import connect, open_database
from ii_mm.db.repository import Repository
from ii_mm.synthetic import make_reference, sha


def repo(tc):
    conn = open_database()
    tc.addCleanup(conn.close)
    return Repository(conn)


def count(r, table):
    return r.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


class PersistenceTest(unittest.TestCase):
    def test_roundtrip_and_children(self):
        r = repo(self)
        doc = make_reference(5)
        res = r.save_analysis(doc)
        self.assertTrue(res.created)
        self.assertEqual(r.get_document(res.analysis_id), doc)
        self.assertEqual(count(r, "evidence"), len(doc["evidence"]))
        self.assertEqual(count(r, "segments"), len(doc["transcript"]))
        self.assertEqual(count(r, "categories"), len(doc["categories"]))
        self.assertEqual(r.current_analysis_id(res.reference_id), res.analysis_id)

    def test_invalid_document_rejected_before_writing(self):
        r = repo(self)
        doc = make_reference(1)
        doc["video"]["duration_s"] = -1
        with self.assertRaises(ContractError):
            r.save_analysis(doc)
        self.assertEqual(count(r, "refs"), 0)

    def test_requires_explicit_transaction_connection(self):
        c = sqlite3.connect(":memory:")
        self.addCleanup(c.close)
        with self.assertRaises(ValueError):
            Repository(c)

    def test_failure_mid_write_rolls_back(self):
        r = repo(self)
        doc = make_reference(2)
        doc["categories"][0]["evidence_ids"] = list(doc["categories"][0]["evidence_ids"])
        r.conn.execute("CREATE TRIGGER boom BEFORE INSERT ON tools BEGIN SELECT RAISE(ABORT, 'falha simulada'); END")
        if not doc["tools"]:
            self.skipTest("fixture sem ferramenta")
        with self.assertRaises(sqlite3.IntegrityError):
            r.save_analysis(doc)
        for t in ("refs", "videos", "analyses", "evidence"):
            self.assertEqual(count(r, t), 0, t)


class DedupPolicyTest(unittest.TestCase):
    def test_same_video_saved_twice_is_idempotent(self):
        r = repo(self)
        doc = make_reference(7)
        a, b = r.save_analysis(doc), r.save_analysis(copy.deepcopy(doc))
        self.assertTrue(a.created)
        self.assertFalse(b.created)
        self.assertEqual(a.analysis_id, b.analysis_id)
        self.assertEqual(count(r, "analyses"), 1)

    def test_different_urls_same_publication_become_aliases(self):
        r = repo(self)
        doc = make_reference(8); doc["reference"]["platform"] = "instagram"
        doc["reference"]["origin_url"] = "https://www.instagram.com/reel/SYNTHalias1/"
        res = r.save_analysis(doc, seen_url="https://m.instagram.com/p/SYNTHalias1/?utm_source=x")
        self.assertEqual(r.resolve_reference("instagram.com/reels/SYNTHalias1"), res.reference_id)
        self.assertEqual(count(r, "refs"), 1)

    def test_same_content_from_two_publications_is_one_video(self):
        r = repo(self)
        a = make_reference(10); b = make_reference(11)
        b["video"]["content_sha256"] = a["video"]["content_sha256"]
        b["video"]["duration_s"] = a["video"]["duration_s"]
        ra, rb = r.save_analysis(a), r.save_analysis(b)
        self.assertEqual(ra.video_pk, rb.video_pk)
        self.assertNotEqual(ra.reference_id, rb.reference_id)
        self.assertEqual(r.references_for_video(ra.video_pk), sorted([ra.reference_id, rb.reference_id]))

    def test_reprocessing_creates_new_version_and_keeps_old(self):
        r = repo(self)
        doc = make_reference(12)
        first = r.save_analysis(doc)
        reclass = Classifier().classify(doc)
        second = r.save_analysis(reclass)
        self.assertTrue(second.created)
        self.assertEqual(second.superseded, first.analysis_id)
        hist = r.analysis_history(first.video_pk)
        self.assertEqual([h["status"] for h in hist], ["superseded", "current"])
        self.assertEqual(hist[0]["superseded_by"], second.analysis_id)
        self.assertIsNotNone(r.get_document(first.analysis_id))
        self.assertEqual(r.current_analysis_id(first.reference_id), second.analysis_id)

    def test_same_publication_different_content_is_conflict_not_overwrite(self):
        r = repo(self)
        doc = make_reference(13)
        first = r.save_analysis(doc)
        changed = copy.deepcopy(doc)
        changed["video"]["content_sha256"] = sha("outro-conteudo")
        second = r.save_analysis(changed)
        self.assertTrue(second.conflict)
        self.assertNotEqual(first.video_pk, second.video_pk)
        issues = r.open_issues()
        self.assertEqual([(i["kind"], i["blocking"]) for i in issues], [("conflict", 1)])
        self.assertIsNotNone(r.get_document(first.analysis_id))
        r.resolve_issue(issues[0]["issue_id"])
        self.assertEqual(r.open_issues(), [])

    def test_reference_id_collision_with_other_publication(self):
        r = repo(self)
        a = make_reference(14); b = make_reference(15)
        b["reference"]["reference_id"] = a["reference"]["reference_id"]
        r.save_analysis(a)
        with self.assertRaises(sqlite3.IntegrityError):
            r.save_analysis(b)
        self.assertEqual(count(r, "refs"), 1)

    def test_evidence_with_different_hashes_are_distinct(self):
        r = repo(self)
        doc = make_reference(16)
        variant = copy.deepcopy(doc)
        variant["evidence"][0]["provenance"]["extractor"] = "outra-versao"
        a, b = r.save_analysis(doc), r.save_analysis(variant)
        self.assertNotEqual(a.analysis_id, b.analysis_id)
        self.assertEqual(count(r, "analyses"), 2)

    def test_manual_issue_lifecycle(self):
        r = repo(self)
        res = r.save_analysis(make_reference(17))
        iid = r.add_issue("pending", "frames ausentes", video_pk=res.video_pk, blocking=True)
        self.assertEqual(r.open_issues(res.video_pk)[0]["issue_id"], iid)
        r.resolve_issue(iid)
        r.resolve_issue(iid)  # idempotente
        self.assertEqual(r.open_issues(res.video_pk), [])

    def test_search_terms_index(self):
        r = repo(self)
        res = r.save_analysis(make_reference(18))
        terms = {t[0] for t in r.conn.execute("SELECT term FROM search_terms WHERE analysis_id = ?", (res.analysis_id,))}
        self.assertTrue(any(t.startswith("cat:") for t in terms))
        self.assertFalse(terms & {"de", "que", "com"})


if __name__ == "__main__":
    unittest.main()

"""Tarefas 03 e 04: ingestão unificada e identidade (referência ≠ arquivo ≠ análise)."""
import json
import unittest

from tests._util import FIX, TempEngine
from ii_be import artifacts as A
from ii_be.errors import InvalidInput
from ii_be.identity import current_metadata, metadata_history, references_sharing_media
from ii_be.ingest import (manual_record, record_from_local_file, record_from_manifest, record_from_url,
                          records_from_meta_export)
from ii_be.synthetic import fake_video


class UrlIdentityTest(unittest.TestCase):
    def test_url_variants_are_one_reference_and_reingestion_is_idempotent(self):
        with TempEngine(memory=True) as t:
            e = t.engine
            a = e.ingest(record_from_url("https://www.instagram.com/reel/SYNTHid001/?igsh=SYNTHshare&utm_source=x"))
            b = e.ingest(record_from_url("https://instagram.com/p/SYNTHid001"))
            c = e.ingest(record_from_url("https://m.instagram.com/reels/SYNTHid001/"))
            again = e.ingest(record_from_url("https://instagram.com/p/SYNTHid001"))
            self.assertTrue(a.created)
            self.assertEqual({a.reference_id, b.reference_id, c.reference_id}, {a.reference_id})
            self.assertTrue(again.duplicate)
            self.assertEqual(e.conn.execute("SELECT COUNT(*) FROM refs").fetchone()[0], 1)
            y1 = e.ingest(record_from_url("https://youtu.be/SYNTHyt0001?si=SYNTHshare"))
            y2 = e.ingest(record_from_url("https://www.youtube.com/watch?v=SYNTHyt0001&t=30"))
            y3 = e.ingest(record_from_url("https://youtube.com/shorts/SYNTHyt0001"))
            self.assertEqual(len({y1.reference_id, y2.reference_id, y3.reference_id}), 1)
            self.assertNotEqual(y1.reference_id, a.reference_id)

    def test_shortcodes_are_case_sensitive(self):
        with TempEngine(memory=True) as t:
            a = t.engine.ingest(record_from_url("https://www.instagram.com/reel/SYNTHcase1/"))
            b = t.engine.ingest(record_from_url("https://www.instagram.com/reel/synthcase1/"))
            self.assertNotEqual(a.reference_id, b.reference_id)

    def test_tracking_parameters_are_never_persisted(self):
        with TempEngine(memory=True) as t:
            e = t.engine
            e.ingest(record_from_url("https://www.instagram.com/reel/SYNTHtrk01/?igsh=SYNTHsecretshare"))
            e.ingest(record_from_url("https://youtu.be/SYNTHyt0002?si=SYNTHsecretshare"))
            dump = "\n".join(str(tuple(r)) for tbl in ("refs", "ref_aliases", "be_sources", "be_reference_meta", "be_outbox")
                             for r in e.conn.execute(f"SELECT * FROM {tbl}"))
            self.assertNotIn("SYNTHsecretshare", dump)

    def test_reference_id_is_deterministic_across_databases(self):
        ids = []
        for _ in range(2):
            with TempEngine(memory=True) as t:
                ids.append(t.engine.ingest(record_from_url("https://www.instagram.com/reel/SYNTHdet01/")).reference_id)
        self.assertEqual(ids[0], ids[1])

    def test_without_trustworthy_identity_is_refused(self):
        with TempEngine(memory=True) as t:
            e = t.engine
            with self.assertRaises(InvalidInput):
                e.ingest(manual_record(metadata={"caption": "só uma legenda, sem link"}))
            with self.assertRaises(InvalidInput):
                e.ingest(manual_record(platform="youtube", url="https://www.instagram.com/reel/SYNTHcnf01/"))
            with self.assertRaises(InvalidInput):
                e.ingest(record_from_url("https://example.com/video/1", source_kind="manual"))
            self.assertEqual(e.conn.execute("SELECT COUNT(*) FROM refs").fetchone()[0], 0)

    def test_closed_contract_and_limits(self):
        with TempEngine(memory=True) as t:
            e = t.engine
            rec = record_from_url("https://www.instagram.com/reel/SYNTHlim01/")
            for bad in ({**rec, "inesperado": 1}, {**rec, "metadata": {"caption": "x" * 10_001}},
                        {**rec, "metadata": {"campo_novo": "x"}}, {**rec, "metadata": {"duration_s": -3}},
                        {**rec, "metadata": {"hashtags": ["#a"] * 101}}, {**rec, "observed_at": "ontem"},
                        {**rec, "media": {"relpath": "../fora.mp4"}}, {**rec, "media": {"relpath": "a.mp4", "sha256": "xyz"}},
                        {**rec, "schema_version": "outra"}, {**rec, "url": "https://www.instagram.com/reel/A\nB/"}):
                with self.assertRaises(InvalidInput):
                    e.ingest(bad)


class SourcesTest(unittest.TestCase):
    def test_meta_export_is_parsed_without_inventing_fields(self):
        payload = json.loads((FIX / "meta_export_saved_posts.json").read_text(encoding="utf-8"))
        records, errors = records_from_meta_export(payload, "saved_posts.json")
        self.assertEqual(len(records), 3)
        self.assertEqual(len(errors), 2)  # item sem link e host desconhecido: reportados, não inventados
        self.assertEqual(records[0]["observed_at"], "2025-10-09T08:53:20+00:00")
        self.assertEqual(records[0]["metadata"], {"author_handle": "autor_sintetico_a"})
        self.assertNotIn("caption", records[0].get("metadata", {}))
        with TempEngine(memory=True) as t:
            results = [t.engine.ingest(r) for r in records]
            self.assertEqual(len({r.reference_id for r in results}), 2)   # salvo e curtido: mesma publicação
            self.assertTrue(all(r.media_state == "none" for r in results))
            plan = t.engine.plan(results[0].reference_id)
            self.assertTrue(plan.graph.startswith("aguardando_midia"))   # sem mídia e sem duração: nada a classificar
            self.assertEqual(plan.enqueued, {})
        self.assertEqual(records_from_meta_export("{quebrado", "x")[1], ["exportação ilegível (JSON inválido)"])

    def test_manifest_and_local_file_with_same_content_meet(self):
        with TempEngine(memory=True) as t:
            e = t.engine
            data = fake_video("manifesto")
            info = e.store.write_bytes("media/manifesto.mp4", data)
            man = json.loads((FIX / "manifesto_pacote_sintetico.json").read_text(encoding="utf-8"))
            man["video_sha256"] = info.sha256
            m = e.ingest(record_from_manifest(man, "manifesto_pacote.json"))
            self.assertEqual(m.media_state, "none")   # o manifesto informa o hash, não entrega o arquivo
            f = e.ingest(record_from_local_file("media/manifesto.mp4"))
            self.assertEqual(f.reference_id, m.reference_id)
            self.assertEqual(f.media_state, "available")
            self.assertTrue(m.canonical_key.startswith("local:sha-"))

    def test_same_media_on_two_platforms_is_one_content_two_references(self):
        with TempEngine(memory=True) as t:
            e = t.engine
            e.store.write_bytes("media/a.mp4", fake_video("compartilhado"))
            e.store.write_bytes("media/b.mp4", fake_video("compartilhado"))
            ig = e.ingest(record_from_local_file("media/a.mp4", url="https://www.instagram.com/reel/SYNTHshr01/"))
            yt = e.ingest(record_from_local_file("media/b.mp4", url="https://www.youtube.com/watch?v=SYNTHshr002"))
            self.assertNotEqual(ig.reference_id, yt.reference_id)
            sha = A.current(e.conn, ig.reference_id, "video")["sha256"]
            self.assertEqual(references_sharing_media(e.conn, sha), sorted([ig.reference_id, yt.reference_id]))
            ev = e.conn.execute("SELECT payload_json FROM be_outbox WHERE type='media.available' ORDER BY event_seq DESC LIMIT 1").fetchone()[0]
            self.assertEqual(json.loads(ev)["shared_with"], [ig.reference_id])

    def test_partial_media_is_not_available(self):
        with TempEngine(memory=True) as t:
            e = t.engine
            e.store.write_bytes("media/parcial.mp4.part", fake_video("parcial", 1000))
            r = e.ingest(record_from_local_file("media/parcial.mp4.part", url="https://www.instagram.com/reel/SYNTHpar01/"))
            self.assertEqual(r.media_state, "partial")
            self.assertEqual(e.conn.execute("SELECT COUNT(*) FROM be_outbox WHERE type='media.available'").fetchone()[0], 0)
            e.store.write_bytes("media/inteiro.mp4", fake_video("parcial", 1000))
            r2 = e.register_artifact(r.reference_id, "video", "media/inteiro.mp4", origin="tool:download", expected_size=1000)
            self.assertEqual(r2["state"], "verified")
            self.assertEqual(A.media_state(e.conn, r.reference_id), "available")


class MetadataHistoryTest(unittest.TestCase):
    def test_metadata_updates_keep_history_and_null_never_erases(self):
        with TempEngine(memory=True) as t:
            e = t.engine
            url = "https://www.instagram.com/reel/SYNTHmet01/"
            r = e.ingest(record_from_url(url, metadata={"caption": "v1 tutorial capcut", "author_handle": "autor_a"},
                                         observed_at="2026-01-01T00:00:00+00:00", source_ref="s1"))
            e.ingest(record_from_url(url, metadata={"caption": "v2 tutorial premiere"}, observed_at="2026-02-01T00:00:00+00:00", source_ref="s2"))
            e.ingest(record_from_url(url, metadata={"caption": "v0 antiga", "author_handle": None},
                                     observed_at="2025-12-01T00:00:00+00:00", source_ref="s3"))
            cur = current_metadata(e.conn, r.reference_id)
            self.assertEqual(cur["caption"], "v2 tutorial premiere")    # observação antiga não sobrescreve
            self.assertEqual(cur["author_handle"], "autor_a")          # None não apaga
            self.assertEqual([h["value"] for h in metadata_history(e.conn, r.reference_id, "caption")],
                             ["v1 tutorial capcut", "v2 tutorial premiere", "v0 antiga"])
            terms = {x[0] for x in e.conn.execute("SELECT term FROM be_terms WHERE reference_id = ?", (r.reference_id,))}
            self.assertIn("premiere", terms)
            self.assertNotIn("capcut", terms)                          # termos refletem o valor corrente
            self.assertEqual(e.conn.execute("SELECT author_handle FROM refs").fetchone()[0], "autor_a")
            self.assertEqual(e.conn.execute("SELECT COUNT(*) FROM be_sources").fetchone()[0], 3)


if __name__ == "__main__":
    unittest.main()

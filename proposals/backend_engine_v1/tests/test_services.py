"""Tarefas 11, 13, 14 e 15: classificação (facetas), conhecimento, busca e curadoria humana soberana."""
import json
import unittest

from tests._util import TempEngine
from ii_be import incremental as I
from ii_be import knowledge as K
from ii_be.classification import FACET_NAMES, ClassificationService
from ii_be.curation import CurationConflict, CurationError, CurationService
from ii_be.ingest import record_from_url
from ii_be.search import QueryError, build, list_references, search
from ii_be.synthetic import seed_media_reference, tool_outputs

META = {"caption": "Legendas automáticas no CapCut", "hashtags": ["#capcut", "#tutorial"], "author_handle": "autor_demo"}
SRT_PREMIERE = ("1\n00:00:00,000 --> 00:00:05,000\nHoje vou falar do Premiere Pro\n\n2\n00:00:05,000 --> 00:00:12,000\n"
                "Primeiro abre o projeto, em seguida o passo a passo da edição de vídeo\n")


def dataset(t):
    e = t.engine
    a = seed_media_reference(e, "https://www.instagram.com/reel/SYNTHsvA01/", "svA01", metadata=META)["ingest"].reference_id
    outs = tool_outputs()
    outs["srt"] = SRT_PREMIERE.encode()
    outs.pop("observations")
    c = seed_media_reference(e, "https://www.youtube.com/watch?v=SYNTHsvC001", "svC01", metadata={"title": "Edição no Premiere"},
                             outputs=outs)["ingest"].reference_id
    b = e.ingest(record_from_url("https://www.youtube.com/watch?v=SYNTHsvB001",
                                 metadata={"title": "Automação passo a passo no n8n com webhook", "duration_s": 95.0})).reference_id
    e.run()
    return a, b, c


class ClassificationFacetsTest(unittest.TestCase):
    def test_facets_keep_the_distinctions(self):
        with TempEngine() as t:
            a, b, c = dataset(t)
            svc = ClassificationService(t.engine)
            r = svc.result(a)
            f = r["facets"]
            self.assertEqual(set(f), set(FACET_NAMES))
            self.assertEqual([x["name"] for x in f["ferramenta_identificada_visualmente"]], ["CapCut"])
            self.assertIn("CapCut", [x["name"] for x in f["ferramenta_mencionada"]])
            obs = {x["technique"]: x["level"] for x in f["tecnica_observada"]}
            self.assertEqual(obs.get("split_screen"), "observed_in_frame")
            self.assertEqual(obs.get("punch_in"), "frame_pair_difference")
            self.assertIn("legenda_animada", [x["technique"] for x in f["tecnica_hipotetica"]])
            self.assertTrue(any(x["kind"] == "oferta_ou_chamada_comercial" for x in f["promessa_comercial"]))
            self.assertTrue(all("label" in x for x in f["potencial_criativo"]))
            self.assertTrue(f["estrutura_narrativa"])
            self.assertIsNone(r["numeric_confidence"])
            blob = json.dumps(r)
            self.assertNotIn("confidence\": 0", blob)
            rc = svc.result(c)["facets"]
            self.assertIn("Adobe Premiere Pro", [x["name"] for x in rc["ferramenta_mencionada"]])
            self.assertEqual(rc["ferramenta_identificada_visualmente"], [])   # menção nunca vira identificação visual
            self.assertEqual(rc["tecnica_observada"], [])

    def test_request_status_and_force(self):
        with TempEngine() as t:
            a, b, c = dataset(t)
            svc = ClassificationService(t.engine)
            req = svc.request(a)
            self.assertEqual(req["enqueued"], {})
            self.assertIn("classify", req["reused"])
            forced = svc.request(a, force=True)
            self.assertIn("classify", forced["enqueued"])
            self.assertEqual(svc.status(a)["classify"]["status"], "queued")
            with self.assertRaises(KeyError):
                svc.request("ref_inexistente")


class KnowledgeQuestionsTest(unittest.TestCase):
    def test_questions_answer_with_provenance(self):
        with TempEngine() as t:
            a, b, c = dataset(t)
            conn = t.engine.conn
            teach = K.videos_teaching_tool(conn, "CapCut")
            self.assertEqual([x["reference_id"] for x in teach], [a])
            self.assertTrue(teach[0]["demonstrated"])
            self.assertTrue(teach[0]["provenance"]["evidence_ids"])
            self.assertEqual([x["reference_id"] for x in K.where_technique(conn, "split_screen")], [a])
            self.assertEqual(K.where_technique(conn, "legenda_animada"), [])                     # só hipótese
            self.assertEqual([x["reference_id"] for x in K.where_technique(conn, "legenda_animada", include_hypotheses=True)], [a])
            self.assertEqual([x["reference_id"] for x in K.references_with_visual_element(conn, "split_screen")], [a])
            levels = K.techniques_by_evidence_level(conn)
            self.assertIn("legenda_animada", [x["technique"] for x in levels["hipoteses"]])
            self.assertNotIn("legenda_animada", [x["technique"] for x in levels["observadas"]])
            not_demo = {(x["tool"], x["reference_id"]) for x in K.tools_mentioned_not_demonstrated(conn)}
            self.assertIn(("Adobe Premiere Pro", c), not_demo)
            self.assertNotIn(("CapCut", a), not_demo)
            self.assertEqual([x["reference_id"] for x in K.automation_processes(conn)], [b])
            kinds = {(x["reference_id"], x["kind"]) for x in K.transferable_knowledge(conn)}
            self.assertIn((a, "tutorial"), kinds)
            for row in K.knowledge_for(conn, a):
                if row["facet"] in ("categoria", "ferramenta", "tecnica", "elemento_visual"):
                    self.assertTrue(row["analysis_id"])


class CurationTest(unittest.TestCase):
    def test_triage_rating_with_optimistic_concurrency_and_history(self):
        with TempEngine() as t:
            a, b, c = dataset(t)
            cur = CurationService(t.engine.conn, t.clock)
            tag = cur.state(a)["etag"]
            r1 = cur.decide(a, "triage", "human:ana", value="manter", expected_etag=tag)
            with self.assertRaises(CurationConflict):
                cur.decide(a, "rating", "human:bia", value="bom", expected_etag=tag)       # visão velha
            cur.decide(a, "rating", "human:bia", value="excelente", expected_etag=r1["etag"])
            cur.decide(a, "triage", "human:ana", value="revisar")
            st = cur.state(a)
            self.assertEqual((st["triage"], st["rating"]), ("revisar_depois", "excelente"))
            hist = cur.history(a)
            self.assertEqual([h["after"] for h in hist if h["action"] == "triage"], [{"triage": "manter"}, {"triage": "revisar_depois"}])
            self.assertEqual(hist[-1]["before"], {"triage": "manter", "rating": "excelente"})
            n_events = t.engine.conn.execute("SELECT COUNT(*) FROM be_outbox WHERE type='curation.reviewed'").fetchone()[0]
            self.assertEqual(n_events, 3)

    def test_only_humans_and_reasons_where_required(self):
        with TempEngine() as t:
            a, b, c = dataset(t)
            cur = CurationService(t.engine.conn, t.clock)
            for bot in ("agent:classificador", "auto:reclassify", "n8n:workflow", "worker:w1", "model:mock"):
                with self.assertRaises(CurationError):
                    cur.decide(a, "triage", bot, value="manter")
            with self.assertRaises(CurationError):
                cur.decide(a, "triage", "human:ana", value="descartar")                   # sem motivo
            with self.assertRaises(CurationError):
                cur.decide(a, "rating", "human:ana", value="10/10")
            with self.assertRaises(CurationError):
                cur.decide(a, "reject_category", "human:ana", category="tutorial")           # ii_mm exige justificativa
            self.assertEqual(t.engine.conn.execute("SELECT COUNT(*) FROM be_curation_log").fetchone()[0], 0)

    def test_human_decision_survives_automatic_reclassification(self):
        with TempEngine() as t:
            a, b, c = dataset(t)
            e = t.engine
            cur = CurationService(e.conn, t.clock)
            cur.decide(a, "reject_category", "human:ana", reason="a oferta é do criador, não o tema", category="marketing_vendas")
            cur.decide(a, "correct_tool", "human:ana", reason="versão desktop", wrong_name="CapCut", right_name="CapCut Desktop")
            doc_ev = [x for x in K.knowledge_for(e.conn, a) if x["facet"] == "elemento_visual"]
            cur.decide(a, "confirm_evidence", "human:ana", evidence_id=doc_ev[0]["provenance"]["evidence_ids"][0])
            cur.decide(a, "reject_hypothesis", "human:ana", reason="a legenda não muda entre os quadros", technique="legenda_animada")
            e.run()
            srt = tool_outputs()["srt"].decode() + "\n6\n00:00:21,000 --> 00:00:23,000\nCupom com desconto no link na bio\n"
            e.store.write_bytes("tools/svA01/srt_v2.srt", srt.encode())
            e.register_artifact(a, "srt", "tools/svA01/srt_v2.srt", origin="tool:whisper")
            e.run()                                                                         # nova análise automática
            res = I.current_result(e.conn, a, "classify")["result"]
            self.assertIn({"category": "marketing_vendas", "human": "rejected", "automatic": res["categories"]["marketing_vendas"]},
                          res["human_overrides"])
            facets = ClassificationService(e).result(a)["facets"]
            mv = [x for x in facets["categoria_editorial"] if x["category"] == "marketing_vendas"][0]
            self.assertEqual((mv["review_state"], mv["authority"]), ("rejected", "human"))
            self.assertFalse(any(x.get("kind") == "oferta_ou_chamada_comercial" for x in facets["promessa_comercial"]))
            self.assertIn("CapCut Desktop", [x["name"] for x in facets["ferramenta_identificada_visualmente"]])
            kn = {(x["facet"], x["value"]): (x["status"], x["authority"]) for x in K.knowledge_for(e.conn, a)}
            self.assertEqual(kn[("tecnica", "legenda_animada")], ("hipotese_rejeitada", "human"))
            self.assertEqual(kn[("categoria", "marketing_vendas")], ("rejeitada_humano", "human"))
            self.assertEqual(K.where_technique(e.conn, "legenda_animada", include_hypotheses=True), [])
            self.assertEqual(len([h for h in CurationService(e.conn, t.clock).history(a)]), 4)
            self.assertEqual(e.conn.execute("SELECT COUNT(*) FROM be_outbox WHERE type='curation.reviewed'").fetchone()[0], 4)


class SearchTest(unittest.TestCase):
    def test_combined_filters_reuse_catalog_and_paginate(self):
        with TempEngine() as t:
            a, b, c = dataset(t)
            conn = t.engine.conn
            CurationService(conn, t.clock).decide(a, "triage", "human:ana", value="manter")
            hit = search(conn, {"category": "tutorial", "tool": "CapCut", "text": "legendas capcut", "requires": ["visual", "transcript"],
                                "triage": "manter"})
            self.assertEqual([r["reference_id"] for r in hit["items"]], [a])
            self.assertEqual(hit["items"][0]["curation"], {"triage": "manter", "rating": None})
            self.assertEqual(search(conn, {"tool": "CapCut", "requires": ["visual"], "platform": "youtube"})["items"], [])
            self.assertEqual(search(conn, {"evidence_status": "observed_visual"})["items"][0]["reference_id"], a)
            p1 = search(conn, {}, limit=2)
            p2 = search(conn, {}, cursor=p1["next_cursor"], limit=2)
            got = [r["reference_id"] for r in p1["items"] + p2["items"]]
            self.assertEqual(len(got), 3)
            self.assertEqual(len(set(got)), 3)
            self.assertIsNone(p2["next_cursor"])

    def test_author_time_range_and_ingestion_date_filters(self):
        with TempEngine() as t:
            a, b, c = dataset(t)
            conn = t.engine.conn
            self.assertEqual([r["reference_id"] for r in search(conn, {"author": "autor_demo"})["items"]], [a])
            hit = search(conn, {"evidence_tag": "punch_in_scale", "time_range": [13.0, 15.0]})["items"]
            self.assertEqual([r["reference_id"] for r in hit], [a])
            self.assertEqual(search(conn, {"evidence_tag": "punch_in_scale", "time_range": [0.0, 5.0]})["items"], [])
            self.assertEqual(len(search(conn, {"ingested_from": "2000-01-01T00:00:00+00:00"})["items"]), 3)
            self.assertEqual(search(conn, {"ingested_from": "2999-01-01T00:00:00+00:00"})["items"], [])

    def test_invalid_and_hostile_filters(self):
        with TempEngine() as t:
            a, b, c = dataset(t)
            conn = t.engine.conn
            for bad in ({"campo": 1}, {"category": "inventada"}, {"requires": ["tudo"]}, {"evidence_status": "x"},
                        {"time_range": [5, 1]}, {"text": "a b"}):
                with self.assertRaises(QueryError, msg=bad):
                    search(conn, bad)
            for evil in ("'; DROP TABLE refs; --", "\" OR 1=1 --", "capcut') OR ('1'='1"):
                self.assertEqual(search(conn, {"author": evil})["items"], [])
                self.assertEqual(search(conn, {"text": evil + " zzzz"})["items"], [])
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM refs").fetchone()[0], 3)
            with self.assertRaises(QueryError):
                search(conn, {}, cursor="nao-e-cursor")

    def test_injected_conditions_keep_the_catalog_plan(self):
        with TempEngine() as t:
            dataset(t)
            q, sql, args = build({"category": "tutorial", "text": "capcut", "triage": "manter"}, None, 10)
            self.assertEqual(sql.count(" ORDER BY r.created_at "), 1)
            plan = " | ".join(r[-1] for r in t.engine.conn.execute("EXPLAIN QUERY PLAN " + sql, args))
            self.assertIn("idx_refs_created", plan)
            self.assertNotIn("TEMP B-TREE", plan)

    def test_list_references_includes_unanalysed(self):
        with TempEngine() as t:
            a, b, c = dataset(t)
            e = t.engine
            d = e.ingest(record_from_url("https://www.instagram.com/reel/SYNTHsvD01/")).reference_id
            allr = list_references(e.conn)["items"]
            self.assertEqual(len(allr), 4)
            self.assertEqual([r["reference_id"] for r in list_references(e.conn, analysed=False)["items"]], [d])
            self.assertEqual(sorted(r["reference_id"] for r in list_references(e.conn, media="available")["items"]), sorted([a, c]))


if __name__ == "__main__":
    unittest.main()

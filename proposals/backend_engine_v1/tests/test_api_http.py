"""Tarefas 17 e 18: contratos de API, HTTP local restrito ao loopback e observabilidade."""
import io
import json
import unittest
import urllib.error
import urllib.request

from tests._util import TempEngine
from ii_be.api import ServiceAPI
from ii_be.clock import SystemClock
from ii_be.engine import Engine
from ii_be.http_local import make_server, serve_in_thread
from ii_be.ingest import record_from_url
from ii_be.observability import JsonLogger, redact
from ii_be.synthetic import seed_media_reference

META = {"caption": "Legendas automáticas no CapCut", "hashtags": ["#capcut"], "author_handle": "autor_demo"}


class ApiContractTest(unittest.TestCase):
    def test_read_operations_and_envelope(self):
        with TempEngine() as t:
            e = t.engine
            ref = seed_media_reference(e, "https://www.instagram.com/reel/SYNTHapi01/", "api01", metadata=META)["ingest"].reference_id
            e.run()
            api = ServiceAPI.from_engine(e)
            r = api.handle("get_reference", {"reference_id": ref})
            self.assertTrue(r["ok"])
            self.assertEqual(r["api"], "ii.be.api.v1")
            self.assertEqual(r["data"]["media_state"], "available")
            self.assertEqual(api.handle("get_processing", {"reference_id": ref})["data"]["ii_mm_equivalent"], "completed")
            ev = api.handle("get_evidence", {"reference_id": ref, "limit": 3})["data"]
            self.assertEqual(len(ev["items"]), 3)
            ev2 = api.handle("get_evidence", {"reference_id": ref, "after": ev["next_after"], "limit": 100})["data"]
            self.assertFalse({x["evidence_id"] for x in ev["items"]} & {x["evidence_id"] for x in ev2["items"]})
            self.assertIn("ferramenta_identificada_visualmente", api.handle("get_classification", {"reference_id": ref})["data"]["facets"])
            jobs = api.handle("list_jobs", {"reference_id": ref, "state": "completed", "limit": 100})["data"]["items"]
            self.assertEqual(len(jobs), 13)                          # 12 etapas + 1 job de planejamento
            job = api.handle("get_job", {"job_id": jobs[0]["job_id"]})["data"]
            self.assertEqual(job["attempts_history"][0]["outcome"], "completed")
            self.assertEqual(api.handle("search", {"filters": {"tool": "CapCut"}})["data"]["items"][0]["reference_id"], ref)
            self.assertEqual(api.handle("search_knowledge", {"question": "teaching_tool", "value": "CapCut"})["data"][0]["reference_id"], ref)
            self.assertEqual(api.handle("list_failures", {})["data"]["items"], [])
            self.assertIn("jobs", api.handle("diagnostics", {})["data"])

    def test_errors_are_structured_and_never_leak_internals(self):
        with TempEngine(memory=True) as t:
            api = ServiceAPI.from_engine(t.engine)
            cases = {("get_reference", '{"reference_id": "ref_' + "0" * 20 + '"}'): "NOT_FOUND",
                     ("get_reference", '{"reference_id": "../../etc"}'): "VALIDATION_ERROR",
                     ("get_reference", '{"reference_id": "ref_x", "extra": 1}'): "VALIDATION_ERROR",
                     ("nao_existe", "{}"): "UNKNOWN_OPERATION",
                     ("list_jobs", '{"state": "queued\' OR 1=1 --"}'): "VALIDATION_ERROR",
                     ("list_jobs", '{"limit": 1000}'): "VALIDATION_ERROR",
                     ("get_reference", "{quebrado"): "VALIDATION_ERROR",
                     ("get_reference", "[1, 2]"): "VALIDATION_ERROR",
                     ("search", '{"filters": {"category": "inventada"}}'): "VALIDATION_ERROR"}
            for (op, body), code in cases.items():
                r = api.handle(op, body.encode())
                self.assertEqual((r["ok"], r["error"]["code"]), (False, code), (op, body))
                self.assertNotIn("Traceback", json.dumps(r))
            big = api.handle("search", ("{" + '"filters": {"text": "' + "a" * 300_000 + '"}}').encode())
            self.assertEqual(big["error"]["code"], "PAYLOAD_TOO_LARGE")

    def test_write_operations_are_idempotent_and_replay_safe(self):
        with TempEngine(memory=True) as t:
            api = ServiceAPI.from_engine(t.engine)
            body = {"record": record_from_url("https://www.instagram.com/reel/SYNTHapi02/"), "idempotency_key": "ingest-0001"}
            r1 = api.handle("ingest_reference", body)
            r2 = api.handle("ingest_reference", body)
            self.assertTrue(r1["data"]["created"])
            self.assertEqual((r2["meta"]["replayed"], r2["data"]), (True, r1["data"]))
            other = {"record": record_from_url("https://www.instagram.com/reel/SYNTHapi03/"), "idempotency_key": "ingest-0001"}
            self.assertEqual(api.handle("ingest_reference", other)["error"]["code"], "IDEMPOTENCY_MISMATCH")
            self.assertEqual(api.handle("ingest_reference", {"record": body["record"]})["error"]["code"], "VALIDATION_ERROR")
            ref = r1["data"]["reference_id"]
            cur = api.handle("register_curation", {"reference_id": ref, "action": "triage", "reviewer": "human:ana",
                                                   "params": {"value": "manter"}, "idempotency_key": "cur-000001"})
            self.assertTrue(cur["ok"], cur)
            again = api.handle("register_curation", {"reference_id": ref, "action": "triage", "reviewer": "human:ana",
                                                     "params": {"value": "manter"}, "idempotency_key": "cur-000001"})
            self.assertTrue(again["meta"]["replayed"])
            self.assertEqual(t.engine.conn.execute("SELECT COUNT(*) FROM be_curation_log").fetchone()[0], 1)
            stale = api.handle("register_curation", {"reference_id": ref, "action": "rating", "reviewer": "human:bia", "expected_etag": "0.0",
                                                     "params": {"value": "bom"}, "idempotency_key": "cur-000002"})
            self.assertEqual(stale["error"]["code"], "CONFLICT")
            bot = api.handle("register_curation", {"reference_id": ref, "action": "rating", "reviewer": "agent:x",
                                                   "params": {"value": "bom"}, "idempotency_key": "cur-000003"})
            self.assertEqual(bot["error"]["code"], "VALIDATION_ERROR")


class HttpLocalTest(unittest.TestCase):
    def test_loopback_only_and_round_trip(self):
        with self.assertRaises(ValueError):
            make_server(ServiceAPI(engine_factory=lambda: None), host="0.0.0.0")
        with TempEngine(clock=SystemClock()) as t:
            t.engine.ingest(record_from_url("https://www.instagram.com/reel/SYNTHhttp1/"))
            db, root = t.engine.db_path, t.dir / "store"
            api = ServiceAPI(engine_factory=lambda: Engine(db, root=root, clock=SystemClock()))
            srv, th = serve_in_thread(api)
            base = f"http://127.0.0.1:{srv.server_address[1]}"
            try:
                def post(op, body, ctype="application/json", host=None):
                    data = body if isinstance(body, bytes) else json.dumps(body).encode()
                    rq = urllib.request.Request(f"{base}/v1/{op}", data=data, method="POST", headers={"Content-Type": ctype})
                    if host:
                        rq.add_header("Host", host)
                    try:
                        with urllib.request.urlopen(rq, timeout=10) as resp:
                            return resp.status, json.loads(resp.read())
                    except urllib.error.HTTPError as exc:
                        return exc.code, json.loads(exc.read())
                st, body = post("list_references", {})
                self.assertEqual((st, len(body["data"]["items"])), (200, 1))
                self.assertEqual(post("list_references", b"{quebrado")[0], 400)
                self.assertEqual(post("list_references", {}, ctype="text/plain")[0], 400)          # sem preflight CORS: bloqueia CSRF
                self.assertEqual(post("list_references", {}, host="atacante.example")[0], 400)    # DNS rebinding
                self.assertEqual(post("get_reference", {"reference_id": "ref_" + "1" * 20})[0], 404)
                self.assertEqual(post("x", b"{" + b" " * 300_000 + b"}")[0], 413)
                with urllib.request.urlopen(f"{base}/v1/health", timeout=10) as resp:
                    self.assertEqual(json.loads(resp.read())["data"]["status"], "ok")
            finally:
                srv.shutdown()
                srv.server_close()
                th.join(5)


class ObservabilityTest(unittest.TestCase):
    def test_redaction_of_secrets_and_content(self):
        rec = redact({"token": "abc", "Authorization": "Bearer xyz", "api_key": "k", "caption": "legenda privada do usuário",
                      "note": "use Bearer SYNTHsecret123456 aqui e sk-SYNTHabcdefghijklmnop1234", "nested": {"session_id": 1, "x": [1, 2]}})
        dumped = json.dumps(rec)
        for leaked in ("abc", "xyz", "legenda privada", "SYNTHsecret123456", "sk-SYNTH"):
            self.assertNotIn(leaked, dumped)
        self.assertEqual(rec["caption"]["len"], len("legenda privada do usuário"))
        self.assertEqual(rec["nested"]["x"], [1, 2])

    def test_job_logs_are_structured_and_traceable(self):
        buf = io.StringIO()
        with TempEngine(logger=None) as t:
            e = t.engine
            e.log = JsonLogger(buf, clock=t.clock)
            ref = seed_media_reference(e, "https://www.instagram.com/reel/SYNTHlog01/", "log01", metadata=META)["ingest"].reference_id
            e.run()
        lines = [json.loads(x) for x in buf.getvalue().splitlines()]
        finished = [x for x in lines if x["event"] == "job.finished" and x.get("stage")]
        self.assertEqual(len(finished), 12)
        for x in finished:
            for k in ("job_id", "reference_id", "stage", "attempt", "duration_ms", "outcome"):
                self.assertIn(k, x)
        self.assertNotIn("Legendas automáticas", buf.getvalue())     # conteúdo não vai para o log
        self.assertTrue(all(x["reference_id"] == ref for x in finished))

    def test_diagnostics_view(self):
        with TempEngine() as t:
            e = t.engine
            seed_media_reference(e, "https://www.instagram.com/reel/SYNTHdia01/", "dia01", metadata=META)
            e.run()
            d = e.diagnostics()
            self.assertEqual(d["jobs"]["pending"], 0)
            self.assertEqual(d["jobs"]["running"], 0)
            self.assertEqual(d["awaiting_review"], 1)
            self.assertIn("classify", d["time_per_stage"])
            self.assertEqual(d["reprocess_rate"]["reprocessed_pairs"], 0)
            self.assertGreater(d["events"]["outbox"], 5)


if __name__ == "__main__":
    unittest.main()

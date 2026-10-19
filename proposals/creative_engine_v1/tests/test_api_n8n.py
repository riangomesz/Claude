import json
import re
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from tests._util import Env, mocks, ROOT
from ii_ce import _be  # noqa: F401
from ii_be.engine import Engine
from ii_ce.api import SPECS, CreativeAPI, serve
from ii_ce.orchestrator import CreativeEngine

WF = ROOT / "n8n" / "ii_creative_engine_investigacao.workflow.json"


def post(base, op, body=None, ctype="application/json", host=None):
    req = urllib.request.Request(f"{base}/v1/{op}", data=json.dumps(body or {}).encode(), headers={"Content-Type": ctype, **({"Host": host} if host else {})}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


class ApiEndToEnd(unittest.TestCase):
    def setUp(self):
        self.env = Env().__enter__()
        e = self.env

        def factory():
            eng = Engine(str(e.dir / "e.sqlite"), root=e.dir / "store", clock=e.clock)
            return CreativeEngine(engine=eng, providers=mocks(), clock=e.clock)
        self.api = CreativeAPI(factory, e.dir / "dossies", e.dir / "staging")
        self.srv, self.th = serve(self.api)
        self.base = f"http://127.0.0.1:{self.srv.server_address[1]}"

    def tearDown(self):
        self.srv.shutdown(); self.srv.server_close(); self.env.__exit__(None, None, None)

    def test_workflow_sequence_over_http(self):
        ref = self.env.ref
        st, r = post(self.base, "open_investigation", {"reference_id": ref, "depth": "deep", "limits": {"max_calls": 4, "max_usd": 0}, "requested_by": "n8n:fluxo"})
        self.assertEqual(st, 200); inv = r["data"]["investigation_id"]; self.assertTrue(r["data"]["created"])
        self.assertFalse(post(self.base, "open_investigation", {"reference_id": ref, "depth": "deep", "limits": {"max_calls": 4, "max_usd": 0}})[1]["data"]["created"])
        st, r = post(self.base, "run_investigation", {"investigation_id": inv, "max_tasks": 2, "retry_blocked": False})
        self.assertEqual((st, r["data"]["executed"], r["data"]["state"]), (200, 2, "running"))
        st, r = post(self.base, "run_investigation", {"investigation_id": inv, "max_tasks": 10, "retry_blocked": True}); self.assertEqual(r["data"]["state"], "complete")
        st, r = post(self.base, "get_status", {"investigation_id": inv}); self.assertEqual(r["data"]["progress"]["done"], 4)
        st, d = post(self.base, "generate_dossier", {"investigation_id": inv}); self.assertTrue(d["data"]["created"])
        self.assertFalse(post(self.base, "generate_dossier", {"investigation_id": inv})[1]["data"]["created"])
        st, s = post(self.base, "get_status", {"investigation_id": inv}); self.assertTrue(s["data"]["awaiting_human"])
        # o n8n NÃO pode aprovar nem revisar
        st, r = post(self.base, "approve", {"investigation_id": inv, "scope": "dossier", "value": d["data"]["content_hash"], "approver": "n8n:fluxo"})
        self.assertEqual((st, r["ok"]), (400, False))
        st, r = post(self.base, "register_review", {"reference_id": ref, "key": "ferramenta:capcut", "decision": "confirm", "reviewer": "n8n:fluxo"}); self.assertEqual(st, 400)
        st, r = post(self.base, "register_review", {"reference_id": ref, "key": "ferramenta:capcut", "decision": "confirm", "reviewer": "human:rian"}); self.assertEqual(st, 200)
        st, r = post(self.base, "approve", {"investigation_id": inv, "scope": "dossier", "value": d["data"]["content_hash"], "approver": "human:rian"}); self.assertEqual(st, 200)
        # eventos: ler, confirmar, não reler
        st, ev = post(self.base, "poll_events", {"consumer": "n8n-ce", "limit": 100}); ids = [x["event_id"] for x in ev["data"]["events"]]
        self.assertIn("investigation.created", [x["type"] for x in ev["data"]["events"]]); self.assertTrue(ids)
        post(self.base, "ack_events", {"consumer": "n8n-ce", "event_ids": ids})
        self.assertTrue(all(x["event_id"] not in ids for x in post(self.base, "poll_events", {"consumer": "n8n-ce"})[1]["data"]["events"]))
        st, q = post(self.base, "list_open_questions", {"investigation_id": inv}); self.assertEqual(st, 200); self.assertIn("questions", q["data"])
        self.assertEqual(post(self.base, "export_obsidian", {"investigation_id": inv})[0], 200)
        self.assertTrue((self.env.dir / "dossies" / ref / "manifest.json").is_file())

    def test_validation_and_safety(self):
        st, r = post(self.base, "open_investigation", {"reference_id": "ref_x"}); self.assertEqual((st, r["error"]["code"]), (400, "VALIDATION_ERROR"))
        st, r = post(self.base, "open_investigation", {"reference_id": self.env.ref, "campo_novo": 1}); self.assertEqual(st, 400)
        st, r = post(self.base, "open_investigation", {"reference_id": self.env.ref, "limits": {"api_key": "x"}}); self.assertEqual(st, 400)
        st, r = post(self.base, "run_investigation", {"investigation_id": "inv_" + "0" * 20}); self.assertEqual((st, r["error"]["code"]), (400, "VALIDATION_ERROR"))
        st, r = post(self.base, "operacao_inexistente"); self.assertEqual(st, 404)
        st, r = post(self.base, "get_status", {}, ctype="text/plain"); self.assertEqual(st, 400)
        st, r = post(self.base, "get_status", {}, host="evil.example"); self.assertEqual(st, 400)
        self.assertNotIn("Traceback", json.dumps(r))
        with self.assertRaises(ValueError):
            serve(self.api, host="0.0.0.0")


class WorkflowArtifact(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.wf = json.loads(WF.read_text(encoding="utf-8"))

    def test_inactive_no_credentials_no_external_hosts(self):
        self.assertFalse(self.wf["active"])
        text = WF.read_text(encoding="utf-8")
        self.assertNotIn('"credentials"', text)
        hosts = set(re.findall(r"https?://([^/\"'\s:]+)", text))
        self.assertTrue(hosts <= {"127.0.0.1"}, hosts)
        self.assertNotRegex(text.lower(), r"api[_-]?key|bearer|password|token")

    def test_graph_is_consistent(self):
        names = [n["name"] for n in self.wf["nodes"]]
        self.assertEqual(len(names), len(set(names)))
        self.assertEqual(len({n["id"] for n in self.wf["nodes"]}), len(names))
        for src, outs in self.wf["connections"].items():
            self.assertIn(src, names)
            for branch in outs["main"]:
                for c in branch:
                    self.assertIn(c["node"], names)
        triggers = [n["name"] for n in self.wf["nodes"] if "Trigger" in n["type"] or n["type"].endswith("webhook")]
        self.assertTrue({"Webhook: referência aprovada", "Teste manual"} <= set(triggers))

    def test_http_nodes_call_only_existing_ops_with_valid_fields(self):
        calls = [n for n in self.wf["nodes"] if n["type"] == "n8n-nodes-base.httpRequest"]
        self.assertGreaterEqual(len(calls), 6)
        for n in calls:
            op = re.search(r"/v1/(\w+)$", n["parameters"]["url"]).group(1)
            self.assertIn(op, SPECS, n["name"])
            keys = set(re.findall(r"(?:[{,]\s*)(\w+)\s*:", n["parameters"]["jsonBody"]))
            self.assertTrue(keys <= set(SPECS[op]) | {"max_calls", "max_usd"}, (n["name"], keys - set(SPECS[op])))
            self.assertTrue(n.get("retryOnFail")); self.assertTrue(n["parameters"]["url"].startswith("={{ $('Configuração').first().json.base_url }}"))

    def test_no_domain_logic_in_code_nodes_and_ai_nodes_are_absent(self):
        types = {n["type"] for n in self.wf["nodes"]}
        self.assertFalse({t for t in types if "code" in t.lower() or "openAi" in t or "langchain" in t.lower() or "anthropic" in t.lower()})
        self.assertTrue(all(n.get("disabled") for n in self.wf["nodes"] if n["name"] in ("Exportar para staging do Obsidian", "Ler eventos", "Confirmar eventos", "Agenda: eventos (desabilitado)")))
        max_usd = [n for n in self.wf["nodes"] if n["name"] == "Abrir investigação"][0]["parameters"]["jsonBody"]
        self.assertIn("max_usd: 0", max_usd)      # o fluxo nunca libera modelo pago
        self.assertIn("n8n:", max_usd)             # e se identifica como ator automático

    def test_no_n8n_step_can_take_human_decisions(self):
        ops = {re.search(r"/v1/(\w+)$", n["parameters"]["url"]).group(1) for n in self.wf["nodes"] if n["type"] == "n8n-nodes-base.httpRequest"}
        self.assertFalse(ops & {"approve", "register_review"})


if __name__ == "__main__":
    unittest.main()

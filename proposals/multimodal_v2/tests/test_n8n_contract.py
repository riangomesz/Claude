import copy
import json
import unittest
from pathlib import Path

from tests import _helpers  # noqa: F401
from ii_mm.db.migrations import open_database
from ii_mm.n8n_contract import (
    MISSION_SCHEMA, MissionGateway, build_result, compute_mission_id, sign, validate_mission, validate_result, verify_signature,
)
from ii_mm.synthetic import sha

FIX = Path(__file__).resolve().parents[1] / "fixtures"
SECRET = b"segredo-de-teste-nao-real"


def mission(**over):
    m = {"schema_version": MISSION_SCHEMA, "reference": {"platform": "instagram", "url": "https://www.instagram.com/reel/SYNTHn8n01/"},
         "requested_stages": ["evidence_normalized", "classified"],
         "artifacts": [{"kind": "transcript", "sha256": sha("t"), "uri": "missions/SYNTHn8n01/transcript.json"},
                       {"kind": "frames_manifest", "sha256": sha("f"), "uri": "missions/SYNTHn8n01/manifesto_pacote.json"}],
         "budget": {"allow_paid_models": False, "max_usd": 0}, "requested_by": "n8n:workflow-teste", "created_at": "2026-10-18T00:00:00Z"}
    m.update(over)
    try:
        m["mission_id"] = compute_mission_id(m)
    except Exception:  # referência inválida de propósito: a validação deve recusar antes de calcular
        m["mission_id"] = "ms_invalido"
    return m


class MissionValidationTest(unittest.TestCase):
    def test_example_fixtures_are_valid(self):
        m = json.loads((FIX / "n8n_mission_example.json").read_text(encoding="utf-8"))
        r = json.loads((FIX / "n8n_result_example.json").read_text(encoding="utf-8"))
        self.assertEqual(validate_mission(m), [])
        self.assertEqual(validate_result(r), [])
        self.assertEqual(r["mission_id"], m["mission_id"])

    def test_valid_mission(self):
        self.assertEqual(validate_mission(mission()), [])

    def test_mission_id_is_deterministic_and_bound_to_content(self):
        a, b = mission(), mission()
        self.assertEqual(a["mission_id"], b["mission_id"])
        same_pub_other_url = mission(reference={"platform": "instagram", "url": "https://m.instagram.com/p/SYNTHn8n01/?utm=x"})
        self.assertEqual(a["mission_id"], same_pub_other_url["mission_id"])
        tampered = copy.deepcopy(a)
        tampered["artifacts"][0]["sha256"] = sha("outro")
        self.assertTrue(any("não confere" in p for p in validate_mission(tampered)))

    def test_unsafe_uris_rejected(self):
        for uri in ("../../etc/passwd", "C:\\Users\\x\\.env", "/abs/path", "http://169.254.169.254/latest", "file:///etc",
                    "\\\\servidor\\share", "a/../../b", "ok\x00.json", ""):
            m = mission()
            m["artifacts"][0]["uri"] = uri
            m["mission_id"] = compute_mission_id(m)
            self.assertTrue(validate_mission(m), uri)

    def test_closed_contract_and_limits(self):
        m = mission(); m["extra"] = 1
        self.assertTrue(any("desconhecidas" in p for p in validate_mission(m)))
        m = mission(); m["artifacts"][0]["token"] = "x"
        self.assertTrue(validate_mission(m))
        m = mission(artifacts=[{"kind": "transcript", "sha256": sha(str(i)), "uri": f"a/{i}.json"} for i in range(65)])
        self.assertTrue(validate_mission(m))
        self.assertTrue(validate_mission(mission(requested_stages=["voar"])))
        self.assertTrue(validate_mission(mission(reference={"platform": "instagram", "url": "https://evil.example/reel/x"})))
        self.assertTrue(validate_mission("não é objeto"))

    def test_paid_models_need_explicit_approval(self):
        self.assertTrue(validate_mission(mission(budget={"allow_paid_models": True, "max_usd": 0})))
        self.assertTrue(validate_mission(mission(budget={"allow_paid_models": True, "max_usd": 0.5})))
        self.assertEqual(validate_mission(mission(budget={"allow_paid_models": True, "max_usd": 0.5, "approved_by": "human:rian"})), [])


class ResultAndSignatureTest(unittest.TestCase):
    def test_result_codes_and_next_actions(self):
        self.assertEqual(build_result("m", "awaiting_review")["next_action"], "await_review")
        self.assertEqual(build_result("m", "failed", error_code="TRANSIENT")["next_action"], "retry")
        self.assertEqual(build_result("m", "failed", error_code="MISSING_EVIDENCE")["next_action"], "provide_evidence")
        self.assertEqual(build_result("m", "failed", error_code="CONFLICT")["next_action"], "human")
        with self.assertRaises(ValueError):
            build_result("m", "failed", error_code="QUALQUER")
        bad = build_result("m", "failed", error_code="TRANSIENT"); bad["error"]["retryable"] = False
        self.assertTrue(validate_result(bad))
        self.assertTrue(validate_result({"schema_version": "ii.mission_result.v1", "state": "failed", "error": None}))

    def test_hmac(self):
        body = b'{"a":1}'
        sig = sign(body, SECRET)
        self.assertTrue(verify_signature(body, SECRET, sig))
        self.assertFalse(verify_signature(body + b" ", SECRET, sig))
        self.assertFalse(verify_signature(body, b"outro", sig))
        self.assertFalse(verify_signature(body, SECRET, None))
        self.assertFalse(verify_signature(body, b"", sig))


class GatewayTest(unittest.TestCase):
    def setUp(self):
        self.conn = open_database()
        self.addCleanup(self.conn.close)
        self.calls = []

        def executor(msg):
            self.calls.append(msg["mission_id"])
            if msg["requested_by"] == "n8n:flaky" and len(self.calls) == 1:
                return build_result(msg["mission_id"], "failed", error_code="TRANSIENT", error_message="disco ocupado")
            return build_result(msg["mission_id"], "awaiting_review", executed=msg["requested_stages"], analysis_id="an_x")
        self.gw = MissionGateway(self.conn, executor, SECRET)

    def send(self, msg, secret=SECRET):
        body = json.dumps(msg).encode()
        return self.gw.receive(body, sign(body, secret))

    def test_replay_is_idempotent(self):
        m = mission()
        r1, r2 = self.send(m), self.send(m)
        self.assertEqual(self.calls, [m["mission_id"]])
        self.assertTrue(r2["replayed"])
        self.assertEqual(r1["state"], r2["state"])

    def test_retryable_failure_is_executed_again(self):
        m = mission(requested_by="n8n:flaky")
        self.assertTrue(self.send(m)["error"]["retryable"])
        self.assertEqual(self.send(m)["state"], "awaiting_review")
        self.assertEqual(len(self.calls), 2)

    def test_bad_signature_and_bad_json_never_reach_executor(self):
        self.assertEqual(self.send(mission(), secret=b"errado")["error"]["code"], "VALIDATION_ERROR")
        body = b"{nao json"
        self.assertEqual(self.gw.receive(body, sign(body, SECRET))["state"], "rejected")
        bad = mission(); bad["artifacts"][0]["uri"] = "../x"
        self.assertEqual(self.send(bad)["state"], "rejected")
        self.assertEqual(self.calls, [])

    def test_secret_never_in_results(self):
        r = self.send(mission(), secret=b"errado")
        self.assertNotIn(SECRET.decode(), json.dumps(r))
        with self.assertRaises(ValueError):
            MissionGateway(self.conn, lambda m: {}, b"")

    def test_invalid_executor_output_becomes_transient(self):
        gw = MissionGateway(self.conn, lambda m: {"schema_version": "x"}, SECRET)
        body = json.dumps(mission()).encode()
        r = gw.receive(body, sign(body, SECRET))
        self.assertEqual(r["error"]["code"], "TRANSIENT")


if __name__ == "__main__":
    unittest.main()

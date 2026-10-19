"""Tarefas 05 e 07: fila persistente, posse/lease, política de nova tentativa, dead-letter e cancelamento."""
import json
import unittest

from tests._util import TempEngine
from ii_be.errors import (DependencyMissing, InvalidInput, PermanentError, ResourceBusy, RetryPolicy, StageTimeout,
                          TransientError)
from ii_be.queue import JobQueue, LeaseLost


def q_for(t, **kw):
    return JobQueue(t.engine.conn, t.clock, policy=kw.pop("policy", RetryPolicy(jitter=0.0, base_delay_s=10)), **kw)


class EnqueueAndClaimTest(unittest.TestCase):
    def test_dedup_of_active_requests(self):
        with TempEngine(memory=True) as t:
            q = q_for(t)
            a = q.enqueue("demo", dedup_key="k1")
            b = q.enqueue("demo", dedup_key="k1")
            self.assertTrue(a.created)
            self.assertEqual((b.job_id, b.created), (a.job_id, False))
            j = q.claim("w1")
            q.complete(j.job_id, "w1", {"ok": True})
            c = q.enqueue("demo", dedup_key="k1")   # terminal libera a chave: novo pedido é novo job
            self.assertTrue(c.created)
            self.assertNotEqual(c.job_id, a.job_id)

    def test_priority_and_not_before(self):
        with TempEngine(memory=True) as t:
            q = q_for(t)
            late = q.enqueue("demo", priority=1, delay_s=60).job_id
            low = q.enqueue("demo", priority=200).job_id
            high = q.enqueue("demo", priority=5).job_id
            self.assertEqual(q.claim("w").job_id, high)
            self.assertEqual(q.claim("w").job_id, low)
            self.assertIsNone(q.claim("w"))
            t.clock.advance(61)
            self.assertEqual(q.claim("w").job_id, late)

    def test_dependencies_gate_claim_and_promote(self):
        with TempEngine(memory=True) as t:
            q = q_for(t)
            a = q.enqueue("demo").job_id
            b = q.enqueue("demo", depends_on=[a])
            self.assertEqual(b.state, "waiting_dependency")
            j = q.claim("w")
            self.assertEqual(j.job_id, a)
            self.assertIsNone(q.claim("w2"))                     # b ainda bloqueado
            q.complete(a, "w", {})
            self.assertEqual(q.get(b.job_id)["state"], "queued")
            self.assertEqual(q.claim("w2").job_id, b.job_id)
            with self.assertRaises(ValueError):
                q.enqueue("demo", depends_on=["job_inexistente"])

    def test_concurrency_limits(self):
        with TempEngine(memory=True) as t:
            q = q_for(t, max_running=3, kind_limits={"transcribe": 1})
            for _ in range(3):
                q.enqueue("transcribe")
            q.enqueue("scenes"); q.enqueue("scenes"); q.enqueue("scenes")
            got = [q.claim(f"w{i}") for i in range(5)]
            kinds = [g.kind for g in got if g]
            self.assertEqual(len(kinds), 3)                      # limite global
            self.assertEqual(kinds.count("transcribe"), 1)       # limite por tipo


class LeaseTest(unittest.TestCase):
    def test_expired_lease_is_recovered_and_old_owner_cannot_write(self):
        with TempEngine(memory=True) as t:
            q = q_for(t, lease_s=30)
            jid = q.enqueue("demo").job_id
            q.claim("velho")
            q.mark_running(jid, "velho")
            t.clock.advance(31)
            j2 = q.claim("novo")                                 # recuperação acontece no claim
            self.assertIsNone(j2)                                # foi para retry_scheduled com backoff
            self.assertEqual(q.get(jid)["state"], "retry_scheduled")
            t.clock.advance(11)
            j2 = q.claim("novo")
            self.assertEqual(j2.job_id, jid)
            with self.assertRaises(LeaseLost):
                q.complete(jid, "velho", {"de": "velho"})
            with self.assertRaises(LeaseLost):
                q.heartbeat(jid, "velho")
            q.complete(jid, "novo", {"de": "novo"})
            self.assertEqual(q.get(jid)["result"], {"de": "novo"})
            self.assertEqual([a["outcome"] for a in q.attempts(jid)], ["lease_lost", "completed"])

    def test_heartbeat_keeps_the_lease(self):
        with TempEngine(memory=True) as t:
            q = q_for(t, lease_s=30)
            jid = q.enqueue("demo").job_id
            q.claim("w")
            for _ in range(5):
                t.clock.advance(20)
                self.assertFalse(q.heartbeat(jid, "w"))
                self.assertIsNone(q.claim("intruso"))
            q.complete(jid, "w", {})
            self.assertEqual(q.get(jid)["state"], "completed")


class RetryPolicyTest(unittest.TestCase):
    def run_failure(self, t, q, exc, jid):
        j = q.claim("w")
        self.assertEqual(j.job_id, jid)
        return q.fail(jid, "w", exc)

    def test_transient_backs_off_then_dead_letters_with_event(self):
        with TempEngine(memory=True) as t:
            q = q_for(t)
            jid = q.enqueue("demo", max_attempts=3).job_id
            delays = []
            for _ in range(3):
                d = self.run_failure(t, q, TransientError("disco ocupado"), jid)
                delays.append(d.delay_s)
                t.clock.advance(d.delay_s + 0.001)
            self.assertEqual(q.get(jid)["state"], "dead_letter")
            self.assertEqual(delays[:2], [10, 20])               # exponencial, sem jitter neste teste
            self.assertEqual(t.engine.conn.execute("SELECT COUNT(*) FROM be_outbox WHERE type='job.dead_letter'").fetchone()[0], 1)
            self.assertEqual([a["outcome"] for a in q.attempts(jid)], ["retry", "retry", "dead_letter"])
            self.assertIsNone(q.claim("w"))                      # nunca some e nunca volta sozinho

    def test_jitter_stays_within_bounds_and_cap(self):
        p = RetryPolicy(base_delay_s=10, max_delay_s=100, jitter=0.2)
        for n in range(1, 12):
            d = p.backoff(n)
            raw = min(100, 10 * 2 ** (n - 1))
            self.assertTrue(raw * 0.8 - 1e-9 <= d <= min(100, raw * 1.2) + 1e-9, (n, d))

    def test_each_error_class_has_its_destination(self):
        cases = [(InvalidInput("json quebrado"), "failed"), (PermanentError("bug"), "dead_letter"), (KeyError("x"), "dead_letter"),
                 (StageTimeout("lento"), "retry_scheduled"), (DependencyMissing("sem srt"), "waiting_dependency"),
                 (ResourceBusy("gpu"), "retry_scheduled")]
        for exc, expected in cases:
            with TempEngine(memory=True) as t:
                q = q_for(t)
                jid = q.enqueue("demo").job_id
                d = self.run_failure(t, q, exc, jid)
                self.assertEqual((d.state, q.get(jid)["state"]), (expected, expected), exc)
                self.assertEqual(q.get(jid)["last_error_class"], exc.error_class if hasattr(exc, "error_class") else "permanent")

    def test_busy_and_missing_dependency_have_own_budgets(self):
        with TempEngine(memory=True) as t:
            q = q_for(t, policy=RetryPolicy(jitter=0.0, max_busy_retries=3, max_dependency_waits=2, dependency_delay_s=5))
            b = q.enqueue("demo", max_attempts=2).job_id
            for i in range(4):
                d = self.run_failure(t, q, ResourceBusy("ocupado"), b)
                t.clock.advance(d.delay_s + 0.001)
            self.assertEqual(q.get(b)["state"], "dead_letter")
            self.assertEqual(q.get(b)["failures"], 0)            # ocupado não conta como falha
            m = q.enqueue("demo").job_id
            states = []
            for _ in range(3):
                d = self.run_failure(t, q, DependencyMissing("aguardando srt"), m)
                states.append(d.state)
                t.clock.advance(d.delay_s + 0.001)
            self.assertEqual(states, ["waiting_dependency", "waiting_dependency", "failed"])


class CancelAndRequeueTest(unittest.TestCase):
    def test_cancel_queued_cascades_and_running_is_cooperative(self):
        with TempEngine(memory=True) as t:
            q = q_for(t)
            a = q.enqueue("demo").job_id
            b = q.enqueue("demo", depends_on=[a]).job_id
            c = q.enqueue("demo", depends_on=[b]).job_id
            self.assertEqual(q.cancel(a), "cancelled")
            self.assertEqual({q.get(x)["state"] for x in (a, b, c)}, {"cancelled"})
            r = q.enqueue("demo").job_id
            q.claim("w")
            self.assertEqual(q.cancel(r), "cancel_requested")
            self.assertTrue(q.heartbeat(r, "w"))
            wrote = []
            self.assertEqual(q.complete(r, "w", {"x": 1}, effects=lambda c: wrote.append(1)), "cancelled")
            self.assertEqual(wrote, [])                          # cancelado nunca grava resultado
            self.assertIsNone(q.get(r)["result"])

    def test_requeue_dead_letter_preserves_history_and_unblocks_dependents(self):
        with TempEngine(memory=True) as t:
            q = q_for(t)
            a = q.enqueue("demo", max_attempts=1).job_id
            b = q.enqueue("demo", depends_on=[a]).job_id
            q.claim("w"); q.fail(a, "w", TransientError("x"))
            self.assertEqual(q.get(a)["state"], "dead_letter")
            self.assertEqual([x["job_id"] for x in q.blocked()], [b])
            self.assertEqual(q.requeue(a), "queued")
            q.claim("w"); q.complete(a, "w", {})
            self.assertEqual(q.claim("w").job_id, b)
            self.assertEqual([x["outcome"] for x in q.attempts(a)], ["dead_letter", "completed"])

    def test_no_infinite_retries_whatever_the_error(self):
        with TempEngine(memory=True) as t:
            q = q_for(t, policy=RetryPolicy(jitter=0.0, base_delay_s=1, max_busy_retries=5, max_dependency_waits=5, dependency_delay_s=1))
            for exc in (TransientError("t"), StageTimeout("t"), ResourceBusy("b"), DependencyMissing("d")):
                jid = q.enqueue("demo", max_attempts=4).job_id
                for _ in range(100):
                    j = q.claim("w")
                    if j is None:
                        t.clock.advance(10_000)
                        j = q.claim("w")
                        if j is None:
                            break
                    q.fail(j.job_id, "w", exc)
                self.assertIn(q.get(jid)["state"], ("dead_letter", "failed"), exc)
                self.assertLessEqual(len(q.attempts(jid)), 6)


if __name__ == "__main__":
    unittest.main()

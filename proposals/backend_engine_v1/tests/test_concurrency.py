"""Tarefa 19: concorrência realista com várias threads, cada uma com sua conexão ao mesmo banco (WAL).

Verifica que não existem duas gravações incompatíveis de resultado: cada etapa de cada referência tem exatamente
um resultado válido por impressão digital, cada vídeo tem uma análise, e o banco passa no integrity_check.
"""
import sqlite3
import threading
import time
import unittest

from tests._util import TempEngine
from ii_be.clock import SystemClock
from ii_be.db import tx
from ii_be.errors import RetryPolicy
from ii_be.events import Dispatcher, emit
from ii_be.queue import JobQueue
from ii_be.scheduler import MEDIA_GRAPH
from ii_be.synthetic import seed_media_reference
from ii_be.worker import SimulatedCrash
from ii_mm.db.migrations import connect

META = {"caption": "Tutorial CapCut passo a passo", "hashtags": ["#capcut"]}


def run_threads(n, fn):
    errors = []

    def wrap(i):
        try:
            fn(i)
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)
    ths = [threading.Thread(target=wrap, args=(i,)) for i in range(n)]
    for th in ths:
        th.start()
    for th in ths:
        th.join(60)
    return errors


class MultiWorkerTest(unittest.TestCase):
    def test_many_workers_many_references_each_stage_exactly_once(self):
        with TempEngine(clock=SystemClock()) as t:
            e = t.engine
            refs = [seed_media_reference(e, f"https://www.instagram.com/reel/SYNTHcc{i:03d}/", f"cc{i:03d}", metadata=META)["ingest"].reference_id
                    for i in range(6)]
            e.pump_events()
            planner = e.worker(owner="planner", kinds=["plan"])
            while planner.run_once():
                pass

            def work(i):
                w = e.worker(owner=f"w{i}", own_connection=True)
                try:
                    idle = 0
                    while idle < 3:
                        if w.run_once() is None:
                            idle += 1
                            time.sleep(0.01)
                        else:
                            idle = 0
                finally:
                    w.conn.close()
            self.assertEqual(run_threads(4, work), [])
            c = e.conn
            self.assertEqual(c.execute("SELECT COUNT(*) FROM be_jobs WHERE kind='stage' AND state <> 'completed'").fetchone()[0], 0)
            dup = c.execute("SELECT reference_id, stage, COUNT(*) FROM be_stage_results WHERE status='valid' GROUP BY reference_id, stage "
                            "HAVING COUNT(*) > 1").fetchall()
            self.assertEqual(dup, [])
            self.assertEqual(c.execute("SELECT COUNT(*) FROM be_stage_results").fetchone()[0], len(refs) * len(MEDIA_GRAPH.order))
            self.assertEqual(c.execute("SELECT COUNT(*) FROM analyses").fetchone()[0], len(refs))
            done_twice = c.execute("SELECT job_id FROM be_job_attempts WHERE outcome IN ('completed','reused') GROUP BY job_id "
                                   "HAVING COUNT(*) > 1").fetchall()
            self.assertEqual(done_twice, [])
            self.assertEqual(c.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            owners = {r[0] for r in c.execute("SELECT DISTINCT owner FROM be_job_attempts WHERE owner LIKE 'w%'")}
            self.assertGreater(len(owners), 1)                     # o trabalho foi de fato dividido

    def test_two_workers_racing_for_one_job(self):
        with TempEngine(clock=SystemClock()) as t:
            e = t.engine
            jid = e.queue.enqueue("demo").job_id
            got = []
            barrier = threading.Barrier(8)

            def race(i):
                conn = connect(e.db_path)
                try:
                    q = JobQueue(conn, e.clock)
                    barrier.wait()
                    j = q.claim(f"r{i}")
                    if j:
                        got.append(j.job_id)
                finally:
                    conn.close()
            self.assertEqual(run_threads(8, race), [])
            self.assertEqual(got, [jid])

    def test_concurrent_enqueue_with_same_dedup_key(self):
        with TempEngine(clock=SystemClock()) as t:
            e = t.engine
            ids = []
            barrier = threading.Barrier(8)

            def produce(i):
                conn = connect(e.db_path)
                try:
                    barrier.wait()
                    ids.append(JobQueue(conn, e.clock).enqueue("demo", dedup_key="mesmo-pedido").job_id)
                finally:
                    conn.close()
            self.assertEqual(run_threads(8, produce), [])
            self.assertEqual(len(set(ids)), 1)
            self.assertEqual(e.conn.execute("SELECT COUNT(*) FROM be_jobs").fetchone()[0], 1)


class FailureTest(unittest.TestCase):
    def test_worker_crash_before_commit_is_recovered_without_duplicate(self):
        with TempEngine(lease_s=60) as t:
            e = t.engine
            ref = seed_media_reference(e, "https://www.instagram.com/reel/SYNTHcrash1/", "crash1", metadata=META)["ingest"].reference_id
            e.plan(ref)
            crashed = []

            def crash(job):
                if job.stage == "classify" and not crashed:
                    crashed.append(job.job_id)
                    raise SimulatedCrash("queda simulada antes de gravar")
            w1 = e.worker(owner="w1", hooks={"before_complete": crash})
            with self.assertRaises(SimulatedCrash):
                w1.run_until_idle()
            job = e.queue.get(crashed[0])
            self.assertEqual((job["state"], job["lease_owner"]), ("running", "w1"))
            self.assertIsNone(e.queue.claim("w2"))               # lease ainda válido: ninguém toma
            t.clock.advance(61)
            e.queue.recover_expired()
            t.clock.advance(RetryPolicy(jitter=0.0).max_delay_s)
            w2 = e.worker(owner="w2")
            w2.run_until_idle()
            job = e.queue.get(crashed[0])
            self.assertEqual(job["state"], "completed")
            self.assertEqual([a["outcome"] for a in e.queue.attempts(crashed[0])], ["lease_lost", "completed"])
            self.assertEqual(e.conn.execute("SELECT COUNT(*) FROM analyses").fetchone()[0], 1)  # save_analysis idempotente
            self.assertEqual(e.conn.execute("SELECT COUNT(*) FROM be_stage_results WHERE stage='classify'").fetchone()[0], 1)

    def test_slow_stage_times_out_and_is_retried(self):
        with TempEngine(clock=SystemClock(), lease_s=5) as t:
            e = t.engine
            e.cfg.stage_timeout_s["probe"] = 0.3
            ref = seed_media_reference(e, "https://www.instagram.com/reel/SYNTHslow1/", "slow1", metadata=META)["ingest"].reference_id
            e.plan(ref)
            calls = []

            def slow_probe(ctx):
                calls.append(1)
                while True:
                    time.sleep(0.05)
                    ctx.check()                                   # cooperativo: para quando o worker cancela
            w = e.worker(owner="w", db_path=e.db_path, handlers={"probe": slow_probe})
            out = []
            for _ in range(3):
                r = w.run_once()
                out.append(r)
                if r and r["stage"] == "probe":
                    break
            probe = [r for r in out if r and r["stage"] == "probe"][0]
            self.assertEqual((probe["outcome"], probe["error_class"]), ("retry_scheduled", "timeout"))
            self.assertEqual(e.conn.execute("SELECT COUNT(*) FROM be_stage_results WHERE stage='probe'").fetchone()[0], 0)

    def _hold_write_lock(self, path, seconds, locked):
        def run():
            c = connect(path)
            try:
                c.execute("BEGIN IMMEDIATE")
                locked.set()
                time.sleep(seconds)
                c.execute("COMMIT")
            finally:
                c.close()
        th = threading.Thread(target=run)
        th.start()
        return th

    def test_busy_database_is_waited_for(self):
        with TempEngine(clock=SystemClock()) as t:
            e = t.engine
            jid = e.queue.enqueue("demo").job_id
            locked = threading.Event()
            th = self._hold_write_lock(e.db_path, 0.4, locked)
            locked.wait(5)
            t0 = time.monotonic()
            conn = connect(e.db_path)
            try:
                j = JobQueue(conn, e.clock).claim("w")
            finally:
                conn.close()
            th.join()
            self.assertEqual(j.job_id, jid)
            self.assertGreaterEqual(time.monotonic() - t0, 0.3)

    def test_database_locked_beyond_the_limit_fails_cleanly(self):
        from ii_be.db import Busy
        with TempEngine(clock=SystemClock()) as t:
            e = t.engine
            jid = e.queue.enqueue("demo").job_id
            locked = threading.Event()
            th = self._hold_write_lock(e.db_path, 2.5, locked)
            locked.wait(5)
            conn = connect(e.db_path)
            conn.execute("PRAGMA busy_timeout = 100")
            try:
                with self.assertRaises(Busy):
                    JobQueue(conn, e.clock).claim("w")
            finally:
                conn.close()
            th.join()
            self.assertEqual(e.queue.get(jid)["state"], "queued")   # nada pela metade

    def test_cancel_while_running_never_writes_a_result(self):
        with TempEngine() as t:
            e = t.engine
            ref = seed_media_reference(e, "https://www.instagram.com/reel/SYNTHcan01/", "can01", metadata=META)["ingest"].reference_id
            e.plan(ref)

            def cancel_me(job):
                if job.stage == "acquire":
                    e.queue.cancel(job.job_id, "operador cancelou")
            w = e.worker(owner="w", hooks={"before_complete": cancel_me})
            w.run_until_idle()
            self.assertEqual(e.conn.execute("SELECT COUNT(*) FROM be_stage_results").fetchone()[0], 0)
            states = {r[0] for r in e.conn.execute("SELECT state FROM be_jobs WHERE kind='stage'")}
            self.assertEqual(states, {"cancelled"})                # cancelamento em cascata do grafo inteiro

    def test_event_delivered_to_two_dispatchers_is_processed_once(self):
        with TempEngine(clock=SystemClock()) as t:
            e = t.engine
            with tx(e.conn) as c:
                for i in range(30):
                    emit(c, "export.ready", None, {"i": i}, 0.0, dedup_key=f"x{i}")
            seen = []
            lock = threading.Lock()

            def consume(i):
                conn = connect(e.db_path)
                try:
                    def h(c, ev):
                        with lock:
                            seen.append(ev["event_id"])
                    for _ in range(5):
                        Dispatcher(conn, "consumidor-unico", h).run_once()
                finally:
                    conn.close()
            self.assertEqual(run_threads(3, consume), [])
            rows = e.conn.execute("SELECT COUNT(*) FROM be_consumed WHERE consumer='consumidor-unico'").fetchone()[0]
            self.assertEqual(rows, 30)
            self.assertEqual(len(seen), len(set(seen)))            # nenhum efeito repetido


if __name__ == "__main__":
    unittest.main()

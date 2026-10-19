"""Benchmark sintético do backend (Tarefa 21). NÃO mede produção: dados sintéticos, contêiner Linux, SQLite em arquivo.

Uso (na pasta proposals/backend_engine_v1):
    python -X utf8 tools/bench_backend.py --sizes 82,1000,10000 --out <arquivo.json>

Fases por tamanho N (banco novo em pasta temporária para cada N):
  ingest            N registros (URL + legenda + hashtags + duração nos metadados), um por transação
  dedup             os mesmos N de novo (nada novo deve ser criado)
  enqueue           planejamento de todas as referências (grafo de metadados: 4 etapas cada)
  queue_1w/queue_4w vazão da fila com handlers triviais (custo da fila + outbox, sem ii_mm), 1 e 4 workers (threads)
  pipeline          etapas reais (assemble + classify do ii_mm + index + export desligado) para até `--pipeline-max` refs
  queries           mediana de buscas combinadas, perguntas de conhecimento e listagem paginada
  resume            M jobs presos em lease vencido: tempo de recuperação
  events            despacho de todo o outbox para um consumidor sem efeito
  incremental       nova versão de taxonomia: replanejar e reprocessar (classify refaz, index reaproveita)
  memory            pico do tracemalloc na ingestão (passada separada, para não distorcer os tempos)
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import sqlite3
import statistics
import sys
import tempfile
import threading
import time
import tracemalloc
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))

from ii_be.clock import FakeClock  # noqa: E402
from ii_be.engine import Engine  # noqa: E402
from ii_be.errors import RetryPolicy  # noqa: E402
from ii_be.events import Dispatcher  # noqa: E402
from ii_be.ingest import record_from_url  # noqa: E402
from ii_be import knowledge as K  # noqa: E402
from ii_be.search import list_references, search  # noqa: E402
from ii_be.stages import StageOutput  # noqa: E402
from ii_mm.db.migrations import connect  # noqa: E402

TITLES = ["Tutorial passo a passo de legendas no CapCut", "Automação com n8n e webhook em 5 minutos", "Motion design no After Effects",
          "Como usar o Premiere Pro para cortes rápidos", "Referência visual: paleta de cores e direção de arte",
          "Cupom de desconto no link na bio", "Cinematografia com lente anamórfica", "Você sabia? Curiosidade sobre IA"]


def records(n):
    for i in range(n):
        yield record_from_url(f"https://www.instagram.com/reel/SYNTHbench{i:06d}/",
                              metadata={"title": TITLES[i % len(TITLES)] + f" #{i}", "hashtags": ["#ia", f"#tema{i % 13}"],
                                        "author_handle": f"autor_{i % 97}", "duration_s": 30.0 + (i % 60)})


def timed(fn):
    t0 = time.perf_counter()
    r = fn()
    return time.perf_counter() - t0, r


def median_ms(fn, runs=15):
    vals = []
    for _ in range(runs):
        t0 = time.perf_counter()
        fn()
        vals.append((time.perf_counter() - t0) * 1000)
    return round(statistics.median(vals), 3)


def trivial_handlers():
    def h(ctx):
        return StageOutput({"ok": True, "stage": ctx.stage}, f"d-{ctx.stage}-{ctx.reference_id}")
    return {s: h for s in ("assemble", "classify", "index", "export")}


def drain(engine, n_workers, handlers=None, kinds=("stage",)):
    def work(i):
        w = engine.worker(owner=f"bw{i}", own_connection=True, kinds=list(kinds), handlers=handlers or {})
        try:
            idle = 0
            while idle < 2:
                if w.run_once() is None:
                    idle += 1
                else:
                    idle = 0
        finally:
            w.conn.close()
    ths = [threading.Thread(target=work, args=(i,)) for i in range(n_workers)]
    t0 = time.perf_counter()
    for t in ths:
        t.start()
    for t in ths:
        t.join()
    return time.perf_counter() - t0


def bench_size(n: int, pipeline_max: int) -> dict:
    out = {"n": n}
    tmp = Path(tempfile.mkdtemp(prefix=f"ii_be_bench_{n}_"))
    try:
        clock = FakeClock()
        e = Engine(str(tmp / "bench.sqlite"), root=tmp / "store", clock=clock, policy=RetryPolicy(jitter=0.0))
        recs = list(records(n))
        dt, _ = timed(lambda: [e.ingest(r) for r in recs])
        out["ingest"] = {"total_s": round(dt, 3), "per_record_ms": round(dt * 1000 / n, 3)}
        dt, res = timed(lambda: [e.ingest(r) for r in recs])
        out["dedup"] = {"total_s": round(dt, 3), "per_record_ms": round(dt * 1000 / n, 3), "new": sum(not r.duplicate for r in res),
                        "sources": e.conn.execute("SELECT COUNT(*) FROM be_sources").fetchone()[0]}
        refs = [r[0] for r in e.conn.execute("SELECT reference_id FROM refs ORDER BY reference_id")]
        dt, plans = timed(lambda: [e.plan(r) for r in refs])
        jobs = e.conn.execute("SELECT COUNT(*) FROM be_jobs").fetchone()[0]
        out["enqueue"] = {"total_s": round(dt, 3), "per_reference_ms": round(dt * 1000 / n, 3), "jobs": jobs}

        # vazão da fila com handlers triviais: 1 worker na metade dos jobs, 4 workers no resto
        half_refs = set(refs[: n // 2])
        e.conn.execute("UPDATE be_jobs SET priority = 1 WHERE reference_id IN (SELECT reference_id FROM refs ORDER BY reference_id LIMIT ?)", (n // 2,))
        before = e.conn.execute("SELECT COUNT(*) FROM be_jobs WHERE state='completed'").fetchone()[0]
        # 1 worker: processa até concluir os de prioridade 1
        w = e.worker(owner="b1", own_connection=True, kinds=["stage"], handlers=trivial_handlers())
        t0 = time.perf_counter()
        target = len(half_refs) * 4
        done = 0
        while done < target and w.run_once():
            done += 1
        dt1 = time.perf_counter() - t0
        w.conn.close()
        rest = e.conn.execute("SELECT COUNT(*) FROM be_jobs WHERE state <> 'completed' AND kind='stage'").fetchone()[0]
        dt4 = drain(e, 4, trivial_handlers())
        out["queue_1w"] = {"jobs": done, "total_s": round(dt1, 3), "jobs_per_s": round(done / dt1, 1) if dt1 else None}
        out["queue_4w"] = {"jobs": rest, "total_s": round(dt4, 3), "jobs_per_s": round(rest / dt4, 1) if dt4 else None}
        out["queue_integrity"] = {"left": e.conn.execute("SELECT COUNT(*) FROM be_jobs WHERE state <> 'completed' AND kind='stage'").fetchone()[0],
                                  "completed_twice": e.conn.execute("SELECT COUNT(*) FROM (SELECT job_id FROM be_job_attempts WHERE outcome IN "
                                                                    "('completed','reused') GROUP BY job_id HAVING COUNT(*) > 1)").fetchone()[0]}

        # pipeline real (ii_mm) num banco novo com até pipeline_max referências
        m = min(n, pipeline_max)
        e2 = Engine(str(tmp / "pipeline.sqlite"), root=tmp / "store2", clock=clock, policy=RetryPolicy(jitter=0.0))
        for r in recs[:m]:
            e2.ingest(r)
        for r in [x[0] for x in e2.conn.execute("SELECT reference_id FROM refs")]:
            e2.plan(r)
        t_pipe = drain(e2, 1)
        out["pipeline"] = {"references": m, "jobs": m * 4, "total_s": round(t_pipe, 3), "per_reference_ms": round(t_pipe * 1000 / m, 3),
                           "analyses": e2.conn.execute("SELECT COUNT(*) FROM analyses").fetchone()[0]}
        # incremental: taxonomia nova → classify refaz, index reaproveita se a classificação não mudar
        e2.cfg.taxonomy_version = "tax-benchmark-2"
        dt_plan, _ = timed(lambda: [e2.plan(r[0]) for r in e2.conn.execute("SELECT reference_id FROM refs").fetchall()])
        t_re = drain(e2, 1)
        oc = {r[0]: r[1] for r in e2.conn.execute(
            "SELECT j.stage || ':' || a.outcome, COUNT(*) FROM be_job_attempts a JOIN be_jobs j ON j.job_id = a.job_id "
            "WHERE a.attempt_id > (SELECT COUNT(*) FROM be_jobs WHERE kind='stage') - 0 GROUP BY 1")}
        reran = e2.conn.execute("SELECT COUNT(*) FROM be_job_attempts a JOIN be_jobs j ON j.job_id = a.job_id WHERE j.stage='classify'").fetchone()[0]
        reused_index = e2.conn.execute("SELECT COUNT(*) FROM be_job_attempts a JOIN be_jobs j ON j.job_id = a.job_id "
                                       "WHERE j.stage='index' AND a.outcome='reused'").fetchone()[0]
        out["incremental"] = {"replan_s": round(dt_plan, 3), "reprocess_s": round(t_re, 3), "classify_attempts_total": reran,
                              "index_reused": reused_index, "full_pipeline_s": out["pipeline"]["total_s"]}

        # consultas sobre o banco do pipeline (tem análises) e listagem sobre o banco grande
        c2 = e2.conn
        out["queries"] = {
            "search_category_text_ms": median_ms(lambda: search(c2, {"category": "tutorial", "text": "capcut"}, limit=50)),
            "search_zero_result_ms": median_ms(lambda: search(c2, {"tool": "FerramentaInexistente"}, limit=50)),
            "search_evidence_status_ms": median_ms(lambda: search(c2, {"evidence_status": "metadata_claim"}, limit=50)),
            "knowledge_automation_ms": median_ms(lambda: K.automation_processes(c2, 50)),
            "knowledge_mentioned_not_demonstrated_ms": median_ms(lambda: K.tools_mentioned_not_demonstrated(c2, 50)),
            "list_references_first_page_ms": median_ms(lambda: list_references(e.conn, limit=50)),
            "list_references_text_ms": median_ms(lambda: list_references(e.conn, text="automação webhook", limit=50)),
        }
        cur, pages = None, 0
        t0 = time.perf_counter()
        while True:
            pg = list_references(e.conn, cursor=cur, limit=100)
            pages += 1
            cur = pg["next_cursor"]
            if not cur:
                break
        out["queries"]["list_all_pages"] = {"pages": pages, "total_ms": round((time.perf_counter() - t0) * 1000, 3)}

        # retomada: M jobs presos (dono caiu) num banco limpo
        mres = min(n, 1000)
        e3 = Engine(str(tmp / "resume.sqlite"), clock=clock, policy=RetryPolicy(jitter=0.0), lease_s=60)
        with sqlite3.connect(str(tmp / "resume.sqlite")):
            pass
        for i in range(mres):
            e3.queue.enqueue("demo", dedup_key=f"r{i}")
        for i in range(mres):
            e3.queue.claim("morto")
        clock.advance(61)
        dt, nrec = timed(e3.queue.recover_expired)
        out["resume"] = {"stuck_jobs": mres, "recovered": nrec, "total_ms": round(dt * 1000, 3)}
        e3.close()

        # eventos: despacho de todo o outbox do banco grande
        n_events = e.conn.execute("SELECT COUNT(*) FROM be_outbox").fetchone()[0]
        dt, st = timed(lambda: Dispatcher(e.conn, "bench", lambda c, ev: None).run_once(limit=n_events + 10))
        out["events"] = {"events": n_events, "dispatch_s": round(dt, 3), "per_event_ms": round(dt * 1000 / max(1, n_events), 4),
                         "processed": st["processed"]}
        out["db_size_mb"] = round((tmp / "bench.sqlite").stat().st_size / 1e6, 2)
        e.close()
        e2.close()

        # memória: passada separada (tracemalloc distorce tempos)
        e4 = Engine(str(tmp / "mem.sqlite"), clock=clock)
        tracemalloc.start()
        for r in recs:
            e4.ingest(r)
        cur_b, peak_b = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        out["memory"] = {"ingest_peak_mb": round(peak_b / 1e6, 2), "ingest_retained_mb": round(cur_b / 1e6, 2)}
        e4.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sizes", default="82,1000,10000")
    ap.add_argument("--pipeline-max", type=int, default=1000)
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    env = {"python": platform.python_version(), "sqlite": sqlite3.sqlite_version, "machine": platform.machine(),
           "system": platform.system(), "cpu_count": os.cpu_count()}
    try:
        meminfo = Path(os.sep, "proc", "meminfo")  # só existe no Linux; no Windows o campo fica ausente
        env["mem_total_kb"] = int(next(l for l in meminfo.read_text(encoding="utf-8").splitlines() if l.startswith("MemTotal")).split()[1])
    except (OSError, StopIteration, ValueError):
        pass
    results = {"environment": env, "methodology": __doc__.strip().splitlines()[0], "sizes": []}
    for n in [int(x) for x in a.sizes.split(",")]:
        r = bench_size(n, a.pipeline_max)
        results["sizes"].append(r)
        print(json.dumps(r, ensure_ascii=False), flush=True)
    if a.out:
        Path(a.out).write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

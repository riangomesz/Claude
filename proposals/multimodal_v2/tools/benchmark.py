"""Benchmark reproduzível com dados SINTÉTICOS (Tarefa 17).

Uso:  python3 tools/benchmark.py [--sizes 82,1000,10000] [--seed 7] [--out benchmarks/resultados_benchmark.json]

As cargas (82 / 1.000 / 10.000) são volumes de teste, NÃO o tamanho real do catálogo do projeto.
Os números valem para o ambiente registrado no JSON e não são garantia de desempenho em produção.
Mede: classificação, inserção (1 transação por análise), reenvio idempotente, aliases, consultas
(1ª página, página profunda por cursor vs OFFSET, filtros), varredura paginada vs fetchall (memória)
e retomada do pipeline após interrupção.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import resource
import sqlite3
import statistics
import sys
import tempfile
import time
import tracemalloc
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
sys.dont_write_bytecode = True

from ii_mm.catalog import Query, build_sql, iterate, search  # noqa: E402
from ii_mm.classifier import Classifier  # noqa: E402
from ii_mm.db.migrations import open_database  # noqa: E402
from ii_mm.db.repository import Repository  # noqa: E402
from ii_mm.pipeline import STAGES, Pipeline  # noqa: E402
from ii_mm.synthetic import make_reference  # noqa: E402


def ms(t0: float) -> float:
    return round((time.perf_counter() - t0) * 1000, 2)


def timed(fn, repeat=5):
    vals = []
    for _ in range(repeat):
        t0 = time.perf_counter()
        fn()
        vals.append((time.perf_counter() - t0) * 1000)
    return {"median_ms": round(statistics.median(vals), 3), "min_ms": round(min(vals), 3), "max_ms": round(max(vals), 3), "n": repeat}


def environment():
    mem_kb = None
    try:
        with open("/proc/meminfo") as f:
            mem_kb = int(next(l for l in f if l.startswith("MemTotal")).split()[1])
    except Exception:
        pass
    return {"python": sys.version.split()[0], "sqlite": sqlite3.sqlite_version, "platform": platform.platform(),
            "machine": platform.machine(), "cpu_count": os.cpu_count(), "mem_total_mb": mem_kb and mem_kb // 1024,
            "processor": platform.processor() or None, "journal_mode": "WAL (arquivo temporário em disco)"}


def run_size(n: int, seed: int, workdir: Path) -> dict:
    out: dict = {"records": n}
    clf = Classifier()
    t0 = time.perf_counter()
    docs = [clf.classify(make_reference(i, seed)) for i in range(n)]
    out["classify_total_ms"] = ms(t0)
    out["classify_per_doc_ms"] = round(out["classify_total_ms"] / n, 4)
    out["evidence_total"] = sum(len(d["evidence"]) for d in docs)

    db = workdir / f"bench_{n}.sqlite"
    conn = open_database(db)
    repo = Repository(conn)
    tracemalloc.start()
    t0 = time.perf_counter()
    for d in docs:
        repo.save_analysis(d)
    out["insert_total_ms"] = ms(t0)
    out["insert_peak_python_mb"] = round(tracemalloc.get_traced_memory()[1] / 2**20, 2)
    tracemalloc.stop()
    out["insert_per_doc_ms"] = round(out["insert_total_ms"] / n, 4)
    out["db_size_mb"] = round(db.stat().st_size / 2**20, 2) if db.exists() else None

    t0 = time.perf_counter()
    created = sum(repo.save_analysis(d).created for d in docs[: max(1, n // 10)])
    out["resave_10pct_ms"] = ms(t0)
    out["resave_new_rows"] = created
    dup = docs[: max(1, n // 20)]
    t0 = time.perf_counter()
    for d in dup:
        url = d["reference"]["origin_url"]
        alt = url.replace("www.instagram.com/reel/", "m.instagram.com/p/") if "instagram" in url else None
        repo.save_analysis(d, seen_url=alt)
    out["url_variant_resave_5pct_ms"] = ms(t0)  # variantes de URL colapsam na mesma chave canônica
    counts = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("refs", "videos", "analyses", "evidence", "ref_aliases")}
    out["row_counts"] = counts
    out["duplicates_created"] = counts["analyses"] - n

    page = 50
    deep = max(0, min(n - page, (n // page // 2) * page))  # meio do catálogo
    q = Query()
    out["query_first_page"] = timed(lambda: search(conn, q, limit=page))
    cur = None
    steps = deep // page
    for _ in range(steps):
        cur = search(conn, q, cur, page).next_cursor
    out["deep_page_offset_rows"] = deep
    out["query_deep_page_cursor"] = timed(lambda: search(conn, q, cur, page))
    base_sql, base_args = build_sql(q, None, page)
    off_sql = base_sql.replace(" LIMIT ?", " LIMIT ? OFFSET ?")
    out["query_deep_page_offset"] = timed(lambda: conn.execute(off_sql, base_args + [deep]).fetchall())
    out["query_category"] = timed(lambda: search(conn, Query(category="tutorial", min_support="mentioned_speech"), limit=page))
    out["query_tool_visual"] = timed(lambda: search(conn, Query(tool="ToolAlpha", tool_visual_only=True), limit=page))
    out["query_subject"] = timed(lambda: search(conn, Query(subject="workflow n8n"), limit=page))
    out["query_platform_author"] = timed(lambda: search(conn, Query(platform="youtube", author="autor_07"), limit=page))

    tracemalloc.start()
    t0 = time.perf_counter()
    k = sum(1 for _ in iterate(conn, Query(), page_size=100))
    out["scan_paginated"] = {"ms": ms(t0), "rows": k, "peak_python_mb": round(tracemalloc.get_traced_memory()[1] / 2**20, 3)}
    tracemalloc.stop()
    tracemalloc.start()
    t0 = time.perf_counter()
    rows = conn.execute("SELECT document_json FROM analyses WHERE status = 'current'").fetchall()
    loaded = [json.loads(r[0]) for r in rows]
    out["scan_fetchall_documents"] = {"ms": ms(t0), "rows": len(loaded), "peak_python_mb": round(tracemalloc.get_traced_memory()[1] / 2**20, 3)}
    tracemalloc.stop()
    del rows, loaded

    out["resume"] = resume_benchmark(conn, min(n, 1000))
    conn.close()
    return out


def resume_benchmark(conn, n_videos: int) -> dict:
    vids = [r[0] for r in conn.execute("SELECT video_pk FROM videos ORDER BY video_pk LIMIT ?", (n_videos,))]
    calls = {"count": 0}
    crash_at = {"remaining": len(vids) * len(STAGES) // 2}

    def handler(stage):
        def h(ctx):
            calls["count"] += 1
            crash_at["remaining"] -= 1
            if crash_at["remaining"] == 0:
                raise KeyboardInterrupt  # simula queda do processo no meio do lote
            return f"{stage}:{ctx.video_pk}"
        return h

    handlers = {s: handler(s) for s in STAGES}
    p = Pipeline(conn, handlers)
    t0 = time.perf_counter()
    try:
        for v in vids:
            p.run(v)
    except KeyboardInterrupt:
        pass
    first_ms, first_calls = ms(t0), calls["count"]
    calls["count"] = 0
    t0 = time.perf_counter()
    for v in vids:
        p.run(v)
    second_ms, second_calls = ms(t0), calls["count"]
    calls["count"] = 0
    t0 = time.perf_counter()
    for v in vids:
        p.run(v)
    third_ms = ms(t0)
    total = len(vids) * len(STAGES)
    return {"videos": len(vids), "stage_executions_needed": total, "before_crash": first_calls, "after_resume": second_calls,
            "repeated_executions": first_calls + second_calls - total, "rerun_all_done_calls": calls["count"],
            "ms_before_crash": first_ms, "ms_resume": second_ms, "ms_noop_rerun": third_ms}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sizes", default="82,1000,10000")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out", default=str(HERE / "benchmarks" / "resultados_benchmark.json"))
    a = ap.parse_args()
    sizes = [int(x) for x in a.sizes.split(",")]
    result = {"methodology": __doc__.strip(), "seed": a.seed, "environment": environment(), "runs": []}
    with tempfile.TemporaryDirectory(prefix="ii_bench_") as tmp:
        for n in sizes:
            t0 = time.perf_counter()
            r = run_size(n, a.seed, Path(tmp))
            r["wall_total_s"] = round(time.perf_counter() - t0, 2)
            result["runs"].append(r)
            print(f"n={n}: insert {r['insert_per_doc_ms']} ms/doc, 1ª página {r['query_first_page']['median_ms']} ms, "
                  f"profunda cursor {r['query_deep_page_cursor']['median_ms']} ms vs offset {r['query_deep_page_offset']['median_ms']} ms",
                  flush=True)
    result["max_rss_mb"] = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("resultado:", a.out)


if __name__ == "__main__":
    main()

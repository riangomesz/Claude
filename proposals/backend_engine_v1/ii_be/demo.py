"""Demonstração isolada e reproduzível do backend inteiro (Tarefa 22). SÓ dados sintéticos.

Uso (na pasta proposals/backend_engine_v1):  python -X utf8 -m ii_be.demo [--keep PASTA]

Percorre os 18 passos: receber referências → normalizar origem → deduplicar → criar jobs → resolver dependências →
receber artefatos simulados → validar integridade → normalizar evidências → classificar com o ii_mm → persistir →
indexar conhecimento → revisão humana → atualizar o índice → exportar para staging do Obsidian → gerar eventos
para o n8n (arquivo JSONL, sem rede) → simular queda → retomar → provar que não houve duplicação nem perda.

O relógio é manual e todos os ids são determinísticos: duas execuções produzem o MESMO resumo (o teste confere).
Nada sai da pasta de trabalho; nenhum vídeo real é lido; nenhum serviço externo é chamado.
"""
from __future__ import annotations

import argparse
import collections
import json
import tempfile
from pathlib import Path
from typing import Any, Dict

from . import _ii_mm  # noqa: F401
from . import artifacts as A
from . import incremental as I
from . import knowledge as K
from .clock import FakeClock
from .curation import CurationService
from .engine import Engine
from .errors import RetryPolicy
from .events import Dispatcher, JsonlSink, outbox_counts
from .ingest import record_from_url, records_from_meta_export
from .synthetic import fake_video, tool_outputs
from .worker import SimulatedCrash

IG_URL = "https://www.instagram.com/reel/SYNTHe2e01/?igsh=SYNTHcompartilhamento"
YT_URL = "https://www.youtube.com/watch?v=SYNTHe2e002&si=SYNTHrastreio"
META_EXPORT = {"saved_saved_media": [
    {"title": "autor_e2e", "string_map_data": {"Saved on": {"href": "https://www.instagram.com/p/SYNTHe2e01/", "timestamp": 1760000000}}},
    {"title": "autor_meta", "string_map_data": {"Saved on": {"href": "https://www.instagram.com/reel/SYNTHe2e03/", "timestamp": 1760000500}}}]}


def _stage_runs(e, ref):
    rows = e.conn.execute("SELECT j.stage, a.outcome FROM be_job_attempts a JOIN be_jobs j ON j.job_id = a.job_id "
                          "WHERE j.reference_id = ? AND j.kind = 'stage' ORDER BY a.attempt_id", (ref,)).fetchall()
    return [f"{r['stage']}:{r['outcome']}" for r in rows]


def run_demo(workdir: Path) -> Dict[str, Any]:
    workdir = Path(workdir)
    clock = FakeClock()
    e = Engine(str(workdir / "backend_demo.sqlite"), root=workdir / "store", export_dir=workdir / "obsidian_staging",
               clock=clock, lease_s=120, policy=RetryPolicy(jitter=0.0, base_delay_s=5))
    out: Dict[str, Any] = {"synthetic": True}
    try:
        # 1-3. receber, normalizar origem, deduplicar
        video = fake_video("e2e-video-compartilhado")
        e.store.write_bytes("media/ig_e2e.mp4", video)
        e.store.write_bytes("media/yt_e2e.mp4", video)  # mesmo conteúdo republicado em outra plataforma
        from .ingest import record_from_local_file
        ig = e.ingest(record_from_local_file("media/ig_e2e.mp4", url=IG_URL, metadata={
            "caption": "Legendas automáticas no CapCut em 1 minuto", "hashtags": ["#capcut", "#tutorial"], "author_handle": "autor_e2e"}))
        yt = e.ingest(record_from_local_file("media/yt_e2e.mp4", url=YT_URL, metadata={"title": "CapCut: legendas automáticas (repost)"}))
        recs, errs = records_from_meta_export(META_EXPORT, "saved_posts.json")
        meta = [e.ingest(r) for r in recs]
        manual = e.ingest(record_from_url("https://youtu.be/SYNTHe2e004", metadata={"title": "Automação passo a passo no n8n", "duration_s": 75.0}))
        dup = e.ingest(record_from_url("https://www.instagram.com/reel/SYNTHe2e01/"))
        refs = {"instagram_media": ig.reference_id, "youtube_repost": yt.reference_id, "meta_only": meta[1].reference_id,
                "manual_metadata": manual.reference_id}
        out["1_received"] = {"records": 2 + len(recs) + 2, "export_errors": len(errs)}
        out["2_normalized_origin"] = {k: e.conn.execute("SELECT canonical_key, origin_url FROM refs WHERE reference_id = ?", (v,)).fetchone()[:]
                                      for k, v in refs.items()}
        out["3_dedup"] = {"references": e.conn.execute("SELECT COUNT(*) FROM refs").fetchone()[0],
                          "meta_export_item_matched_existing": meta[0].reference_id == ig.reference_id,
                          "duplicate_record_detected": dup.reference_id == ig.reference_id,
                          "shared_media_references": len({r[0] for r in e.conn.execute(
                              "SELECT reference_id FROM be_artifacts WHERE kind='video' AND sha256 = ?", (A.current(e.conn, ig.reference_id, "video")["sha256"],))})}

        # 4-5. criar jobs e resolver dependências (antes dos artefatos de ferramentas: probe fica aguardando)
        e.pump_events()
        e.worker(owner="planejador", kinds=["plan"]).run_until_idle()
        out["4_jobs_created"] = dict(collections.Counter(r[0] for r in e.conn.execute("SELECT kind FROM be_jobs")))
        blocked = e.conn.execute("SELECT COUNT(*) FROM be_jobs WHERE kind='stage' AND state='waiting_dependency'").fetchone()[0]
        out["5_dependencies"] = {"waiting_for_dependencies": blocked, "ready": e.conn.execute(
            "SELECT COUNT(*) FROM be_jobs WHERE kind='stage' AND state='queued'").fetchone()[0],
            "metadata_only_without_duration": e.plan(refs["meta_only"]).graph}

        # 6-7. artefatos simulados das ferramentas + integridade
        outs = tool_outputs()
        for name, ref in (("ig", ig.reference_id), ("yt", yt.reference_id)):
            for kind, data in outs.items():
                rel = f"tools/{name}/{kind}"
                e.store.write_bytes(rel, data)
                e.register_artifact(ref, kind, rel, origin="agent:demo-observador" if kind == "observations" else f"tool:{kind}")
        e.store.write_bytes("tools/ig/srt_corrompido", b"conteudo trocado no caminho")
        bad = e.register_artifact(ig.reference_id, "srt", "tools/ig/srt_corrompido", origin="tool:whisper", expected_sha256="0" * 64)
        out["6_artifacts_registered"] = e.conn.execute("SELECT COUNT(*) FROM be_artifacts").fetchone()[0]
        out["7_integrity"] = {"corrupt_detected": bad["state"], "current_srt_version": A.current(e.conn, ig.reference_id, "srt")["version"]}

        # 8-11 e 16. processar; a classificação do repost cai antes de gravar (queda simulada)
        crashed = []

        def crash(job):
            if job.stage == "classify" and job.reference_id == yt.reference_id and not crashed:
                crashed.append(job.job_id)
                raise SimulatedCrash("queda simulada do worker A")
        worker_a = e.worker(owner="worker-A", hooks={"before_complete": crash})
        try:
            for _ in range(10):
                e.pump_events()
                if not worker_a.run_until_idle():
                    break
        except SimulatedCrash:
            pass
        for _ in range(10):  # o restante segue em outro worker; o job do repost continua preso no lease do A
            e.pump_events()
            if not e.worker(owner="worker-B").run_until_idle():
                break
        ig_cls = I.current_result(e.conn, ig.reference_id, "classify")["result"]
        out["8_evidence_normalized"] = I.current_result(e.conn, ig.reference_id, "assemble")["result"]["evidence"]
        out["9_classified_by_ii_mm"] = {"categories": ig_cls["categories"], "tools": ig_cls["tools"]}
        out["10_persisted"] = {"analyses": e.conn.execute("SELECT COUNT(*) FROM analyses").fetchone()[0],
                               "videos": e.conn.execute("SELECT COUNT(*) FROM videos").fetchone()[0]}
        out["11_knowledge_indexed"] = {"teaching_capcut": [r["reference_id"] == ig.reference_id for r in K.videos_teaching_tool(e.conn, "CapCut")],
                                       "techniques": K.techniques_by_evidence_level(e.conn)}
        job = e.queue.get(crashed[0])
        out["16_interruption"] = {"job_state": job["state"], "lease_owner": job["lease_owner"], "stage": job["stage"]}

        # 12-13. revisão humana e atualização do índice (só index/export refazem)
        cur = CurationService(e.conn, clock)
        cur.decide(ig.reference_id, "triage", "human:curador", value="manter")
        cur.decide(ig.reference_id, "rating", "human:curador", value="excelente")
        cur.decide(ig.reference_id, "reject_category", "human:curador", reason="oferta é do criador, não tema do vídeo", category="marketing_vendas")
        cur.decide(ig.reference_id, "reject_hypothesis", "human:curador", reason="a legenda não muda entre os quadros", technique="legenda_animada")
        before = len(_stage_runs(e, ig.reference_id))
        e.run(worker=e.worker(owner="worker-B"))
        out["12_human_review"] = {"history": len(cur.history(ig.reference_id)), "etag": cur.etag(ig.reference_id)}
        out["13_index_updated"] = {"reran": _stage_runs(e, ig.reference_id)[before:],
                                   "marketing_vendas": [x["status"] for x in K.knowledge_for(e.conn, ig.reference_id)
                                                        if x["facet"] == "categoria" and x["value"] == "marketing_vendas"]}

        # 14-15. exportação em staging e eventos para integração futura (JSONL, sem rede)
        notes = sorted(p.name for p in (workdir / "obsidian_staging").glob("*.md"))
        out["14_obsidian_staging"] = {"notes": len(notes)}
        sink = workdir / "n8n_staging" / "eventos.jsonl"
        Dispatcher(e.conn, "n8n_staging", JsonlSink(sink), clock=clock).run_once(limit=10_000)
        out["15_events_for_n8n"] = {"outbox_by_type": outbox_counts(e.conn), "jsonl_lines": len(sink.read_text(encoding="utf-8").splitlines())}

        # 17. retomar: o lease do worker A vence; o worker C recupera e conclui
        clock.advance(121)
        e.queue.recover_expired()
        clock.advance(10)
        e.run(worker=e.worker(owner="worker-C"))
        out["17_resumed"] = {"attempts": [a["outcome"] for a in e.queue.attempts(crashed[0])],
                             "youtube_state": e.processing(yt.reference_id)["ii_mm_equivalent"]}

        # 18. sem duplicação nem perda de histórico
        c = e.conn
        out["18_verification"] = {
            "references": c.execute("SELECT COUNT(*) FROM refs").fetchone()[0],
            "stage_results_duplicated": c.execute("SELECT COUNT(*) FROM (SELECT 1 FROM be_stage_results WHERE status='valid' "
                                                  "GROUP BY reference_id, stage, fingerprint HAVING COUNT(*) > 1)").fetchone()[0],
            "jobs_completed_twice": c.execute("SELECT COUNT(*) FROM (SELECT job_id FROM be_job_attempts WHERE outcome IN ('completed','reused') "
                                              "GROUP BY job_id HAVING COUNT(*) > 1)").fetchone()[0],
            "videos": c.execute("SELECT COUNT(*) FROM videos").fetchone()[0],
            "analyses": c.execute("SELECT COUNT(*) FROM analyses").fetchone()[0],
            "human_history_kept": len(cur.history(ig.reference_id)),
            "events_consumed_once": c.execute("SELECT COUNT(*) FROM be_consumed GROUP BY consumer, event_id HAVING COUNT(*) > 1").fetchall() == [],
            "integrity_check": c.execute("PRAGMA integrity_check").fetchone()[0],
            "pending_jobs": e.diagnostics()["jobs"]["pending"],
        }
        out["note"] = "Dados sintéticos. Não é análise de vídeo real nem medição de desempenho de produção."
    finally:
        e.close()
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep", help="pasta NOVA para manter banco, artefatos, notas e eventos")
    a = ap.parse_args(argv)
    if a.keep:
        p = Path(a.keep)
        if p.exists() and any(p.iterdir()):
            raise SystemExit(f"recusado: {p} já existe com conteúdo (use uma pasta nova)")
        p.mkdir(parents=True, exist_ok=True)
        print(json.dumps(run_demo(p), ensure_ascii=False, indent=2, default=list))
    else:
        with tempfile.TemporaryDirectory(prefix="ii_be_demo_") as t:
            print(json.dumps(run_demo(Path(t)), ensure_ascii=False, indent=2, default=list))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

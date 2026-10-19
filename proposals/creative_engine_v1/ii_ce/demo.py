"""Demonstração ponta a ponta do motor criativo. SÓ dados sintéticos e especialistas MOCK.

Uso (na pasta proposals/creative_engine_v1):  python -X utf8 -m ii_ce.demo [--out PASTA]

Percorre: ingestão e pipeline do ii_be → investigação → planejamento → especialistas simulados → queda e retomada →
reconciliação (com divergência) → decisões humanas → dossiê (versionado, idempotente) → exportação Obsidian (staging) →
eventos JSONL para o n8n → nova investigação sem apagar revisões. Relógio manual: duas execuções geram os mesmos arquivos.
O vídeo piloto DQV5dm6gCvH NÃO está neste ambiente: nada aqui foi assistido, tudo vem de fixtures do ii_be/ii_mm."""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict

from . import _be  # noqa: F401
from ii_be.clock import FakeClock
from ii_be.engine import Engine
from ii_be.errors import RetryPolicy
from ii_be.synthetic import seed_media_reference
from .events import JsonlSink
from .orchestrator import CreativeEngine
from .providers import MockSpecialist, SimulatedInterrupt

BANNER = "DADOS SINTÉTICOS DE DEMONSTRAÇÃO — nenhum vídeo real foi assistido; especialistas são MOCK"
SPECS = ("audiovisual", "reproducao", "criativo", "implementacao")


def run_demo(workdir: Path) -> Dict[str, Any]:
    workdir = Path(workdir)
    clock = FakeClock()
    eng = Engine(str(workdir / "backend_demo.sqlite"), root=workdir / "store", export_dir=workdir / "obsidian_staging_ii_mm", clock=clock, policy=RetryPolicy(jitter=0.0))
    out: Dict[str, Any] = {"synthetic": True, "banner": BANNER, "pilot_DQV5dm6gCvH": "BLOQUEADO: vídeo e artefatos não disponíveis neste ambiente; usadas fixtures"}
    checks: Dict[str, bool] = {}
    try:
        # 1-2. ingerir e recuperar artefatos (pipeline real do ii_be sobre saídas sintéticas de ferramentas)
        seeded = seed_media_reference(eng, "https://www.instagram.com/reel/SYNTHce0001/", "ce-demo-1", metadata={"caption": "Fluxo de automação com n8n e motion"})
        ref = seeded["ingest"].reference_id
        eng.run()
        out["reference_id"] = ref
        fired = {"done": False}

        def interrupt_once(request):
            if request["specialist"] == "criativo" and not fired["done"]:
                fired["done"] = True
                raise SimulatedInterrupt("queda simulada no meio da tarefa")

        def providers(with_interrupt: bool):
            return {"audiovisual": MockSpecialist("audiovisual"), "reproducao": MockSpecialist("reproducao"),
                    "criativo": MockSpecialist("criativo", behavior="contradict", on_call=interrupt_once if with_interrupt else None),
                    "implementacao": MockSpecialist("implementacao")}

        ce = CreativeEngine(engine=eng, providers=providers(True), profiles_dir=Path(__file__).resolve().parents[1] / "profiles", lease_s=120)
        ce.banner = BANNER
        # 3-4. criar investigação e planejar especialistas (cada escolha tem motivo)
        op = ce.open_investigation(ref, depth="deep", requested_by="human:demo")
        inv = op["investigation_id"]
        out["plan"] = {"reference_kind": op["reference_kind"], "tasks": [{"specialist": t["specialist"], "selected": t["selected"], "reason": t["reason"]} for t in op["plan"]["tasks"]]}
        checks["investigacao_idempotente"] = ce.open_investigation(ref, depth="deep", requested_by="human:demo")["investigation_id"] == inv
        # 5-6. executar especialistas simulados; 15. queda no meio
        interrupted = False
        try:
            ce.run(inv)
        except SimulatedInterrupt:
            interrupted = True
        st = {t["specialist"]: t["state"] for t in ce.status(inv)["tasks"]}
        checks["queda_deixou_tarefa_em_execucao"] = interrupted and st.get("criativo") == "running"
        # retomada por outro processo (novo objeto, mesmo banco), depois do vencimento do lease
        clock.advance(300)
        ce2 = CreativeEngine(engine=eng, providers=providers(False), profiles_dir=ce.profiles_dir, lease_s=120)
        ce2.banner = BANNER
        res = ce2.run(inv)
        out["run_after_resume"] = res
        # 16. sem duplicação
        n_claims = eng.conn.execute("SELECT COUNT(*) FROM ce_claims WHERE investigation_id = ?", (inv,)).fetchone()[0]
        n_distinct = eng.conn.execute("SELECT COUNT(*) FROM (SELECT DISTINCT task_id, key, value, statement FROM ce_claims WHERE investigation_id = ?)", (inv,)).fetchone()[0]
        calls = eng.conn.execute("SELECT specialist, attempts FROM ce_tasks WHERE investigation_id = ?", (inv,)).fetchall()
        checks["sem_afirmacoes_duplicadas"] = n_claims == n_distinct
        checks["cada_tarefa_concluiu_uma_vez"] = all(r["attempts"] <= 2 for r in calls) and ce2.status(inv)["progress"]["done"] == 4
        checks["retomada_concluiu"] = res["state"] == "complete"
        # 7. reconciliação com divergência registrada
        groups = {g["key"]: g for g in ce2.groups(inv)}
        conflicts = [k for k, g in groups.items() if g["conflict"]]
        out["conflicts"] = conflicts
        checks["divergencia_registrada"] = bool(conflicts) and all(groups[k]["state"] == "contradicted" for k in conflicts)
        # 8-12. dossiê com análise, reprodução, adaptação e roteiro
        d1 = ce2.generate_dossier(inv, workdir / "dossie")
        out["dossier_v1"] = {k: d1[k] for k in ("dossier_version", "created", "sections_without_data")}
        checks["dossie_gerado"] = d1["created"] and d1["dossier_version"] == 1 and all((Path(d1["path"]) / f).is_file() for f in (
            "00_RESUMO_EXECUTIVO.md", "01_ANALISE_AUDIOVISUAL.md", "02_ENGENHARIA_REVERSA.md", "03_FERRAMENTAS_E_TECNICAS.md", "04_APLICACAO_RIAN_ROCHA_IA.md",
            "05_APLICACAO_OBJETARIA.md", "06_ROTEIRO_ORIGINAL.md", "07_PLANO_DE_PRODUCAO.md", "08_PERGUNTAS_EM_ABERTO.md", "manifest.json", "README.md"))
        checks["dossie_idempotente"] = ce2.generate_dossier(inv, workdir / "dossie")["created"] is False
        # 17. decisões humanas preservadas (e visíveis no dossiê)
        ce2.review(ref, "ferramenta:capcut", "confirm", "human:rian", note="Visto na interface do vídeo.")
        ce2.review(ref, "producao:split_screen", "reject", "human:rian", note="Hipótese descartada pelo curador.")
        d2 = ce2.generate_dossier(inv, workdir / "dossie")
        out["dossier_v2"] = {k: d2[k] for k in ("dossier_version", "created")}
        checks["revisao_humana_gera_nova_versao_sem_perder_a_anterior"] = d2["dossier_version"] == 2 and (Path(d2["path"]) / "_versoes").is_dir()
        # nova investigação (profundidade diferente) não apaga revisões nem a investigação anterior
        op2 = ce2.open_investigation(ref, depth="standard", requested_by="human:demo")
        ce2.run(op2["investigation_id"])
        g2 = {g["key"]: g for g in ce2.groups(op2["investigation_id"])}
        checks["nova_versao_preserva_decisoes_humanas"] = g2.get("ferramenta:capcut", {}).get("human_state") == "confirmed"
        checks["versao_anterior_preservada"] = ce2.get(inv)["state"] == "superseded" and op2["seq"] == 2
        # 13. exportação Obsidian (staging)
        ob = ce2.export_obsidian(inv, workdir / "obsidian_staging")
        ob2 = ce2.export_obsidian(inv, workdir / "obsidian_staging")
        checks["obsidian_idempotente"] = ob["results"]["note"] in ("created", "updated") and ob2["results"]["note"] == "unchanged"
        # 14. eventos para o n8n
        n1 = ce2.drain_events("n8n-demo", JsonlSink(workdir / "eventos_n8n.jsonl"))
        n2 = ce2.drain_events("n8n-demo", JsonlSink(workdir / "eventos_n8n.jsonl"))
        checks["eventos_entregues_uma_vez"] = n1 > 0 and n2 == 0
        out["events_delivered"] = n1
        out["status"] = ce2.status(inv)
        out["investigation_object"] = ce2.investigation_object(inv)
    finally:
        eng.close()
    out["checks"] = checks
    out["all_checks_passed"] = all(checks.values())
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", help="pasta de saída (recriada)")
    a = ap.parse_args(argv)
    wd = Path(a.out) if a.out else Path(tempfile.mkdtemp(prefix="ii_ce_demo_"))
    if a.out and wd.exists():
        shutil.rmtree(wd)
    wd.mkdir(parents=True)
    res = run_demo(wd)
    (wd / "demo_summary.json").write_text(json.dumps(res, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    for k, v in res["checks"].items():
        print(("OK   " if v else "FALHA"), k)
    print(f"\n{sum(res['checks'].values())}/{len(res['checks'])} verificações · saída em {wd}")
    return 0 if res["all_checks_passed"] else 1


if __name__ == "__main__":
    sys.exit(main())

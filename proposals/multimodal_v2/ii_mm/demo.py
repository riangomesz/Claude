"""Demonstração isolada de ponta a ponta (Tarefa 18). Só dados sintéticos; nada sai do diretório temporário.

    entrada bruta sintética → adaptadores → normalização → classificação (+ narrativa e técnicas)
    → persistência SQLite → indexação/consulta → revisão humana → exportação para staging Obsidian
    → missão n8n assinada pelo gateway idempotente

Uso: python3 -m ii_mm.demo [--keep DIR]
"""
from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path
from typing import Any, Dict

from . import adapters as A
from .catalog import Query, search
from .classifier import Classifier
from .contract import validate_document
from .db.migrations import open_database
from .db.repository import Repository
from .n8n_contract import MISSION_SCHEMA, MissionGateway, build_result, compute_mission_id, sign
from .narrative import suggest_blocks
from .normalize import Normalizer
from .obsidian_export import export_reference
from .review import ReviewService
from .synthetic import sha
from .techniques import build_techniques

SRT = """1
00:00:00,000 --> 00:00:02,400
Para tudo e olha isso aqui

2
00:00:02,400 --> 00:00:07,800
Nesse vídeo vou mostrar o passo a passo no CapCut

3
00:00:07,800 --> 00:00:14,000
Primeiro abre a timeline, em seguida clica em legendas automáticas

4
00:00:14,000 --> 00:00:19,500
Fica 100% automático e mais rápido

5
00:00:19,500 --> 00:00:24,000
Comenta e clica no link na bio com desconto
"""
FFMPEG = "pts_time:7.9\nlavfi.scene_score=0.41\npts_time:14.05\nlavfi.scene_score=0.37\npts_time:19.6\nlavfi.scene_score=0.12\n"
FFPROBE = {"streams": [{"codec_type": "video", "width": 1080, "height": 1920, "avg_frame_rate": "30/1", "codec_name": "h264"},
                       {"codec_type": "audio"}], "format": {"duration": "24.0"}}
FRAMES = {"schema_version": "ii.evidence_package.v1", "frames": [
    {"pacote_id": "P01", "t_s": 9.0, "sha256": sha("demo-p01"), "file": "frames/p01_interface_t009000ms.jpg", "papel": "interface_ou_legenda"},
    {"pacote_id": "P02", "t_s": 14.0, "sha256": sha("demo-p02"), "file": "frames/p02_corte_antes_t014000ms.jpg", "papel": "corte_antes", "par_com": "P03"},
    {"pacote_id": "P03", "t_s": 14.033, "sha256": sha("demo-p03"), "file": "frames/p03_corte_depois_t014033ms.jpg", "papel": "corte_depois", "par_com": "P02"},
    {"pacote_id": "P04", "t_s": 21.0, "sha256": sha("demo-p04"), "file": "frames/p04_oferta_t021000ms.jpg", "papel": "interface_ou_legenda"}]}
OBSERVATIONS = {"observations": [
    {"frame_refs": ["P01"], "t_s": 9.0, "tag": "ui_screen_visible", "text": "Interface do CapCut com timeline e botão de legendas"},
    {"frame_refs": ["P01"], "t_s": 9.0, "tag": "split_screen", "text": "Apresentador embaixo, tela da ferramenta em cima"},
    {"frame_refs": ["P01"], "t_s": 9.0, "tag": "burned_caption", "text": "Legenda branca com contorno sobre o apresentador"},
    {"frame_refs": ["P02", "P03"], "t_s": 14.0, "tag": "punch_in_scale", "text": "Rosto maior no segundo quadro do par"},
    {"frame_refs": ["P02", "P03"], "t_s": 14.0, "tag": "animated_caption", "text": "Legenda muda de palavra entre os quadros"},
    {"frame_refs": ["P04"], "t_s": 21.0, "tag": "price_or_discount_on_screen", "text": "Selo de 50% de desconto na tela"}]}


def run_demo(workdir: Path) -> Dict[str, Any]:
    workdir = Path(workdir)
    report: Dict[str, Any] = {}
    n = Normalizer("ref_DEMO01", "instagram", "SYNTHdemo01", 24.0, content_sha256=sha("demo-video"),
                   origin_url="https://www.instagram.com/reel/SYNTHdemo01/", author_handle="autor_demo")
    n.add_frames(A.frames_from_manifest(FRAMES))
    n.add_probe(A.probe_from_ffprobe_json(FFPROBE))
    n.add_transcript(A.transcript_from_srt(SRT))
    n.add_scene_candidates(A.scenes_from_ffmpeg_metadata(FFMPEG, threshold=0.1))
    n.add_metadata("Legendas automáticas no CapCut em 1 minuto", ["#capcut", "#tutorial", "#edicaodevideo"])
    n.add_observations(A.observations_from_json(OBSERVATIONS, observer="agent:demo"))
    n.add_unverified("'100% automático' (afirmação promocional da fala, sem demonstração)", source="demo:curadoria", t_start_s=14.0, t_end_s=19.5)
    report["normalization"] = {k: (v if not isinstance(v, list) else len(v)) for k, v in n.report.items()}
    report["downgraded"] = n.report["downgraded"]

    doc = Classifier().classify(n.build())
    doc["narrative_blocks"] = suggest_blocks(doc)
    doc["techniques"] = build_techniques(doc, [{"technique": "split_screen", "author": "agent:demo",
                                                "text": "Gravar tela e rosto separadamente e compor 9:16 com a interface no topo",
                                                "requires": ["captura de tela", "editor com camadas"]}])
    problems = validate_document(doc)
    if problems:
        raise RuntimeError(f"documento inválido: {problems}")
    report["categories"] = {c["category"]: c["support"] for c in doc["categories"]}
    report["tools"] = {t["name"]: t["status"] for t in doc["tools"]}
    report["techniques"] = sorted({(t["technique"], t["level"]) for t in doc["techniques"]})
    report["narrative"] = [(b["type"], b["support"]) for b in doc["narrative_blocks"]]

    conn = open_database(workdir / "demo_ii.sqlite")
    try:
        repo = Repository(conn)
        saved = repo.save_analysis(doc)
        again = repo.save_analysis(doc)
        report["persist"] = {"analysis_id": saved.analysis_id, "created": saved.created, "idempotent_resave_created": again.created}
        hits = search(conn, Query(tool="CapCut", tool_visual_only=True)).items
        report["query_visual_tool_hits"] = [h["reference_id"] for h in hits]
        report["query_time_range_hits"] = [h["reference_id"] for h in search(conn, Query(evidence_tag="punch_in_scale", time_range=(13.0, 15.0))).items]

        rv = ReviewService(repo)
        rv.accept_category(saved.reference_id, "tutorial", "human:demo", "passo a passo visível na interface e na fala")
        rv.correct_tool_name(saved.reference_id, "CapCut", "CapCut (desktop)", "human:demo", "layout da versão desktop")
        reviewed = rv.reviewed_document(saved.reference_id)
        report["review"] = {"history": len(rv.history(saved.reference_id)),
                            "tutorial_state": next(c["review_state"] for c in reviewed["categories"] if c["category"] == "tutorial"),
                            "tool_after": reviewed["tools"][0]["name"], "original_untouched": repo.get_document(saved.analysis_id) == doc}

        stage = workdir / "obsidian_staging"
        report["export_first"] = export_reference(reviewed, stage)["markdown"]
        report["export_second"] = export_reference(reviewed, stage)["markdown"]
        report["note_path"] = str(stage / "ref_DEMO01.md")

        secret = b"segredo-demo-nao-real"
        mission = {"schema_version": MISSION_SCHEMA, "reference": {"platform": "instagram", "url": "https://www.instagram.com/reel/SYNTHdemo01/"},
                   "requested_stages": ["evidence_normalized", "classified"],
                   "artifacts": [{"kind": "srt", "sha256": sha(SRT), "uri": "missions/SYNTHdemo01/transcricao.srt"}],
                   "budget": {"allow_paid_models": False, "max_usd": 0}, "requested_by": "n8n:demo", "created_at": "2026-10-18T00:00:00Z"}
        mission["mission_id"] = compute_mission_id(mission)
        gw = MissionGateway(conn, lambda m: build_result(m["mission_id"], "awaiting_review", executed=m["requested_stages"],
                                                         analysis_id=saved.analysis_id), secret)
        body = json.dumps(mission).encode()
        r1, r2 = gw.receive(body, sign(body, secret)), gw.receive(body, sign(body, secret))
        report["n8n"] = {"state": r1["state"], "next_action": r1["next_action"], "replayed": bool(r2.get("replayed"))}
    finally:
        conn.close()
    return report


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep", help="diretório para manter os artefatos (padrão: temporário, apagado ao final)")
    a = ap.parse_args()
    if a.keep:
        Path(a.keep).mkdir(parents=True, exist_ok=True)
        print(json.dumps(run_demo(Path(a.keep)), ensure_ascii=False, indent=2, default=list))
    else:
        with tempfile.TemporaryDirectory(prefix="ii_demo_") as t:
            print(json.dumps(run_demo(Path(t)), ensure_ascii=False, indent=2, default=list))


if __name__ == "__main__":
    main()

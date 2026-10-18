"""Gera o pacote de integração (handoff/): exemplos de contrato validados e manifesto com SHA-256.

Uso: python3 tools/build_handoff.py            (regrava handoff/contratos/*.json e handoff/MANIFESTO_PACOTE.json)
     python3 tools/build_handoff.py --check    (só confere; sai com 1 se algo estiver desatualizado)
Os exemplos são gerados pelo próprio código a partir de dados SINTÉTICOS; nada de mídia, banco ou credencial.
"""
from __future__ import annotations

import hashlib
import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
sys.dont_write_bytecode = True

# Arquivos que compõem o pacote (papel de cada um). Diretórios inteiros são expandidos.
PACKAGE = {
    "ii_mm": "núcleo (somente stdlib)",
    "../classification/text_matcher.py": "dependência do classificador textual",
    "tests": "testes de aceitação",
    "fixtures": "fixtures sintéticas (formatos reais, valores sintéticos)",
    "tools": "ferramentas (cobertura, benchmark, patch legado, pacote)",
    "patches/legacy_close_sqlite_connections.diff": "patch demonstrativo do legado (L1), não aplicado",
    "handoff/contratos": "exemplos de contrato validados",
    "handoff/exemplo_uso.py": "exemplo executável: modo sombra somente leitura + staging",
    "run_tests.py": "executor da suíte",
    "verify_package.py": "verificador de pacote de evidências",
    "PLANO_INTEGRACAO_SEGURA.md": "plano em três estágios",
    "MATRIZ_COMPATIBILIDADE.md": "compatibilidade com o Projeto-MVP",
    "RISCO_E_ROLLBACK.md": "riscos e rollback",
}
FORBIDDEN_SUFFIXES = (".sqlite", ".sqlite3", ".db", ".mp4", ".mov", ".jpg", ".jpeg", ".png", ".webp", ".wav", ".mp3", ".env", ".pem", ".key")


def contract_examples() -> dict:
    from ii_mm import adapters as A
    from ii_mm.demo import FFMPEG, FFPROBE, FRAMES, OBSERVATIONS, SRT
    from ii_mm.classifier import Classifier
    from ii_mm.narrative import suggest_blocks
    from ii_mm.normalize import Normalizer
    from ii_mm.quality import temporal_quality
    from ii_mm.shadow import run_shadow
    from ii_mm.synthetic import sha
    from ii_mm.techniques import build_techniques
    from ii_mm.n8n_contract import MISSION_SCHEMA, build_result, compute_mission_id

    n = Normalizer("ref_DEMO01", "instagram", "SYNTHdemo01", 24.0, content_sha256=sha("demo-video"),
                   origin_url="https://www.instagram.com/reel/SYNTHdemo01/", author_handle="autor_demo")
    frames = A.frames_from_manifest(FRAMES)
    probe = A.probe_from_ffprobe_json(FFPROBE)
    n.add_frames(frames); n.add_probe(probe)
    n.add_transcript(A.transcript_from_srt(SRT))
    n.add_scene_candidates(A.scenes_from_ffmpeg_metadata(FFMPEG, threshold=0.1))
    n.add_observations(A.observations_from_json(OBSERVATIONS, observer="agent:demo"))
    doc = Classifier().classify(n.build())
    doc["narrative_blocks"] = suggest_blocks(doc)
    doc["techniques"] = build_techniques(doc, [{"technique": "split_screen", "author": "agent:demo",
                                                "text": "gravar tela e rosto separados e compor 9:16", "requires": ["editor com camadas"]}])
    doc.pop("classification_runs", None)  # log de execução; não faz parte do exemplo estável
    mission = {"schema_version": MISSION_SCHEMA, "reference": {"platform": "instagram", "url": "https://www.instagram.com/reel/SYNTHdemo01/"},
               "requested_stages": ["evidence_normalized", "classified", "awaiting_review"],
               "artifacts": [{"kind": "srt", "sha256": sha(SRT), "uri": "missions/SYNTHdemo01/transcricao.srt"},
                             {"kind": "frames_manifest", "sha256": sha("manifesto"), "uri": "missions/SYNTHdemo01/manifesto_pacote.json"}],
               "budget": {"allow_paid_models": False, "max_usd": 0}, "requested_by": "n8n:exemplo", "created_at": "2026-10-18T00:00:00Z"}
    mission["mission_id"] = compute_mission_id(mission)
    rows = json.loads((HERE / "fixtures" / "legacy" / "shadow_rows.json").read_text(encoding="utf-8"))
    shadow = run_shadow(rows)
    return {
        "ii.reference_analysis.v2.exemplo.json": doc,
        "ii.visual_observation.v1.exemplo.json": OBSERVATIONS
            | {"_nota": "frame_refs apontam para pacote_id/frame_id do manifesto; attributes é opcional (lista fechada)"},
        "ii.mission.v1.exemplo.json": mission,
        "ii.mission_result.v1.exemplo.json": build_result(mission["mission_id"], "awaiting_review",
                                                          executed=mission["requested_stages"], analysis_id="an_1_exemplo"),
        "ii.shadow_report.v1.exemplo.json": shadow,
        "ii.temporal_quality.v1.exemplo.json": temporal_quality(doc, [frames], probe.records[0]),
    }


def _files() -> list:
    out = []
    for rel in PACKAGE:
        p = (HERE / rel).resolve()
        items = sorted(x for x in p.rglob("*") if x.is_file()) if p.is_dir() else [p]
        for f in items:
            if "__pycache__" in f.parts or f.name == "MANIFESTO_PACOTE.json":
                continue
            out.append(f)
    return out


def content_hash(data: bytes) -> str:
    """SHA-256 do conteúdo com quebras de linha normalizadas (CRLF → LF): um checkout do Windows com
    core.autocrlf=true não pode invalidar o manifesto sem mudança real de conteúdo."""
    return hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()


def manifest() -> dict:
    files = []
    for f in _files():
        rel = f.relative_to(HERE.parent).as_posix() if HERE.parent in f.parents else f.name
        if f.suffix.lower() in FORBIDDEN_SUFFIXES:
            raise SystemExit(f"arquivo proibido no pacote: {rel}")
        data = f.read_bytes()
        files.append({"path": rel, "sha256_lf": content_hash(data), "bytes_lf": len(data.replace(b"\r\n", b"\n"))})
    return {"schema_version": "ii.handoff_manifest.v1", "base": "proposals/", "files": files,
            "roles": PACKAGE, "verify": "python3 tools/build_handoff.py --check",
            "hash_note": "sha256_lf = SHA-256 com CRLF normalizado para LF (estável entre Linux e Windows)"}


def render(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def main(check: bool) -> int:
    stale = []
    out_dir = HERE / "handoff" / "contratos"
    for name, obj in contract_examples().items():
        path = out_dir / name
        text = render(obj)
        if check:
            if not path.exists() or path.read_text(encoding="utf-8") != text:
                stale.append(str(path.relative_to(HERE)))
        else:
            path.write_text(text, encoding="utf-8")
    mpath = HERE / "handoff" / "MANIFESTO_PACOTE.json"
    text = render(manifest())
    if check:
        if not mpath.exists() or mpath.read_text(encoding="utf-8") != text:
            stale.append(str(mpath.relative_to(HERE)))
    else:
        mpath.write_text(text, encoding="utf-8")
    if stale:
        print("desatualizado:", ", ".join(stale))
        return 1
    print("pacote ok" if check else "pacote gerado")
    return 0


if __name__ == "__main__":
    sys.exit(main("--check" in sys.argv))

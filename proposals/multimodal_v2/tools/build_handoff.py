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
# Documentos que CITAM o hash do manifesto (handoff, prompt, relatório) ficam fora dele, para não haver ciclo.
PACKAGE = {
    "ii_mm": "núcleo (somente stdlib)",
    "../classification/text_matcher.py": "dependência do classificador textual",
    "tests": "testes de aceitação",
    "fixtures": "fixtures sintéticas (formatos reais, valores sintéticos)",
    "tools": "ferramentas (cobertura, benchmark, patch legado, pacote, schemas)",
    "patches/legacy_close_sqlite_connections.diff": "patch demonstrativo do legado (L1), não aplicado",
    "handoff/contratos": "exemplos de contrato validados",
    "handoff/schemas": "JSON Schemas estruturais dos contratos públicos",
    "handoff/exemplo_uso.py": "exemplo executável: modo sombra somente leitura + staging",
    "handoff/verificar_recebimento.py": "validador do receptor (stdlib, não executa o pacote, não grava)",
    "handoff/windows": "scripts PowerShell do guia operacional",
    "handoff/baseline_contratos_c6845a4.json": "baseline dos contratos do Projeto-MVP (c6845a4) usada por tools/compat_report.py",
    "run_tests.py": "executor da suíte",
    "verify_package.py": "verificador de pacote de evidências",
    "test_multimodal_classifier.py": "testes do protótipo v1",
    "test_regression_current.py": "regressão do legado (golden)",
    "test_verify_package.py": "testes do verificador de pacote",
    "multimodal_classifier.py": "protótipo v1 (preservado)",
    "regression_golden.json": "golden da classificação legada",
    "analise_multimodal_v2.json": "marcador do piloto (blocked_missing_evidence), usado por teste",
    "make_golden.py": "gerador do golden",
    "../classification/test_text_matcher.py": "testes do matcher",
    "INVENTARIO_COMPONENTES.md": "inventário dos componentes",
    "DEPENDENCIAS_WINDOWS.md": "auditoria de dependências para Windows",
    "GUIA_WINDOWS_POWERSHELL.md": "guia operacional PowerShell",
    "CRITERIOS_ADOCAO.md": "critérios de adoção",
    "CHECKLIST_ACEITE_RC.md": "checklist de aceite por estágio",
    "AVALIACAO_HUMANA.md": "fluxo de avaliação humana",
    "PLANO_INTEGRACAO_SEGURA.md": "plano em três estágios",
    "MATRIZ_COMPATIBILIDADE.md": "compatibilidade com o Projeto-MVP",
    "RISCO_E_ROLLBACK.md": "riscos e rollback",
}
# Pastas inteiramente controladas pelo pacote: qualquer arquivo a mais nelas é sinal de adulteração ou sobra.
MANAGED_DIRS = ["multimodal_v2/ii_mm", "multimodal_v2/tests", "multimodal_v2/fixtures", "multimodal_v2/tools",
                "multimodal_v2/handoff"]
REQUIREMENTS = {"python_min": "3.11", "python_tested": ["3.11.17", "3.12.3", "3.13.16"], "sqlite_min": "3.24.0",
                "external_packages": [], "os_tested": ["Linux x86_64 (container de nuvem)"], "os_not_tested": ["Windows"]}
FORBIDDEN_SUFFIXES = (".sqlite", ".sqlite3", ".db", ".mp4", ".mov", ".jpg", ".jpeg", ".png", ".webp", ".wav", ".mp3", ".env", ".pem", ".key")
MANIFEST_NAME = "MANIFESTO_PACOTE.json"
INVENTORY_START = "## 1. Tabela gerada\n\n"
INVENTORY_END = "\n\n\"Testes que o exercitam\""


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
            if "__pycache__" in f.parts or f.name == MANIFEST_NAME:
                continue
            out.append(f)
    return out


def content_hash(data: bytes) -> str:
    """SHA-256 do conteúdo com quebras de linha normalizadas (CRLF → LF): um checkout do Windows com
    core.autocrlf=true não pode invalidar o manifesto sem mudança real de conteúdo."""
    return hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()


def manifest() -> dict:
    from ii_mm import RC_ID, __version__
    files = []
    for f in _files():
        rel = f.relative_to(HERE.parent).as_posix()
        if f.suffix.lower() in FORBIDDEN_SUFFIXES:
            raise SystemExit(f"arquivo proibido no pacote: {rel}")
        data = f.read_bytes()
        files.append({"path": rel, "sha256_lf": content_hash(data), "bytes_lf": len(data.replace(b"\r\n", b"\n"))})
    return {"schema_version": "ii.handoff_manifest.v2", "rc_id": RC_ID, "version": __version__, "base": "proposals/",
            "requirements": REQUIREMENTS, "managed_dirs": MANAGED_DIRS, "files": files,
            "roles": PACKAGE, "verify": "python handoff/verificar_recebimento.py",
            "hash_note": "sha256_lf = SHA-256 com CRLF normalizado para LF (estável entre Linux e Windows)"}


def build_zip(dest: Path) -> str:
    """Zip determinístico (ordem, datas e permissões fixas) com os arquivos do manifesto + o próprio manifesto."""
    import zipfile
    from ii_mm import RC_ID
    man_path = HERE / "handoff" / MANIFEST_NAME
    entries = [(f.relative_to(HERE.parent).as_posix(), f) for f in _files()] + [(man_path.relative_to(HERE.parent).as_posix(), man_path)]
    with zipfile.ZipFile(dest, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for rel, f in sorted(entries):
            info = zipfile.ZipInfo(f"{RC_ID}/proposals/{rel}", date_time=(1980, 1, 1, 0, 0, 0))
            info.external_attr = 0o644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, f.read_bytes().replace(b"\r\n", b"\n"))
    return hashlib.sha256(Path(dest).read_bytes()).hexdigest()


def render(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def main(check: bool, zip_path: str = None) -> int:
    if str(HERE / "tools") not in sys.path:
        sys.path.insert(0, str(HERE / "tools"))
    from schemas import schemas as all_schemas
    import inventory
    stale = []
    inv_path = HERE / "INVENTARIO_COMPONENTES.md"  # seção 1 é gerada (tools/inventory.py)
    inv_old = inv_path.read_text(encoding="utf-8")
    head, rest = inv_old.split(INVENTORY_START, 1)
    inv_new = head + INVENTORY_START + inventory.markdown(inventory.collect()) + INVENTORY_END + rest.split(INVENTORY_END, 1)[1]
    if inv_new != inv_old:
        if check:
            stale.append(inv_path.name)
        else:
            inv_path.write_text(inv_new, encoding="utf-8")
    generated = [(HERE / "handoff" / "contratos" / n, o) for n, o in contract_examples().items()]
    generated += [(HERE / "handoff" / "schemas" / n, o) for n, o in all_schemas().items()]
    for path, obj in generated:
        text = render(obj)
        path.parent.mkdir(parents=True, exist_ok=True)
        if check:
            if not path.exists() or path.read_text(encoding="utf-8") != text:
                stale.append(str(path.relative_to(HERE)))
        else:
            path.write_text(text, encoding="utf-8")
    mpath = HERE / "handoff" / MANIFEST_NAME
    text = render(manifest())
    if check:
        if not mpath.exists() or mpath.read_text(encoding="utf-8") != text:
            stale.append(str(mpath.relative_to(HERE)))
    else:
        mpath.write_text(text, encoding="utf-8")
    if stale:
        print("desatualizado:", ", ".join(stale))
        return 1
    if zip_path and not check:
        digest = build_zip(Path(zip_path))
        print(f"zip: {zip_path} sha256={digest}")
    print("pacote ok" if check else "pacote gerado")
    print(f"sha256 do manifesto (LF): {content_hash(mpath.read_bytes())}")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    zp = sys.argv[sys.argv.index("--zip") + 1] if "--zip" in sys.argv else None
    sys.exit(main("--check" in sys.argv, zp))

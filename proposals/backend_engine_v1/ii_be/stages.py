"""Etapas audiovisuais (Tarefa 08): recebem as saídas das ferramentas existentes (ffprobe, ffmpeg, whisper, módulos
do Projeto-MVP), conferem integridade e alimentam o núcleo `ii_mm`. Nada aqui reimplementa essas ferramentas.

Cada handler recebe um `StageContext` e devolve `StageOutput(result, digest, events, effects)`:
- `result`: resumo pequeno e serializável (vai para `be_stage_results` e para o job);
- `digest`: resumo do que foi produzido (corte antecipado do processamento incremental);
- `effects(c)`: gravações que precisam ser atômicas com a conclusão do job (índice, artefato derivado);
- `events`: eventos do outbox, gravados na mesma transação.

Integridade: todo artefato lido é conferido pelo SHA-256 no momento do uso. Arquivo alterado depois do registro
vira `corrupt` e a etapa espera uma nova versão (`DependencyMissing`), em vez de processar conteúdo divergente.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from . import _ii_mm  # noqa: F401
from ii_mm import adapters as AD
from ii_mm.classifier import Classifier
from ii_mm.contract import canonical_json, validate_document
from ii_mm.db.repository import Repository
from .refscope import RefScopedRepository
from ii_mm.dedup import analysis_input_hash
from ii_mm.narrative import suggest_blocks
from ii_mm.normalize import Normalizer
from ii_mm.obsidian_export import ExportError, export_reference
from ii_mm.review import ReviewService
from ii_mm.techniques import build_techniques
from . import artifacts as A
from . import knowledge as K
from .clock import iso
from .errors import Cancelled, DependencyMissing, InvalidInput, PermanentError, StageTimeout
from .identity import current_metadata

MAX_ARTIFACT_BYTES = 64 * 1024 * 1024
EVENT = Tuple[str, Dict[str, Any], str]  # tipo, payload, dedup_key


@dataclass
class StageOutput:
    result: Dict[str, Any]
    digest: str
    events: List[EVENT] = field(default_factory=list)
    effects: Optional[Callable[[sqlite3.Connection], None]] = None


@dataclass
class StageContext:
    conn: sqlite3.Connection
    reference_id: str
    stage: str
    job_id: str
    attempt: int
    payload: Dict[str, Any]
    upstream: Dict[str, Dict[str, Any]]       # etapa -> resultado corrente
    store: Optional[A.ArtifactStore]
    export_dir: Optional[Path]
    clock: Any
    deadline: float
    heartbeat_fn: Callable[[], bool] = lambda: False
    cancelled: bool = False

    def heartbeat(self) -> None:
        """Renova o lease (levanta LeaseLost se a posse se foi) e registra pedido de cancelamento."""
        if self.heartbeat_fn():
            self.cancelled = True
        self.check()

    def check(self) -> None:
        if self.cancelled:
            raise Cancelled("cancelamento solicitado")
        if self.clock.now() > self.deadline:
            raise StageTimeout(f"{self.stage}: passou do prazo")


def _d(obj: Any) -> str:
    return hashlib.sha256(canonical_json(obj).encode("utf-8")).hexdigest()


def _read(ctx: StageContext, art: Dict[str, Any]) -> bytes:
    if ctx.store is None:
        raise PermanentError("sem raiz de artefatos configurada")
    if art.get("size_bytes") and art["size_bytes"] > MAX_ARTIFACT_BYTES:
        raise InvalidInput(f"artefato {art['kind']} maior que {MAX_ARTIFACT_BYTES} bytes")
    info = ctx.store.inspect(art["relpath"])
    if not info.exists or info.sha256 != art["sha256"]:
        A.verify(ctx.conn, ctx.store, art["artifact_id"], iso(ctx.clock.now()))
        raise DependencyMissing(f"artefato {art['kind']} v{art['version']} {'ausente' if not info.exists else 'alterado após o registro (corrupt)'}")
    with open(ctx.store.path(art["relpath"]), "rb") as f:
        return f.read()


def _artifact(ctx: StageContext, kinds: Tuple[str, ...]) -> Optional[Dict[str, Any]]:
    for k in kinds:
        a = A.current(ctx.conn, ctx.reference_id, k)
        if a:
            return a
    return None


def _json(ctx: StageContext, art: Dict[str, Any]) -> Any:
    try:
        return json.loads(_read(ctx, art).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InvalidInput(f"artefato {art['kind']} ilegível: {exc.__class__.__name__}") from None


def _text(ctx: StageContext, art: Dict[str, Any]) -> str:
    try:
        return _read(ctx, art).decode("utf-8")
    except UnicodeDecodeError:
        raise InvalidInput(f"artefato {art['kind']} não é UTF-8") from None


def _art_ref(a: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    return {"artifact_id": a["artifact_id"], "kind": a["kind"], "version": a["version"], "sha256": a["sha256"]} if a else None


def _by_id(ctx: StageContext, ref: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not ref:
        return None
    row = ctx.conn.execute("SELECT * FROM be_artifacts WHERE artifact_id = ?", (ref["artifact_id"],)).fetchone()
    return dict(row) if row else None


# --------------------------------------------------------------------------- etapas de mídia
def stage_acquire(ctx: StageContext) -> StageOutput:
    art = A.current(ctx.conn, ctx.reference_id, "video")
    if art is None:
        raise DependencyMissing(f"mídia não disponível (estado: {A.media_state(ctx.conn, ctx.reference_id)})")
    info = ctx.store.inspect(art["relpath"]) if ctx.store else None
    if info is None or not info.exists or info.sha256 != art["sha256"]:
        A.verify(ctx.conn, ctx.store, art["artifact_id"], iso(ctx.clock.now()))
        raise DependencyMissing("mídia ausente ou alterada desde o registro; aguardando nova aquisição")
    res = {"video": _art_ref(art), "size_bytes": art["size_bytes"]}
    return StageOutput(res, art["sha256"])


def _optional(kinds: Tuple[str, ...], parse: Optional[Callable[[StageContext, Dict[str, Any]], Dict[str, Any]]] = None):
    def handler(ctx: StageContext) -> StageOutput:
        art = _artifact(ctx, kinds)
        if art is None:
            res = {"present": False, "artifact": None}
            return StageOutput(res, _d(res))
        extra = parse(ctx, art) if parse else {}
        res = {"present": True, "artifact": _art_ref(art), **extra}
        return StageOutput(res, _d({"sha": art["sha256"], **extra}))
    return handler


def _parse_probe(ctx, art):
    r = AD.probe_from_ffprobe_json(_json(ctx, art))
    if not r.records:
        raise InvalidInput(f"ffprobe sem dados utilizáveis: {r.errors}")
    p = r.records[0]
    return {"duration_s": p["duration_s"], "width": p.get("width"), "height": p.get("height"), "fps": p.get("fps"),
            "has_audio": p.get("has_audio"), "vfr_suspected": p.get("vfr_suspected")}


def stage_probe(ctx: StageContext) -> StageOutput:
    art = _artifact(ctx, ("ffprobe",))
    if art is None:
        raise DependencyMissing("saída do ffprobe ainda não registrada")
    extra = _parse_probe(ctx, art)
    res = {"artifact": _art_ref(art), **extra}
    return StageOutput(res, _d({"sha": art["sha256"], **extra}))


def _parse_transcript(ctx, art):
    r = AD.transcript_from_segments(_json(ctx, art)) if art["kind"] == "transcript_segments" else AD.transcript_from_srt(_text(ctx, art))
    return {"segments": len(r.records), "adapter_errors": len(r.errors)}


def _parse_scenes(ctx, art):
    r = AD.scenes_from_ffmpeg_metadata(_text(ctx, art)) if art["kind"] == "scenes_ffmpeg" else AD.scenes_from_candidates_json(_json(ctx, art))
    return {"scenes": len(r.records), "adapter_errors": len(r.errors)}


def _parse_frames(ctx, art):
    r = AD.frames_from_manifest(_json(ctx, art))
    return {"frames": len(r.records), "adapter_errors": len(r.errors)}


def _parse_metrics(ctx, art):
    r = AD.metrics_from_frame_pairs(_json(ctx, art))
    return {"pairs": len(r.records), "adapter_errors": len(r.errors)}


def _parse_observations(ctx, art):
    r = AD.observations_from_json(_json(ctx, art), observer=art["origin"])
    return {"observations": len(r.records), "observer": art["origin"], "adapter_errors": len(r.errors)}


# --------------------------------------------------------------------------- evidências e classificação
def _derived_write(ctx: StageContext, rel: str, data: bytes) -> A.FileInfo:
    if ctx.store is None:
        raise PermanentError("sem raiz de artefatos configurada")
    existing = ctx.store.inspect(rel)
    if existing.exists and existing.sha256 == hashlib.sha256(data).hexdigest():
        return existing  # endereçado por conteúdo: reescrever é desnecessário
    return ctx.store.write_bytes(rel, data)


def stage_assemble(ctx: StageContext) -> StageOutput:
    c = ctx.conn
    ref = c.execute("SELECT platform, canonical_key, origin_url FROM refs WHERE reference_id = ?", (ctx.reference_id,)).fetchone()
    meta = current_metadata(c, ctx.reference_id)
    native = ref["canonical_key"].split(":", 1)[1]
    probe = (ctx.upstream.get("probe") or {}).get("result")
    duration = (probe or {}).get("duration_s") or meta.get("duration_s")
    if not duration:
        raise DependencyMissing("duração desconhecida (sem ffprobe e sem duração nos metadados)")
    sha = ((ctx.upstream.get("acquire") or {}).get("result") or {}).get("video", {}) or {}
    n = Normalizer(ctx.reference_id, ref["platform"], native, float(duration), content_sha256=sha.get("sha256"),
                   origin_url=ref["origin_url"], author_handle=meta.get("author_handle"))
    used = {}

    def art_of(stage):
        res = (ctx.upstream.get(stage) or {}).get("result") or {}
        return _by_id(ctx, res.get("artifact") or res.get("video"))

    a = art_of("frames")
    if a:
        n.add_frames(AD.frames_from_manifest(_json(ctx, a))); used["frames"] = a["sha256"]
    a = art_of("probe")
    if a:
        n.add_probe(AD.probe_from_ffprobe_json(_json(ctx, a))); used["probe"] = a["sha256"]
    a = art_of("transcribe")
    if a:
        tr = AD.transcript_from_segments(_json(ctx, a)) if a["kind"] == "transcript_segments" else AD.transcript_from_srt(_text(ctx, a))
        n.add_transcript(tr); used["transcribe"] = a["sha256"]
    a = art_of("scenes")
    if a:
        sc = AD.scenes_from_ffmpeg_metadata(_text(ctx, a), threshold=0.1) if a["kind"] == "scenes_ffmpeg" else AD.scenes_from_candidates_json(_json(ctx, a))
        n.add_scene_candidates(sc); used["scenes"] = a["sha256"]
    a = art_of("metrics")
    if a:
        n.add_visual_metrics(AD.metrics_from_frame_pairs(_json(ctx, a))); used["metrics"] = a["sha256"]
    a = art_of("visual_analysis")
    if a:
        n.add_observations(AD.observations_from_json(_json(ctx, a), observer=a["origin"])); used["visual_analysis"] = a["sha256"]
    ctx.check()
    caption = meta.get("caption") or meta.get("title")
    if caption or meta.get("hashtags"):
        n.add_metadata(caption, meta.get("hashtags") or [])
    doc = n.build()
    problems = validate_document(doc)
    if problems:
        raise InvalidInput(f"pacote de evidências inválido: {problems[:5]}")
    body = canonical_json(doc).encode("utf-8")
    digest = hashlib.sha256(body).hexdigest()
    rel = f"derived/{ctx.reference_id}/evidence_{digest[:16]}.json"
    info = _derived_write(ctx, rel, body)
    report = {k: (len(v) if isinstance(v, list) else v) for k, v in n.report.items()}
    res = {"evidence_package": {"relpath": rel, "sha256": info.sha256}, "evidence": len(doc["evidence"]), "inputs": used,
           "normalization": report, "duration_s": duration, "graph": ctx.payload.get("graph")}

    def effects(c2):
        A.record(c2, ctx.reference_id, "evidence_package", info, origin="stage:assemble", now_iso=iso(ctx.clock.now()), job_id=ctx.job_id)
    return StageOutput(res, digest, [("analysis.completed", {"reference_id": ctx.reference_id, "evidence": len(doc["evidence"]),
                                                             "evidence_sha256": digest}, f"assemble|{ctx.reference_id}|{digest}")], effects)


def human_overrides(conn: sqlite3.Connection, reference_id: str, doc: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Decisões humanas que divergem da nova classificação automática (a decisão humana prevalece)."""
    auto = {c["category"]: c["support"] for c in doc["categories"]}
    out = []
    for r in conn.execute("SELECT target, state FROM review_state WHERE reference_id = ? AND target LIKE 'category:%'", (reference_id,)):
        cat = r["target"].split(":", 1)[1]
        if r["state"] == "rejected" and cat in auto:
            out.append({"category": cat, "human": "rejected", "automatic": auto[cat]})
        elif r["state"] == "added" and cat not in auto:
            out.append({"category": cat, "human": "added", "automatic": None})
    return out


def stage_classify(ctx: StageContext) -> StageOutput:
    pkg = ((ctx.upstream.get("assemble") or {}).get("result") or {}).get("evidence_package")
    if not pkg:
        raise DependencyMissing("pacote de evidências ausente")
    if ctx.store is None:
        raise PermanentError("sem raiz de artefatos configurada")
    info = ctx.store.inspect(pkg["relpath"])
    if not info.exists or info.sha256 != pkg["sha256"]:
        raise DependencyMissing("pacote de evidências ausente ou alterado; refazer assemble")
    with open(ctx.store.path(pkg["relpath"]), "rb") as f:
        doc = json.loads(f.read().decode("utf-8"))
    doc = Classifier().classify(doc)
    doc["narrative_blocks"] = suggest_blocks(doc)
    doc["techniques"] = build_techniques(doc, [])
    problems = validate_document(doc)
    if problems:
        raise InvalidInput(f"classificação inválida: {problems[:5]}")
    ctx.check()
    saved = Repository(ctx.conn).save_analysis(doc)  # persistência do ii_mm: idempotente por input_hash
    input_hash = analysis_input_hash(doc)
    overrides = human_overrides(ctx.conn, saved.reference_id, doc)
    res = {"analysis_id": saved.analysis_id, "created": saved.created, "superseded": saved.superseded, "conflict": saved.conflict,
           "input_hash": input_hash, "categories": {c["category"]: c["support"] for c in doc["categories"]},
           "tools": {t["name"]: t["status"] for t in doc["tools"]}, "human_overrides": overrides}
    events = [("classification.updated", {"reference_id": ctx.reference_id, "analysis_id": saved.analysis_id, "created": saved.created,
                                          "superseded": saved.superseded, "human_overrides": overrides},
               f"classify|{saved.analysis_id}")]
    return StageOutput(res, input_hash, events)


def reviewed(conn: sqlite3.Connection, reference_id: str) -> Optional[Dict[str, Any]]:
    repo = RefScopedRepository(conn)   # análise da REFERÊNCIA (I1), não só do vídeo
    if repo.current_analysis_id(reference_id) is None:
        return None
    return ReviewService(repo).reviewed_document(reference_id)


def stage_index(ctx: StageContext) -> StageOutput:
    doc = reviewed(ctx.conn, ctx.reference_id)
    if doc is None:
        raise DependencyMissing("referência sem análise corrente")
    aid = RefScopedRepository(ctx.conn).current_analysis_id(ctx.reference_id)
    rows = K.rows_for(doc, K.curation_targets(ctx.conn, ctx.reference_id))
    digest = _d([list(r) for r in rows])
    res = {"analysis_id": aid, "rows": len(rows), "facets": sorted({r[0] for r in rows}),
           "human_rows": sum(1 for r in rows if r[4] == "human")}

    def effects(c):
        K.replace_rows(c, ctx.reference_id, aid, rows)
    return StageOutput(res, digest, [("knowledge.indexed", {"reference_id": ctx.reference_id, "analysis_id": aid, "rows": len(rows)},
                                      f"index|{ctx.reference_id}|{digest}")], effects)


def stage_export(ctx: StageContext) -> StageOutput:
    if ctx.export_dir is None:
        res = {"exported": False, "reason": "exportação não configurada"}
        return StageOutput(res, _d(res))
    doc = reviewed(ctx.conn, ctx.reference_id)
    if doc is None:
        raise DependencyMissing("referência sem análise corrente")
    try:
        out = export_reference(doc, ctx.export_dir)  # staging apenas: o ii_mm recusa pasta de Vault
    except ExportError as exc:
        raise InvalidInput(str(exc)) from None
    note = Path(out["path"]).name
    body = Path(out["path"]).read_bytes()
    digest = hashlib.sha256(body).hexdigest()
    res = {"exported": True, "note": note, "markdown": out["markdown"], "note_sha256": digest}
    return StageOutput(res, digest, [("export.ready", {"reference_id": ctx.reference_id, "note": note, "sha256": digest},
                                      f"export|{ctx.reference_id}|{digest}")])


HANDLERS: Dict[str, Callable[[StageContext], StageOutput]] = {
    "acquire": stage_acquire,
    "probe": stage_probe,
    "audio": _optional(("audio",)),
    "transcribe": _optional(("transcript_segments", "srt"), _parse_transcript),
    "scenes": _optional(("scenes_ffmpeg", "scene_candidates"), _parse_scenes),
    "frames": _optional(("frames_manifest",), _parse_frames),
    "metrics": _optional(("frame_metrics",), _parse_metrics),
    "visual_analysis": _optional(("observations",), _parse_observations),
    "assemble": stage_assemble,
    "classify": stage_classify,
    "index": stage_index,
    "export": stage_export,
}

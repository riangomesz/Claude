"""Contrato de dados `ii.reference_analysis.v2`.

Um documento descreve UMA referência (um vídeo salvo de uma plataforma) e tudo o que se sabe
sobre ele, sempre com a natureza de cada afirmação explícita:

    observed_visual  visto num frame/sequência com proveniência verificável (SHA-256 do artefato)
    measured_signal  medido por ferramenta determinística (ffprobe, detecção de cena, métricas)
    transcript_claim dito na fala (transcrição automática = dado não confiável)
    metadata_claim   declarado em metadados (legenda, hashtags, autor informado)
    inference        conclusão derivada de outras evidências; não é observação
    unverified       registrado, mas sem base verificável (ex.: afirmação promocional)

Os documentos são dicts JSON puros; este módulo oferece construtores e um validador estrito.
"""
from __future__ import annotations

import hashlib
import json
import math
from typing import Any, Dict, Iterable, List, Optional

from . import SCHEMA_VERSION

EVIDENCE_STATUSES = (
    "observed_visual", "measured_signal", "transcript_claim", "metadata_claim", "inference", "unverified",
)
# Base de uma observação visual: o que foi efetivamente olhado.
VISUAL_BASES = ("static_frame", "frame_pair", "frame_sequence", "video_clip")
SOURCE_TYPES = (
    "agent_observation", "human_observation", "whisper", "ffprobe", "scene_detection",
    "frame_extraction", "visual_metric", "instagram_metadata", "text_classifier", "derived",
)
# Fontes permitidas por status: impede, por construção, "fala vira fato visual".
STATUS_SOURCES = {
    "observed_visual": {"agent_observation", "human_observation"},
    "measured_signal": {"ffprobe", "scene_detection", "frame_extraction", "visual_metric"},
    "transcript_claim": {"whisper"},
    "metadata_claim": {"instagram_metadata"},
    "inference": {"text_classifier", "derived", "agent_observation", "human_observation"},
    "unverified": set(SOURCE_TYPES),
}
PLATFORMS = ("instagram", "youtube", "tiktok", "x", "vimeo", "local", "other")
TOOL_STATUSES = ("visually_identified", "mentioned_only", "metadata_only", "inferred", "unverified")
TECHNIQUE_LEVELS = (
    "observed_in_frame",        # 1. visto num quadro
    "frame_pair_difference",    # 2. diferença entre dois quadros
    "temporal_sequence",        # 3. movimento comprovado por sequência temporal
    "hypothesis",               # 4. hipótese de técnica
    "reproduction_suggestion",  # 5. sugestão criativa de reprodução
)
REVIEW_STATES = ("pending", "accepted", "rejected", "edited")
FORBIDDEN_NUMERIC_KEYS = ("confidence", "probability", "accuracy", "precision_pct", "score_pct", "percent")
TIME_TOLERANCE_S = 0.5


class ContractError(ValueError):
    pass


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def evidence_id(video_key: str, status: str, source_type: str, t_start_s: Optional[float],
                t_end_s: Optional[float], ref: Optional[str], claim: str, tag: Optional[str] = None) -> str:
    """ID estável por conteúdo: a mesma evidência gera o mesmo ID em qualquer execução e ordem."""
    def _t(x):
        return None if x is None else round(float(x), 3)
    payload = canonical_json([video_key, status, source_type, _t(t_start_s), _t(t_end_s), ref, claim, tag])
    return "ev_" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]


def make_evidence(video_key: str, *, status: str, source_type: str, claim: str,
                  provenance: Dict[str, Any], t_start_s: Optional[float] = None,
                  t_end_s: Optional[float] = None, ref: Optional[str] = None,
                  tag: Optional[str] = None, basis: Optional[str] = None,
                  extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if t_start_s is not None and t_end_s is None:
        t_end_s = t_start_s
    ev = {
        "evidence_id": evidence_id(video_key, status, source_type, t_start_s, t_end_s, ref, claim, tag),
        "status": status,
        "source_type": source_type,
        "claim": claim,
        "t_start_s": t_start_s,
        "t_end_s": t_end_s,
        "ref": ref,
        "tag": tag,
        "basis": basis,
        "provenance": dict(provenance),
    }
    if extra:
        ev["extra"] = dict(extra)
    return ev


def empty_document(reference_id: str, platform: str, video_id: str, duration_s: float,
                   content_sha256: Optional[str] = None, origin_url: Optional[str] = None,
                   author_handle: Optional[str] = None) -> Dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "reference": {
            "reference_id": reference_id, "platform": platform, "origin_url": origin_url,
            "author_handle": author_handle, "author_handle_status": "metadata_claim" if author_handle else None,
        },
        "video": {"video_id": video_id, "content_sha256": content_sha256, "duration_s": duration_s},
        "segments": [], "transcript": [], "frames": [], "evidence": [], "metrics": [],
        "categories": [], "tools": [], "techniques": [], "narrative_blocks": [],
        "hypotheses": [], "pending": [], "review_history": [],
    }


# ---------------------------------------------------------------------------
# Validação
# ---------------------------------------------------------------------------

def _num(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def _find_forbidden_keys(obj: Any, path: str = "$") -> Iterable[str]:
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in FORBIDDEN_NUMERIC_KEYS:
                yield f"{path}.{k}"
            yield from _find_forbidden_keys(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _find_forbidden_keys(v, f"{path}[{i}]")


def _check_interval(p: List[str], where: str, a, b, dur: Optional[float], required: bool) -> None:
    if a is None and b is None:
        if required:
            p.append(f"{where}: intervalo temporal obrigatório")
        return
    if not (_num(a) and _num(b)):
        p.append(f"{where}: tempos devem ser numéricos")
        return
    if a < 0 or b < a:
        p.append(f"{where}: intervalo inválido ({a}, {b})")
    if dur is not None and b > dur + TIME_TOLERANCE_S:
        p.append(f"{where}: fim {b} excede a duração {dur}")


def _unique(p: List[str], items: List[Dict[str, Any]], key: str, where: str) -> set:
    seen, out = set(), set()
    for it in items:
        v = it.get(key) if isinstance(it, dict) else None
        if v is None:
            p.append(f"{where}: item sem '{key}'")
        elif v in seen:
            p.append(f"{where}: '{key}' duplicado: {v}")
        seen.add(v)
        out.add(v)
    return out


def validate_document(doc: Any) -> List[str]:
    """Lista de violações do contrato (vazia = válido). Nunca levanta exceção para entrada ruim."""
    p: List[str] = []
    if not isinstance(doc, dict):
        return ["documento deve ser um objeto JSON"]
    if doc.get("schema_version") != SCHEMA_VERSION:
        p.append(f"schema_version deve ser {SCHEMA_VERSION}")
    for key in ("reference", "video"):
        if not isinstance(doc.get(key), dict):
            p.append(f"'{key}' ausente ou não é objeto")
    list_keys = ("segments", "transcript", "frames", "evidence", "metrics", "categories", "tools",
                 "techniques", "narrative_blocks", "hypotheses", "pending", "review_history")
    for key in list_keys:
        if not isinstance(doc.get(key, []), list):
            p.append(f"'{key}' deve ser lista")
    if p:
        return p

    ref, video = doc["reference"], doc["video"]
    if not ref.get("reference_id"):
        p.append("reference.reference_id obrigatório")
    if ref.get("platform") not in PLATFORMS:
        p.append(f"reference.platform inválida: {ref.get('platform')}")
    if not video.get("video_id"):
        p.append("video.video_id obrigatório")
    dur = video.get("duration_s")
    if not (_num(dur) and dur > 0):
        p.append("video.duration_s deve ser número positivo")
        dur = None
    sha = video.get("content_sha256")
    if sha is not None and not (isinstance(sha, str) and len(sha) == 64 and all(c in "0123456789abcdef" for c in sha)):
        p.append("video.content_sha256 deve ser hex SHA-256 minúsculo")

    for path in _find_forbidden_keys(doc):
        p.append(f"campo numérico de confiança não permitido: {path}")

    seg_ids = _unique(p, doc.get("transcript", []), "segment_id", "transcript")
    for s in doc.get("transcript", []):
        _check_interval(p, f"transcript:{s.get('segment_id')}", s.get("t_start_s"), s.get("t_end_s"), dur, True)
        if not isinstance(s.get("text"), str):
            p.append(f"transcript:{s.get('segment_id')}: text deve ser string")
    _unique(p, doc.get("segments", []), "segment_id", "segments")
    for s in doc.get("segments", []):
        _check_interval(p, f"segments:{s.get('segment_id')}", s.get("t_start_s"), s.get("t_end_s"), dur, True)

    frame_ids = _unique(p, doc.get("frames", []), "frame_id", "frames")
    for f in doc.get("frames", []):
        _check_interval(p, f"frames:{f.get('frame_id')}", f.get("t_s"), f.get("t_s"), dur, True)
        if not (isinstance(f.get("sha256"), str) and len(f["sha256"]) == 64):
            p.append(f"frames:{f.get('frame_id')}: sha256 obrigatório")

    ev_by_id: Dict[str, Dict[str, Any]] = {}
    _unique(p, doc.get("evidence", []), "evidence_id", "evidence")
    for e in doc.get("evidence", []):
        eid = e.get("evidence_id")
        ev_by_id[eid] = e
        st, src = e.get("status"), e.get("source_type")
        if st not in EVIDENCE_STATUSES:
            p.append(f"evidence:{eid}: status inválido {st}")
            continue
        if src not in SOURCE_TYPES:
            p.append(f"evidence:{eid}: source_type inválido {src}")
        elif src not in STATUS_SOURCES[st]:
            p.append(f"evidence:{eid}: fonte {src} não pode sustentar status {st}")
        if not isinstance(e.get("claim"), str) or not e["claim"].strip():
            p.append(f"evidence:{eid}: claim obrigatório")
        prov = e.get("provenance")
        if not isinstance(prov, dict) or not prov.get("source"):
            p.append(f"evidence:{eid}: provenance.source obrigatório")
            prov = {}
        _check_interval(p, f"evidence:{eid}", e.get("t_start_s"), e.get("t_end_s"), dur,
                        st in ("observed_visual", "transcript_claim"))
        if st == "observed_visual":
            if e.get("basis") not in VISUAL_BASES:
                p.append(f"evidence:{eid}: observed_visual exige basis em {VISUAL_BASES}")
            if not prov.get("artifact_sha256"):
                p.append(f"evidence:{eid}: observed_visual exige provenance.artifact_sha256")
            if e.get("ref") and frame_ids and e["ref"] not in frame_ids and e.get("basis") in ("static_frame", "frame_pair"):
                p.append(f"evidence:{eid}: ref {e['ref']} não corresponde a frame do documento")
        if st == "transcript_claim" and e.get("ref") and seg_ids and e["ref"] not in seg_ids:
            p.append(f"evidence:{eid}: ref {e['ref']} não corresponde a segmento da transcrição")

    def _refs(where: str, ids) -> List[Dict[str, Any]]:
        out = []
        if not isinstance(ids, list):
            p.append(f"{where}: evidence_ids deve ser lista")
            return out
        for i in ids:
            if i not in ev_by_id:
                p.append(f"{where}: evidência inexistente {i}")
            else:
                out.append(ev_by_id[i])
        return out

    from .evidence_rules import category_support, CATEGORIES, SUPPORT_LEVELS  # import tardio, sem ciclo
    _unique(p, doc.get("categories", []), "category", "categories")
    for c in doc.get("categories", []):
        name = c.get("category")
        if name not in CATEGORIES:
            p.append(f"categories: categoria desconhecida {name}")
        sup = _refs(f"categories:{name}", c.get("evidence_ids", []))
        con = _refs(f"categories:{name}:contra", c.get("contradicting_evidence_ids", []))
        if c.get("support") not in SUPPORT_LEVELS:
            p.append(f"categories:{name}: support inválido {c.get('support')}")
        elif c["support"] != category_support(sup):
            p.append(f"categories:{name}: support {c['support']} incoerente com as evidências ({category_support(sup)})")
        if c.get("review_state", "pending") not in REVIEW_STATES:
            p.append(f"categories:{name}: review_state inválido")
        overlap = {e["evidence_id"] for e in sup} & {e["evidence_id"] for e in con}
        if overlap:
            p.append(f"categories:{name}: evidência a favor e contra ao mesmo tempo: {sorted(overlap)}")

    for t in doc.get("tools", []):
        name = t.get("name")
        if not name:
            p.append("tools: item sem name")
        st = t.get("status")
        if st not in TOOL_STATUSES:
            p.append(f"tools:{name}: status inválido {st}")
        vis = _refs(f"tools:{name}:visual", t.get("visual_evidence_ids", []))
        _refs(f"tools:{name}:mencoes", t.get("mention_evidence_ids", []))
        if st == "visually_identified" and not any(e["status"] == "observed_visual" for e in vis):
            p.append(f"tools:{name}: visually_identified sem evidência observed_visual")
        if any(e["status"] != "observed_visual" for e in vis):
            p.append(f"tools:{name}: visual_evidence_ids contém evidência não visual")

    for t in doc.get("techniques", []):
        name, lvl = t.get("technique"), t.get("level")
        if lvl not in TECHNIQUE_LEVELS:
            p.append(f"techniques:{name}: level inválido {lvl}")
            continue
        evs = _refs(f"techniques:{name}", t.get("evidence_ids", []))
        bases = {e.get("basis") for e in evs if e["status"] == "observed_visual"}
        if lvl == "observed_in_frame" and not bases:
            p.append(f"techniques:{name}: observed_in_frame exige evidência visual")
        if lvl == "frame_pair_difference" and not bases & {"frame_pair", "frame_sequence", "video_clip"}:
            p.append(f"techniques:{name}: frame_pair_difference exige basis frame_pair ou superior")
        if lvl == "temporal_sequence" and not bases & {"frame_sequence", "video_clip"}:
            p.append(f"techniques:{name}: temporal_sequence exige frame_sequence ou video_clip (par de quadros não prova movimento)")

    for h in doc.get("hypotheses", []):
        _refs(f"hypotheses:{h.get('hypothesis_id')}", h.get("evidence_ids", []))
        if not h.get("text"):
            p.append(f"hypotheses:{h.get('hypothesis_id')}: text obrigatório")

    for r in doc.get("review_history", []):
        for k in ("review_id", "at", "reviewer", "action", "target"):
            if not r.get(k):
                p.append(f"review_history:{r.get('review_id')}: '{k}' obrigatório")

    from .narrative import validate_blocks  # import tardio, sem ciclo
    p.extend(validate_blocks(doc))
    return p


def assert_valid(doc: Any) -> None:
    problems = validate_document(doc)
    if problems:
        raise ContractError("; ".join(problems[:10]) + (" …" if len(problems) > 10 else ""))


# Mapeamento do contrato v1 (multimodal_classifier.py) para v2.
V1_TO_V2_STATUS = {
    "verified_visual": "observed_visual",
    "measured": "measured_signal",
    "claimed_transcript": "transcript_claim",
    "claimed_metadata": "metadata_claim",
    "hypothesis": "inference",
}

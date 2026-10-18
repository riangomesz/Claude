"""Adaptadores de saídas JÁ PRODUZIDAS por ferramentas externas (Tarefa 10).

Nenhum adaptador executa FFmpeg, Whisper ou modelo: todos recebem texto/JSON já gerado e devolvem
registros canônicos + erros. Nunca levantam exceção por entrada ruim; registram o problema.

Formatos suportados (derivados do código do Projeto-MVP, commit c6845a4):
- Transcrição: segmentos {start,end,text} (faster-whisper), {id,start,end,text} (missão ii_coverage),
  {index,start_time,end_time,text} (core/transcription.py, tempos "HH:MM:SS,mmm") e texto SRT bruto.
- Cenas: saída `metadata=print` do ffmpeg (pts_time + lavfi.scene_score) e `ii.scene_candidates.v1`.
- Sonda: JSON do `ffprobe -show_streams -show_format`.
- Frames: `ii.coverage.manifest.v1` (frame_id, t_actual_s) e `ii.evidence_package.v1` (pacote_id, t_s, par_com).
- Métricas visuais: pares de temporal_intelligence/metric_calculator.py.
- Observações estruturadas de agente ou humano (formato proposto `ii.visual_observation.v1`).
"""
from __future__ import annotations

import json
import math
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class AdapterResult:
    kind: str
    records: List[Dict[str, Any]] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    source: Dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.errors


def _load(payload: Any) -> Any:
    if isinstance(payload, (bytes, bytearray)):
        payload = payload.decode("utf-8", errors="replace")
    if isinstance(payload, str):
        return json.loads(payload)
    return payload


MAX_RECORDS = 50_000      # por chamada de adaptador; um Reel típico tem dezenas a centenas de registros
MAX_TEXT_CHARS = 10_000   # por texto (segmento, observação); excedente é truncado e sinalizado


def _clean(text: str) -> str:
    """Espaços colapsados e forma Unicode NFC."""
    return unicodedata.normalize("NFC", " ".join(str(text).split()))


def _bounded_text(res: "AdapterResult", text: str, where: str) -> str:
    t = _clean(text)
    if len(t) > MAX_TEXT_CHARS:
        res.errors.append(f"{where}: texto truncado em {MAX_TEXT_CHARS} caracteres (original {len(t)})")
        t = t[:MAX_TEXT_CHARS]
    return t


def _over_limit(res: "AdapterResult", items: list) -> list:
    if len(items) > MAX_RECORDS:
        res.errors.append(f"{len(items)} registros excedem o limite de {MAX_RECORDS}; só os primeiros foram lidos")
        return items[:MAX_RECORDS]
    return items


def _num(x) -> Optional[float]:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


_TS = re.compile(r"^\s*(?:(\d+):)?(\d{1,2}):(\d{1,2})(?:[.,](\d{1,3}))?\s*$")


def parse_timestamp(value: Any) -> Optional[float]:
    """Aceita número, "SS.mmm", "MM:SS.mmm", "HH:MM:SS,mmm". Devolve segundos ou None."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return _num(value)
    if not isinstance(value, str):
        return None
    s = value.strip()
    n = _num(s)
    if n is not None:
        return n
    m = _TS.match(s)
    if not m:
        return None
    h, mi, se, ms = m.groups()
    if h is None:  # "MM:SS"
        h, mi = 0, mi
    total = int(h or 0) * 3600 + int(mi) * 60 + int(se) + (int(ms.ljust(3, "0")) / 1000 if ms else 0)
    return round(total, 3)


# ---------------------------------------------------------------------------
# Transcrição
# ---------------------------------------------------------------------------

def transcript_from_segments(payload: Any, source: str = "whisper") -> AdapterResult:
    res = AdapterResult("transcript", source={"source": source})
    try:
        data = _load(payload)
    except (json.JSONDecodeError, TypeError) as exc:
        res.errors.append(f"JSON inválido: {exc.__class__.__name__}")
        return res
    if isinstance(data, dict):
        data = data.get("segments", data.get("segmentos"))
    if not isinstance(data, list):
        res.errors.append("esperada lista de segmentos (ou objeto com 'segments'/'segmentos')")
        return res
    seen = set()
    for n, seg in enumerate(_over_limit(res, data), start=1):
        if not isinstance(seg, dict):
            res.errors.append(f"segmento {n}: não é objeto")
            continue
        start = parse_timestamp(seg.get("start", seg.get("start_time", seg.get("inicio_s"))))
        end = parse_timestamp(seg.get("end", seg.get("end_time", seg.get("fim_s"))))
        text = seg.get("text", seg.get("texto"))
        sid = seg.get("id", seg.get("index", n))
        if start is None or end is None or end < start or start < 0:
            res.errors.append(f"segmento {sid}: tempos ausentes ou inválidos")
            continue
        if not isinstance(text, str) or not text.strip():
            res.errors.append(f"segmento {sid}: texto vazio")
            continue
        text = _bounded_text(res, text, f"segmento {sid}")
        key = (round(start, 3), round(end, 3), text)
        if key in seen:
            res.errors.append(f"segmento {sid}: duplicado, ignorado")
            continue
        seen.add(key)
        res.records.append({"segment_id": f"s{sid}", "t_start_s": round(start, 3), "t_end_s": round(end, 3),
                            "text": text, "source": source})
    res.records.sort(key=lambda r: (r["t_start_s"], r["t_end_s"], r["segment_id"]))
    return res


_SRT_BLOCK = re.compile(r"(\d+)\s*\n\s*([0-9:,.]+)\s*-->\s*([0-9:,.]+)[^\n]*\n(.*?)(?=\n\s*\n|\Z)", re.S)


def transcript_from_srt(text: str, source: str = "srt_file") -> AdapterResult:
    if not isinstance(text, str):
        return AdapterResult("transcript", errors=["SRT deve ser texto"], source={"source": source})
    segs = [{"index": m.group(1), "start_time": m.group(2), "end_time": m.group(3),
             "text": " ".join(m.group(4).split())} for m in _SRT_BLOCK.finditer(text.replace("\r\n", "\n").strip())]
    res = transcript_from_segments(segs, source=source)
    if not segs:
        res.errors.append("nenhum bloco SRT reconhecido")
    return res


# ---------------------------------------------------------------------------
# Cenas, sonda e métricas
# ---------------------------------------------------------------------------

def scenes_from_ffmpeg_metadata(stdout: str, threshold: Optional[float] = None) -> AdapterResult:
    """Interpreta `ffmpeg ... -vf "select='gt(scene,X)',metadata=print:file=-"` (mesma lógica de fase5.js)."""
    res = AdapterResult("scene_candidates", source={"source": "ffmpeg_metadata_print", "threshold": threshold})
    if not isinstance(stdout, str):
        res.errors.append("stdout deve ser texto")
        return res
    t = None
    for line in stdout.splitlines():
        m1 = re.search(r"pts_time:([0-9.]+)", line)
        if m1:
            t = _num(m1.group(1))
        m2 = re.search(r"lavfi\.scene_score=([0-9.]+)", line)
        if m2 and t is not None:
            res.records.append({"t_s": round(t, 3), "score": round(float(m2.group(1)), 3)})
            t = None
    return _dedupe_scenes(res)


def scenes_from_candidates_json(payload: Any) -> AdapterResult:
    res = AdapterResult("scene_candidates", source={"source": "ii.scene_candidates.v1"})
    try:
        data = _load(payload)
    except (json.JSONDecodeError, TypeError) as exc:
        res.errors.append(f"JSON inválido: {exc.__class__.__name__}")
        return res
    if not isinstance(data, dict) or not isinstance(data.get("candidatos"), list):
        res.errors.append("esperado objeto ii.scene_candidates.v1 com lista 'candidatos'")
        return res
    res.source.update({"threshold": data.get("limiar"), "method": data.get("metodo")})
    for c in _over_limit(res, data["candidatos"]):
        t, sc = (_num(c.get("t_s")), _num(c.get("score"))) if isinstance(c, dict) else (None, None)
        if t is None or sc is None or t < 0:
            res.errors.append(f"candidato inválido: {c!r}"[:120])
            continue
        res.records.append({"t_s": round(t, 3), "score": round(sc, 3)})
    return _dedupe_scenes(res)


def _dedupe_scenes(res: AdapterResult) -> AdapterResult:
    best: Dict[float, float] = {}
    for r in res.records:
        best[r["t_s"]] = max(best.get(r["t_s"], -1.0), r["score"])
    if len(best) != len(res.records):
        res.errors.append(f"{len(res.records) - len(best)} candidato(s) duplicado(s) consolidados")
    res.records = [{"t_s": t, "score": s} for t, s in sorted(best.items())]
    return res


def probe_from_ffprobe_json(payload: Any) -> AdapterResult:
    res = AdapterResult("probe", source={"source": "ffprobe"})
    try:
        data = _load(payload)
    except (json.JSONDecodeError, TypeError) as exc:
        res.errors.append(f"JSON inválido: {exc.__class__.__name__}")
        return res
    if not isinstance(data, dict):
        res.errors.append("esperado objeto JSON do ffprobe")
        return res
    video = next((s for s in data.get("streams", []) if isinstance(s, dict) and s.get("codec_type") == "video"), None)
    audio = any(isinstance(s, dict) and s.get("codec_type") == "audio" for s in data.get("streams", []))
    dur = _num((data.get("format") or {}).get("duration")) or (_num(video.get("duration")) if video else None)
    if video is None:
        res.errors.append("nenhum stream de vídeo")
    if not dur or dur <= 0:
        res.errors.append("duração ausente ou inválida")
    fps = None
    if video and isinstance(video.get("avg_frame_rate"), str) and "/" in video["avg_frame_rate"]:
        a, b = video["avg_frame_rate"].split("/", 1)
        fps = round(float(a) / float(b), 3) if _num(a) and _num(b) else None
    if video and not res.errors:
        res.records.append({"duration_s": round(dur, 6), "width": video.get("width"), "height": video.get("height"),
                            "fps": fps, "codec": video.get("codec_name"), "has_audio": audio})
    return res


METRIC_KEYS = ("diff_absoluta_global", "diff_absoluta_topo", "diff_absoluta_base", "ssim_global",
               "ssim_topo", "ssim_base", "histograma_correl_global")


def metrics_from_frame_pairs(payload: Any) -> AdapterResult:
    """Pares de temporal_intelligence (timestamp_anterior_s/timestamp_atual_s + métricas)."""
    res = AdapterResult("visual_metrics", source={"source": "temporal_intelligence.metric_calculator"})
    try:
        data = _load(payload)
    except (json.JSONDecodeError, TypeError) as exc:
        res.errors.append(f"JSON inválido: {exc.__class__.__name__}")
        return res
    if isinstance(data, dict):
        data = data.get("pares", data.get("pairs", data.get("metricas")))
    if not isinstance(data, list):
        res.errors.append("esperada lista de pares de métricas")
        return res
    for n, p in enumerate(_over_limit(res, data), start=1):
        if not isinstance(p, dict):
            res.errors.append(f"par {n}: não é objeto")
            continue
        a, b = _num(p.get("timestamp_anterior_s")), _num(p.get("timestamp_atual_s"))
        if a is None or b is None or b <= a:
            res.errors.append(f"par {n}: timestamps inválidos")
            continue
        vals = {k: _num(p[k]) for k in METRIC_KEYS if k in p and _num(p[k]) is not None}
        if not vals:
            res.errors.append(f"par {n}: sem métricas reconhecidas")
            continue
        res.records.append({"t_start_s": round(a, 3), "t_end_s": round(b, 3), "metrics": vals})
    return res


# ---------------------------------------------------------------------------
# Frames e observações
# ---------------------------------------------------------------------------

def frames_from_manifest(payload: Any) -> AdapterResult:
    res = AdapterResult("frames")
    try:
        data = _load(payload)
    except (json.JSONDecodeError, TypeError) as exc:
        res.errors.append(f"JSON inválido: {exc.__class__.__name__}")
        return res
    if not isinstance(data, dict) or not isinstance(data.get("frames"), list):
        res.errors.append("esperado manifesto com lista 'frames'")
        return res
    schema = data.get("schema_version")
    res.source = {"source": schema or "manifesto_desconhecido", "video_sha256": data.get("video_sha256") or (data.get("video") or {}).get("sha256")}
    seen = set()
    for f in _over_limit(res, data["frames"]):
        if not isinstance(f, dict):
            res.errors.append("frame não é objeto")
            continue
        fid = f.get("pacote_id") or f.get("frame_id")
        t = _num(f.get("t_s", f.get("t_actual_s")))
        sha = f.get("sha256")
        if not fid or t is None or t < 0 or not (isinstance(sha, str) and re.fullmatch(r"[0-9a-f]{64}", sha)):
            res.errors.append(f"frame {fid}: id, tempo ou sha256 inválido")
            continue
        if fid in seen:
            res.errors.append(f"frame {fid}: duplicado")
            continue
        seen.add(fid)
        res.records.append({"frame_id": fid, "t_s": round(t, 3), "sha256": sha, "file": f.get("file"),
                            "width": f.get("width"), "height": f.get("height"),
                            "role": f.get("papel") or f.get("selection_origin"), "pair_with": f.get("par_com")})
    res.records.sort(key=lambda r: (r["t_s"], r["frame_id"]))
    return res


OBSERVATION_KINDS = ("observation", "hypothesis")


def observations_from_json(payload: Any, observer: str) -> AdapterResult:
    """Formato `ii.visual_observation.v1`: lista de
    {frame_refs:[...], t_s, tag, text, kind: observation|hypothesis, basis?}."""
    res = AdapterResult("observations", source={"source": "ii.visual_observation.v1", "observer": observer})
    try:
        data = _load(payload)
    except (json.JSONDecodeError, TypeError) as exc:
        res.errors.append(f"JSON inválido: {exc.__class__.__name__}")
        return res
    if isinstance(data, dict):
        data = data.get("observations")
    if not isinstance(data, list):
        res.errors.append("esperada lista 'observations'")
        return res
    for n, o in enumerate(_over_limit(res, data), start=1):
        if not isinstance(o, dict):
            res.errors.append(f"observação {n}: não é objeto")
            continue
        refs = o.get("frame_refs") or ([o["frame_ref"]] if o.get("frame_ref") else [])
        t = _num(o.get("t_s"))
        kind = o.get("kind", "observation")
        if not refs or t is None or not o.get("tag") or not str(o.get("text", "")).strip() or kind not in OBSERVATION_KINDS:
            res.errors.append(f"observação {n}: exige frame_refs, t_s, tag, text e kind válido")
            continue
        res.records.append({"frame_refs": [str(r) for r in refs], "t_s": round(t, 3), "tag": str(o["tag"]),
                            "text": _bounded_text(res, o["text"], f"observação {n}"), "kind": kind, "basis": o.get("basis"),
                            "observer": observer})
    return res

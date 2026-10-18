"""Relatório de qualidade das evidências temporais (Missão Suprema 02, Tarefa 11).

Aponta problemas de tempo nas entradas e no documento, sem nenhuma porcentagem de "compreensão":
cada achado tem código, severidade (info | warning | blocking), detalhe e intervalo quando houver.

Entradas: o documento v2 e, opcionalmente, os `AdapterResult` brutos (para ver o que a normalização
rejeitou ou reordenou) e o registro do ffprobe.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

GAP_WARN_S = 10.0          # lacuna absoluta entre quadros que merece aviso
GAP_WARN_FRACTION = 0.25   # ou fração da duração
OVERLAP_TOL_S = 0.05
DESYNC_TOL_S = 0.5
GRID_TOL_FRAMES = 0.25     # quanto um timestamp pode fugir da grade de quadros


def _finding(code, severity, detail, interval=None) -> Dict[str, Any]:
    f = {"code": code, "severity": severity, "detail": detail}
    if interval is not None:
        f["interval_s"] = [round(interval[0], 3), round(interval[1], 3)]
    return f


def temporal_quality(doc: Dict[str, Any], raw: Iterable[Any] = (), probe: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    dur = float(doc["video"]["duration_s"])
    fps = (probe or {}).get("fps") or doc["video"].get("fps")
    out: List[Dict[str, Any]] = []

    for res in raw:
        recs = getattr(res, "records", [])
        times = [r.get("t_s", r.get("t_start_s")) for r in recs]
        times = [t for t in times if isinstance(t, (int, float))]
        neg = [t for t in times if t < 0]
        beyond = [t for t in times if t > dur + 0.5]
        if neg:
            out.append(_finding("negative_timestamp", "blocking", f"{res.kind}: {len(neg)} registro(s) com tempo negativo"))
        if beyond:
            out.append(_finding("beyond_duration", "blocking", f"{res.kind}: {len(beyond)} registro(s) após o fim ({dur} s)", (min(beyond), max(beyond))))
        for e in getattr(res, "errors", []):
            if "tempos" in e or "inválid" in e:
                out.append(_finding("invalid_time_input", "warning", f"{res.kind}: {e}"))

    frames = sorted(doc.get("frames", []), key=lambda f: f["t_s"])
    seen: Dict[float, str] = {}
    for f in frames:
        key = round(f["t_s"], 3)
        if key in seen:
            out.append(_finding("duplicate_frame_timestamp", "warning", f"{seen[key]} e {f['frame_id']} no mesmo instante ({key} s)"))
        seen.setdefault(key, f["frame_id"])
    if frames:
        points = [0.0] + [f["t_s"] for f in frames] + [dur]
        gaps = sorted(((b - a, a, b) for a, b in zip(points, points[1:])), reverse=True)
        for size, a, b in gaps:
            if size >= GAP_WARN_S or size >= GAP_WARN_FRACTION * dur:
                out.append(_finding("large_sampling_gap", "warning", f"{size:.1f} s sem quadro amostrado", (a, b)))
    else:
        out.append(_finding("no_frames", "warning", "nenhum quadro registrado: nada visual pode ser observado"))

    segs = sorted(doc.get("transcript", []), key=lambda s: (s["t_start_s"], s["t_end_s"]))
    if not segs:
        out.append(_finding("no_transcript", "info", "sem transcrição: fala, narrativa e menções ficam sem evidência"))
    for a, b in zip(segs, segs[1:]):
        if b["t_start_s"] < a["t_end_s"] - OVERLAP_TOL_S:
            out.append(_finding("overlapping_segments", "warning", f"{a['segment_id']} e {b['segment_id']} se sobrepõem",
                                (b["t_start_s"], min(a["t_end_s"], b["t_end_s"]))))
    if segs and segs[-1]["t_end_s"] > dur + DESYNC_TOL_S:
        out.append(_finding("transcript_beyond_video", "warning", "a transcrição termina depois do vídeo (possível dessincronia)"))

    if probe:
        if probe.get("vfr_suspected"):
            out.append(_finding("variable_frame_rate", "warning",
                                f"avg_frame_rate {probe.get('fps')} ≠ r_frame_rate {probe.get('r_frame_rate')}: índices de quadro não são tempo exato"))
        v, au = probe.get("video_stream_duration_s"), probe.get("audio_stream_duration_s")
        if v and au and abs(v - au) > DESYNC_TOL_S:
            out.append(_finding("av_duration_mismatch", "warning", f"vídeo {v} s × áudio {au} s: verificar sincronia antes de alinhar fala e imagem"))
        if abs(probe.get("duration_s", dur) - dur) > DESYNC_TOL_S:
            out.append(_finding("declared_duration_mismatch", "blocking", f"duração declarada {dur} s × ffprobe {probe.get('duration_s')} s"))
    if fps and not (probe or {}).get("vfr_suspected"):
        off = [f["frame_id"] for f in frames if abs(f["t_s"] * fps - round(f["t_s"] * fps)) > GRID_TOL_FRAMES]
        if off:
            out.append(_finding("off_frame_grid", "info", f"{len(off)} quadro(s) fora da grade de {fps} fps (arredondamento ou VFR): {off[:5]}"))

    counts: Dict[str, int] = {}
    for f in out:
        counts[f["severity"]] = counts.get(f["severity"], 0) + 1
    return {"schema_version": "ii.temporal_quality.v1", "video_id": doc["video"]["video_id"], "duration_s": dur,
            "frames": len(frames), "transcript_segments": len(segs), "findings": out, "counts": counts,
            "note": "Relatório de integridade temporal. Não mede compreensão nem qualidade do conteúdo."}

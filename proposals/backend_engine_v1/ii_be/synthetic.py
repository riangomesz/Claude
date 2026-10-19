"""Fixtures SINTÉTICAS para testes, demonstração e benchmark. Nenhuma mídia real: o "vídeo" é um arquivo de bytes
determinísticos com o prefixo `II_BE_SYNTHETIC`; as saídas de ferramentas reaproveitam as da demonstração do `ii_mm`
(que também são sintéticas). Nada aqui deve ser confundido com análise de um vídeo real.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, Optional

from . import _ii_mm  # noqa: F401
from ii_mm.demo import FFMPEG, FFPROBE, FRAMES, OBSERVATIONS, SRT

SYNTHETIC_PREFIX = b"II_BE_SYNTHETIC\n"


def fake_video(seed: str, size: int = 4096) -> bytes:
    out = bytearray(SYNTHETIC_PREFIX)
    block = hashlib.sha256(seed.encode()).digest()
    while len(out) < size:
        block = hashlib.sha256(block).digest()
        out += block
    return bytes(out[:size])


def tool_outputs(duration_s: float = 24.0) -> Dict[str, bytes]:
    probe = json.loads(json.dumps(FFPROBE))
    probe["format"]["duration"] = str(duration_s)
    return {
        "ffprobe": json.dumps(probe, sort_keys=True).encode(),
        "srt": SRT.encode("utf-8"),
        "scenes_ffmpeg": FFMPEG.encode("utf-8"),
        "frames_manifest": json.dumps(FRAMES, sort_keys=True).encode(),
        "observations": json.dumps(OBSERVATIONS, sort_keys=True, ensure_ascii=False).encode("utf-8"),
    }


def seed_media_reference(engine, url: str, seed: str, metadata: Optional[Dict[str, Any]] = None,
                         outputs: Optional[Dict[str, bytes]] = None, observer: str = "agent:sintetico") -> Dict[str, Any]:
    """Grava vídeo sintético + saídas de ferramentas na raiz gerenciada, ingere e registra os artefatos."""
    from .ingest import record_from_local_file
    store = engine.store
    vid_rel = f"media/{seed}.mp4"
    store.write_bytes(vid_rel, fake_video(seed))
    res = engine.ingest(record_from_local_file(vid_rel, url=url, metadata=metadata))
    files = outputs if outputs is not None else tool_outputs()
    ext = {"ffprobe": "json", "srt": "srt", "scenes_ffmpeg": "txt", "frames_manifest": "json", "observations": "json",
           "transcript_segments": "json", "frame_metrics": "json", "scene_candidates": "json", "audio": "wav"}
    arts = {}
    for kind, data in files.items():
        rel = f"tools/{seed}/{kind}.{ext.get(kind, 'bin')}"
        store.write_bytes(rel, data)
        arts[kind] = engine.register_artifact(res.reference_id, kind, rel, origin=observer if kind == "observations" else f"tool:{kind}")
    return {"ingest": res, "artifacts": arts, "video_relpath": vid_rel}

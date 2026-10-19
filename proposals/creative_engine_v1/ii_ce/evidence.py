"""Pacote de evidências por referência (congelado na investigação) e seleção por tarefa.

O pacote é lido do banco do `ii_be` (análise corrente do `ii_mm`, classificação, metadados, mídia) UMA vez, na criação da
investigação, e gravado junto dela: o resultado é reprodutível mesmo que o catálogo mude depois, e `run` não precisa do motor.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional

from . import _be  # noqa: F401
from ii_be import artifacts as A
from ii_be.classification import ClassificationService
from ii_be.identity import current_metadata
from ii_be.refscope import RefScopedRepository
from .contracts import GENERATOR_VERSION, STRONG_STATUS, SAID_STATUS, canonical_json, clean_text, digest

MAX_EVIDENCE = 400
MAX_PER_TASK = 80
_DUR = re.compile(r"([\d.]+)\s*s\b")
META_FIELDS = ("caption", "title", "author_handle", "hashtags", "duration_s", "published_at", "language")


class NoEvidence(LookupError):
    pass


def _facet(res: Dict[str, Any], name: str) -> Any:
    return (res.get("facets") or {}).get(name) or []


def build_bundle(engine, reference_id: str) -> Dict[str, Any]:
    """Pacote para a referência. Sem análise corrente devolve pacote vazio (a investigação fica `blocked_no_evidence`)."""
    conn = engine.conn
    if not conn.execute("SELECT 1 FROM refs WHERE reference_id = ?", (reference_id,)).fetchone():
        raise KeyError(reference_id)
    meta = {k: v for k, v in current_metadata(conn, reference_id).items() if k in META_FIELDS}
    meta = {k: (clean_text(v, 1200) if isinstance(v, str) else v) for k, v in meta.items()}
    video = A.current(conn, reference_id, "video")
    aid = RefScopedRepository(conn).current_analysis_id(reference_id)
    bundle: Dict[str, Any] = {"reference_id": reference_id, "analysis_id": aid, "media_sha256": (video or {}).get("sha256"),
                              "metadata": meta, "evidence": [], "facets": {}, "duration_s": meta.get("duration_s"),
                              "versions": {"generator": GENERATOR_VERSION}}
    if aid:
        rows = conn.execute("SELECT evidence_id, status, source_type, claim, t_start_s, t_end_s, tag FROM evidence WHERE analysis_id = ? "
                            "ORDER BY COALESCE(t_start_s, 1e9), evidence_id LIMIT ?", (aid, MAX_EVIDENCE)).fetchall()
        bundle["evidence"] = [{"id": r["evidence_id"], "status": r["status"], "source_type": r["source_type"], "claim": clean_text(r["claim"], 400),
                               "t_start": r["t_start_s"], "t_end": r["t_end_s"], "tag": r["tag"]} for r in rows]
        res = ClassificationService(engine).result(reference_id) or {}
        bundle["versions"]["classifier"] = res.get("classifier_version")
        bundle["versions"]["analysis_id"] = aid
        bundle["facets"] = {
            "categories": [{"category": c["category"], "support": c["support"], "evidence_ids": c.get("evidence_ids", [])} for c in _facet(res, "categoria_editorial")],
            "tools": [{"name": clean_text(t["name"], 80), "status": t.get("status"), "evidence_ids": t.get("evidence_ids", [])} for t in _facet(res, "ferramenta_mencionada")],
            "tools_visual": [{"name": clean_text(t["name"], 80), "evidence_ids": t.get("evidence_ids", [])} for t in _facet(res, "ferramenta_identificada_visualmente")],
            "techniques": [{"technique": t["technique"], "level": t.get("level"), "evidence_ids": t.get("evidence_ids", []), "timestamps": t.get("timestamps", []),
                            "proves": t.get("proves"), "does_not_prove": t.get("does_not_prove")} for t in _facet(res, "tecnica_observada")],
            "techniques_hypothetical": [{"technique": t.get("technique"), "evidence_ids": t.get("evidence_ids", [])} for t in _facet(res, "tecnica_hipotetica") if isinstance(t, dict)],
            "transferable": _facet(res, "conhecimento_transferivel"), "commercial": _facet(res, "promessa_comercial"),
            "creative": _facet(res, "potencial_criativo"), "narrative": _facet(res, "estrutura_narrativa"),
        }
        if bundle["duration_s"] is None:
            for e in bundle["evidence"]:
                if e["source_type"] == "ffprobe":
                    m = _DUR.search(e["claim"] or "")
                    if m:
                        bundle["duration_s"] = float(m.group(1))
    bundle["content_hash"] = digest([(e["id"], e["status"], e["claim"], e["t_start"]) for e in bundle["evidence"]], bundle["media_sha256"], n=32)
    return bundle


def ev_index(bundle: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {e["id"]: e for e in bundle["evidence"]}


def _strong(e):
    return e["status"] in STRONG_STATUS


def select_for(specialist: str, bundle: Dict[str, Any], upstream: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    """Evidências mínimas por tarefa (nunca o pacote inteiro para todos)."""
    ev = bundle["evidence"]
    if specialist == "audiovisual":
        pick = [e for e in ev if _strong(e) or e["status"] == "inference"]
    elif specialist == "reproducao":
        tool_ids = {i for t in bundle["facets"].get("tools", []) + bundle["facets"].get("tools_visual", []) for i in t["evidence_ids"]}
        tech_ids = {i for t in bundle["facets"].get("techniques", []) for i in t["evidence_ids"]}
        pick = [e for e in ev if e["id"] in tool_ids or e["id"] in tech_ids or e["status"] in SAID_STATUS
                or e["tag"] in ("ui_screen_visible", "tool_name_visible", "step_sequence_visible", "workflow_graph_on_screen", "cursor_or_click_visible")]
    elif specialist == "criativo":
        pick = [e for e in ev if e["status"] in SAID_STATUS or e["status"] == "observed_visual" or e["source_type"] == "scene_detection"]
    elif specialist == "implementacao":
        ids = {i for c in (upstream or []) for i in c.get("evidence_ids", [])}
        pick = [e for e in ev if e["id"] in ids]
    else:
        pick = []
    return pick[:MAX_PER_TASK]


def seconds(t: Optional[float]) -> str:
    return "—" if t is None else f"{t:.1f}s"

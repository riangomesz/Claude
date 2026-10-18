"""Estrutura narrativa (Tarefa 11).

Blocos possíveis: gancho, contexto, problema, revelacao, demonstracao, beneficios, oferta, cta.
Nada presume a sequência clássica: blocos podem faltar, repetir, sobrepor-se ou ficar pendentes.
Cada bloco aponta para evidências temporais e tem um `support` próprio:
    supported_visual   (tag visual compatível)
    mentioned_speech   (pista textual na fala)
    suggested_metadata (pista na legenda; sem tempo próprio)
    hypothesis         (só posição temporal, ex.: início do vídeo como possível gancho)
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from ._matcher import compile_keyword, normalize
from .contract import TIME_TOLERANCE_S

BLOCK_TYPES = ("gancho", "contexto", "problema", "revelacao", "demonstracao", "beneficios", "oferta", "cta")
BLOCK_STATES = ("suggested", "confirmed", "rejected", "pending")
HOOK_WINDOW_S = 3.0

TEXT_CUES: Dict[str, List[str]] = {
    "gancho": ["voce nao vai acreditar", "pare de", "para tudo", "olha isso", "ninguem fala", "wait"],
    "contexto": ["hoje eu vou", "nesse video", "neste video", "today i", "in this video"],
    "problema": ["problema", "dificil", "cansado de", "voce perde", "o erro", "sem saber", "struggle", "problem"],
    "revelacao": ["segredo", "ninguem te conta", "descobri", "o truque", "the secret", "the trick"],
    "demonstracao": ["vou mostrar", "olha aqui", "olha so", "clica", "clique", "seleciona", "aperta", "let me show"],
    "beneficios": ["mais rapido", "economiza", "sem precisar", "automatico", "de graca", "em minutos", "faster", "save time"],
    "oferta": ["desconto", "cupom", "gratis por", "semana gratis", "oferta", "teste gratis", "discount", "free trial"],
    "cta": ["link na bio", "comenta", "comente", "salva esse", "salve esse", "segue", "siga", "clica no link", "link in bio", "follow"],
}
# Pista dentro de uma frase excluída não conta ("clica no link" é CTA, não demonstração).
TEXT_EXCLUDE: Dict[str, List[str]] = {
    "demonstracao": ["clica no link", "clique no link", "clica no botao seguir", "olha so que preco"],
    "beneficios": ["automatico do carro", "cambio automatico"],
}
VISUAL_CUES = {
    "ui_screen_visible": "demonstracao", "step_sequence_visible": "demonstracao", "cursor_or_click_visible": "demonstracao",
    "sales_offer_on_screen": "oferta", "price_or_discount_on_screen": "oferta",
}

_PATTERNS = {b: [(c, compile_keyword(c)) for c in cues] for b, cues in TEXT_CUES.items()}
_EXCLUDE = {b: [compile_keyword(c) for c in cues] for b, cues in TEXT_EXCLUDE.items()}


def _cue_hits(btype: str, norm: str) -> List[str]:
    spans = [m.span() for p in _EXCLUDE.get(btype, []) for m in p.finditer(norm)]
    hits = []
    for cue, pat in _PATTERNS[btype]:
        for m in pat.finditer(norm):
            if not any(a <= m.start() and m.end() <= b for a, b in spans):
                hits.append(cue)
                break
    return hits


def _block_id(btype: str, t0: Optional[float], t1: Optional[float], source: str) -> str:
    t = "na" if t0 is None else f"{t0:.3f}-{t1:.3f}"
    return f"nb_{btype}_{t}_{source}"


def suggest_blocks(doc: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Sugere blocos a partir das evidências. Tudo nasce `suggested`, nunca `confirmed`."""
    blocks: Dict[str, Dict[str, Any]] = {}

    def add(btype, t0, t1, ev, support, rule, cues=()):
        bid = _block_id(btype, t0, t1, rule)
        b = blocks.setdefault(bid, {"block_id": bid, "type": btype, "t_start_s": t0, "t_end_s": t1,
                                    "evidence_ids": [], "support": support, "status": "suggested",
                                    "rule": rule, "cues": []})
        if ev["evidence_id"] not in b["evidence_ids"]:
            b["evidence_ids"].append(ev["evidence_id"])
        b["cues"] = sorted(set(b["cues"]) | set(cues))

    speech = sorted((e for e in doc.get("evidence", []) if e["status"] == "transcript_claim"),
                    key=lambda e: (e["t_start_s"], e["evidence_id"]))
    for e in speech:
        norm = normalize(e["claim"])
        for btype in _PATTERNS:
            hits = _cue_hits(btype, norm)
            if hits:
                add(btype, e["t_start_s"], e["t_end_s"], e, "mentioned_speech", "text_cue", hits)
    if speech and speech[0]["t_start_s"] <= HOOK_WINDOW_S:
        first = speech[0]
        if not any(b["type"] == "gancho" and b["t_start_s"] == first["t_start_s"] for b in blocks.values()):
            add("gancho", first["t_start_s"], first["t_end_s"], first, "hypothesis", "posicao_inicial")
    for e in doc.get("evidence", []):
        if e["status"] == "observed_visual" and e.get("tag") in VISUAL_CUES:
            add(VISUAL_CUES[e["tag"]], e["t_start_s"], e["t_end_s"], e, "supported_visual", "visual_cue")
        if e["status"] == "metadata_claim":
            norm = normalize(e["claim"])
            for btype in ("oferta", "cta"):
                hits = _cue_hits(btype, norm)
                if hits:
                    add(btype, None, None, e, "suggested_metadata", "metadata_cue", hits)
    return sorted(blocks.values(), key=lambda b: (b["t_start_s"] is None, b["t_start_s"] or 0, b["type"], b["block_id"]))


def validate_blocks(doc: Dict[str, Any]) -> List[str]:
    p: List[str] = []
    dur = (doc.get("video") or {}).get("duration_s")
    ev_ids = {e.get("evidence_id") for e in doc.get("evidence", [])}
    seen = set()
    for b in doc.get("narrative_blocks", []):
        bid = b.get("block_id")
        if bid in seen:
            p.append(f"narrative:{bid}: block_id duplicado")
        seen.add(bid)
        if b.get("type") not in BLOCK_TYPES:
            p.append(f"narrative:{bid}: tipo inválido {b.get('type')}")
        if b.get("status") not in BLOCK_STATES:
            p.append(f"narrative:{bid}: status inválido {b.get('status')}")
        t0, t1 = b.get("t_start_s"), b.get("t_end_s")
        if (t0 is None) != (t1 is None):
            p.append(f"narrative:{bid}: intervalo incompleto")
        elif t0 is not None and (t0 < 0 or t1 < t0 or (dur and t1 > dur + TIME_TOLERANCE_S)):
            p.append(f"narrative:{bid}: intervalo inválido ({t0}, {t1})")
        missing = [i for i in b.get("evidence_ids", []) if i not in ev_ids]
        if missing:
            p.append(f"narrative:{bid}: evidência inexistente {missing}")
        if b.get("status") == "confirmed" and not b.get("evidence_ids") and not b.get("confirmed_by"):
            p.append(f"narrative:{bid}: bloco confirmado sem evidência nem revisor")
    return p


def coverage(doc: Dict[str, Any], min_gap_s: float = 1.0) -> Dict[str, Any]:
    """Tipos ausentes, lacunas temporais sem bloco e sobreposições (sobreposição é informação, não erro)."""
    dur = doc["video"]["duration_s"]
    timed = sorted((b for b in doc.get("narrative_blocks", []) if b.get("t_start_s") is not None and b.get("status") != "rejected"),
                   key=lambda b: (b["t_start_s"], b["t_end_s"]))
    gaps, overlaps, cursor = [], [], 0.0
    for i, b in enumerate(timed):
        if b["t_start_s"] - cursor >= min_gap_s:
            gaps.append((round(cursor, 3), b["t_start_s"]))
        for o in timed[i + 1:]:
            if o["t_start_s"] < b["t_end_s"]:
                overlaps.append((b["block_id"], o["block_id"]))
        cursor = max(cursor, b["t_end_s"])
    if dur - cursor >= min_gap_s:
        gaps.append((round(cursor, 3), dur))
    present = {b["type"] for b in doc.get("narrative_blocks", []) if b.get("status") != "rejected"}
    return {"missing_types": [t for t in BLOCK_TYPES if t not in present], "gaps": gaps, "overlaps": overlaps}

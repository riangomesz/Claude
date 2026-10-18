"""Biblioteca de técnicas reproduzíveis (Missão Suprema 02, Tarefa 12).

Consultas sobre o banco do `ii_mm`, sempre na análise corrente de cada referência, devolvendo a origem
de cada evidência e o que ela NÃO prova. Sugestões de reprodução saem rotuladas como proposta criativa,
nunca como reconstrução do vídeo.
"""
from __future__ import annotations

import json
import sqlite3
from typing import Any, Dict, List, Optional, Sequence

from .techniques import LEVEL_PROVES
from .vocabulary import AI_TOOLS, TECHNIQUES

DEMONSTRATED_LEVELS = ("observed_in_frame", "frame_pair_difference", "temporal_sequence")
CURRENT = ("SELECT a.analysis_id, rv.reference_id FROM ref_videos rv CROSS JOIN analyses a "
           "ON a.video_pk = rv.video_pk WHERE a.status = 'current'")


def _docs(conn: sqlite3.Connection, analysis_ids: Sequence[str]) -> Dict[str, Dict[str, Any]]:
    if not analysis_ids:
        return {}
    marks = ",".join("?" * len(analysis_ids))
    return {r["analysis_id"]: json.loads(r["document_json"])
            for r in conn.execute(f"SELECT analysis_id, document_json FROM analyses WHERE analysis_id IN ({marks})", list(analysis_ids))}


def _evidence_view(doc: Dict[str, Any], ids: Sequence[str]) -> List[Dict[str, Any]]:
    ev = {e["evidence_id"]: e for e in doc["evidence"]}
    out = []
    for i in ids:
        e = ev.get(i)
        if e:
            out.append({"evidence_id": i, "status": e["status"], "basis": e.get("basis"), "t_start_s": e.get("t_start_s"),
                        "claim": e["claim"][:200], "source": e["provenance"].get("source"),
                        "observer": e["provenance"].get("observer"), "attributes": (e.get("extra") or {}).get("attributes")})
    return out


def references_with_technique(conn: sqlite3.Connection, technique: str, levels: Optional[Sequence[str]] = None,
                              limit: int = 50) -> List[Dict[str, Any]]:
    """Ex.: "Quais vídeos utilizam split screen?" → cada resultado diz o nível de prova e as evidências."""
    if technique not in TECHNIQUES:
        raise ValueError(f"técnica desconhecida: {technique}")
    lv = list(levels or LEVEL_PROVES)
    marks = ",".join("?" * len(lv))
    rows = conn.execute(f"SELECT c.reference_id, c.analysis_id, t.level FROM ({CURRENT}) c JOIN techniques t "
                        f"ON t.analysis_id = c.analysis_id WHERE t.technique = ? AND t.level IN ({marks}) "
                        "ORDER BY c.reference_id, t.level LIMIT ?", [technique] + lv + [limit]).fetchall()
    docs = _docs(conn, sorted({r["analysis_id"] for r in rows}))
    out = []
    for r in rows:
        doc = docs[r["analysis_id"]]
        t = next(x for x in doc["techniques"] if x["technique"] == technique and x["level"] == r["level"])
        out.append({"reference_id": r["reference_id"], "level": r["level"], "demonstrated": r["level"] in DEMONSTRATED_LEVELS,
                    "proves": LEVEL_PROVES[r["level"]][0], "does_not_prove": LEVEL_PROVES[r["level"]][1],
                    "evidence": _evidence_view(doc, t.get("evidence_ids", []))})
    return out


def references_with_caption_style(conn: sqlite3.Connection, size: Optional[str] = None, words_per_caption: Optional[int] = None,
                                  position: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
    """Ex.: "legendas grandes e palavras isoladas" → atributos estruturados de observações `burned_caption`."""
    wanted = [f"attr:burned_caption:{k}={v}" for k, v in (("size", size), ("words_per_caption", words_per_caption), ("position", position)) if v is not None]
    if not wanted:
        raise ValueError("informe ao menos um atributo")
    conds = " AND ".join("EXISTS (SELECT 1 FROM search_terms s WHERE s.term = ? AND s.analysis_id = c.analysis_id)" for _ in wanted)
    rows = conn.execute(f"SELECT c.reference_id, c.analysis_id FROM ({CURRENT}) c WHERE {conds} ORDER BY c.reference_id LIMIT ?",
                        wanted + [limit]).fetchall()
    docs = _docs(conn, [r["analysis_id"] for r in rows])
    out = []
    for r in rows:
        doc = docs[r["analysis_id"]]
        ids = [e["evidence_id"] for e in doc["evidence"] if e.get("tag") == "burned_caption" and e["status"] == "observed_visual"]
        out.append({"reference_id": r["reference_id"], "evidence": _evidence_view(doc, ids),
                    "limitation": "atributos registrados por observador em quadros estáticos; animação da legenda não é provada"})
    return out


def references_with_ai_tool_interface(conn: sqlite3.Connection, limit: int = 50) -> List[Dict[str, Any]]:
    """Ex.: "Quais exemplos apresentam interfaces de ferramentas de IA?" (nome legível × reconhecido pela aparência)."""
    marks = ",".join("?" * len(AI_TOOLS))
    rows = conn.execute(
        f"SELECT c.reference_id, c.analysis_id, t.name, t.status FROM ({CURRENT}) c JOIN tools t ON t.analysis_id = c.analysis_id "
        f"WHERE t.name IN ({marks}) AND t.status IN ('visually_identified', 'inferred') "
        "AND EXISTS (SELECT 1 FROM evidence e WHERE e.analysis_id = c.analysis_id AND e.tag IN ('ui_screen_visible','tool_name_visible','logo_visible')) "
        "ORDER BY c.reference_id, t.name LIMIT ?", sorted(AI_TOOLS) + [limit]).fetchall()
    return [{"reference_id": r["reference_id"], "tool": r["name"], "identification": r["status"],
             "note": "nome ou logotipo legível no quadro" if r["status"] == "visually_identified"
                     else "interface reconhecida pela aparência (conhecimento externo do observador); nome não verificado"} for r in rows]


def technique_overview(conn: sqlite3.Connection) -> Dict[str, Dict[str, int]]:
    """Ex.: "Quais técnicas são demonstradas e quais são apenas hipóteses?" (contagem de REFERÊNCIAS por nível)."""
    out: Dict[str, Dict[str, int]] = {}
    for r in conn.execute(f"SELECT t.technique, t.level, COUNT(DISTINCT c.reference_id) AS n FROM ({CURRENT}) c "
                          "JOIN techniques t ON t.analysis_id = c.analysis_id GROUP BY t.technique, t.level ORDER BY t.technique"):
        bucket = "demonstrated" if r["level"] in DEMONSTRATED_LEVELS else "hypothesis_only" if r["level"] == "hypothesis" else "suggestions"
        d = out.setdefault(r["technique"], {"demonstrated": 0, "hypothesis_only": 0, "suggestions": 0})
        d[bucket] += r["n"]
    return out


def reproduction_guide(conn: sqlite3.Connection, technique: str, limit: int = 20) -> Dict[str, Any]:
    """Ex.: "Como reproduzir este estilo?" Ideias rotuladas como proposta criativa, com o que foi observado ao lado."""
    observed = references_with_technique(conn, technique, DEMONSTRATED_LEVELS, limit)
    rows = references_with_technique(conn, technique, ["reproduction_suggestion"], limit)
    ideas = []
    for r in rows:
        aid = conn.execute(f"SELECT analysis_id FROM ({CURRENT}) WHERE reference_id = ?", (r["reference_id"],)).fetchone()[0]
        doc = _docs(conn, [aid])[aid]
        t = next(x for x in doc["techniques"] if x["technique"] == technique and x["level"] == "reproduction_suggestion")
        for i in t.get("ideas", []):
            ideas.append({"reference_id": r["reference_id"], "text": i["text"], "requires": i.get("requires", []), "author": i.get("author")})
    return {
        "technique": technique, "description": TECHNIQUES[technique], "status": "proposta_criativa",
        "disclaimer": "As ideias abaixo são propostas de produção. Não reconstroem nem afirmam como os vídeos originais foram feitos.",
        "observed_examples": [{"reference_id": o["reference_id"], "level": o["level"], "does_not_prove": o["does_not_prove"]} for o in observed],
        "ideas": ideas,
        "still_needs_continuous_video": sorted({o["reference_id"] for o in observed if o["level"] != "temporal_sequence"}),
    }

"""Engenharia reversa audiovisual (Tarefa 12).

Cinco níveis de prova, nunca confundidos:
1. observed_in_frame       técnica visível num quadro (ex.: tela dividida)
2. frame_pair_difference   diferença entre DOIS quadros (ex.: escala maior = possível punch-in)
3. temporal_sequence       movimento observado em trecho CONTÍNUO de vídeo (quadros amostrados não bastam)
4. hypothesis              técnica suposta, sem prova suficiente
5. reproduction_suggestion ideia criativa de como reproduzir (não é afirmação sobre o vídeo)

Um par de quadros NUNCA vira prova de animação contínua.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from .vocabulary import TECHNIQUES, VISUAL_TAGS

PAIR_TAGS = {"punch_in_scale", "jump_cut_pair", "cut_pair"}  # só fazem sentido comparando dois instantes
LEVEL_PROVES = {
    "observed_in_frame": ("a técnica aparece no quadro", "como ela surge, quanto dura ou se é animada"),
    "frame_pair_difference": ("houve mudança entre dois instantes", "a trajetória, a curva de movimento ou se houve animação contínua"),
    "temporal_sequence": ("o movimento foi observado em trecho contínuo de vídeo",
                          "qual efeito, transição, preset ou ferramenta produziu o movimento"),
    "hypothesis": ("nada; é uma suposição registrada", "a própria técnica"),
    "reproduction_suggestion": ("nada sobre o vídeo; é uma ideia de produção", "que o vídeo original foi feito assim"),
}


def level_for(evidence: Dict[str, Any]) -> Optional[str]:
    tag = evidence.get("tag")
    spec = VISUAL_TAGS.get(tag)
    if not spec or not spec.technique:
        return None
    if evidence["status"] == "inference":
        return "hypothesis"
    if evidence["status"] != "observed_visual":
        return None
    basis = evidence.get("basis")
    if spec.motion:
        # Quadros amostrados (mesmo 3 ou mais) mostram variação, não o mecanismo: só trecho contínuo vale.
        return "temporal_sequence" if basis == "video_clip" else "hypothesis"
    if tag in PAIR_TAGS:
        return "frame_pair_difference" if basis in ("frame_pair", "frame_sequence", "video_clip") else "hypothesis"
    return "observed_in_frame"


def build_techniques(doc: Dict[str, Any], suggestions: Sequence[Dict[str, Any]] = ()) -> List[Dict[str, Any]]:
    """Agrupa evidências por (técnica, nível). Sugestões de reprodução entram como nível 5."""
    groups: Dict[tuple, Dict[str, Any]] = {}
    for e in doc.get("evidence", []):
        lvl = level_for(e)
        if not lvl:
            continue
        tech = VISUAL_TAGS[e["tag"]].technique
        g = groups.setdefault((tech, lvl), {"technique": tech, "level": lvl, "evidence_ids": [], "timestamps": []})
        g["evidence_ids"].append(e["evidence_id"])
        g["timestamps"].append([e["t_start_s"], e["t_end_s"]])
    for s in suggestions:
        tech = s["technique"]
        if tech not in TECHNIQUES:
            raise ValueError(f"técnica desconhecida: {tech}")
        g = groups.setdefault((tech, "reproduction_suggestion"), {"technique": tech, "level": "reproduction_suggestion",
                                                                   "evidence_ids": [], "timestamps": [], "ideas": []})
        g["ideas"].append({"text": s["text"], "requires": list(s.get("requires", [])), "author": s.get("author", "desconhecido")})
        g["evidence_ids"] = sorted(set(g["evidence_ids"]) | set(s.get("based_on", [])))
    out = []
    order = list(LEVEL_PROVES)
    for (tech, lvl), g in sorted(groups.items(), key=lambda kv: (kv[0][0], order.index(kv[0][1]))):
        g["evidence_ids"] = sorted(set(g["evidence_ids"]))
        g["timestamps"] = sorted(g["timestamps"], key=lambda t: (t[0] is None, t[0] or 0))
        g["proves"], g["does_not_prove"] = LEVEL_PROVES[lvl]
        g["description"] = TECHNIQUES[tech]
        out.append(g)
    return out


def open_questions(techniques: Sequence[Dict[str, Any]]) -> List[str]:
    """O que ainda depende de observar o vídeo contínuo."""
    qs = []
    for t in techniques:
        if t["level"] in ("frame_pair_difference", "hypothesis"):
            qs.append(f"{t['technique']}: confirmar com sequência de quadros ou trecho de vídeo ({t['does_not_prove']})")
    return qs

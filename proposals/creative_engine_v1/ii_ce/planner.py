"""Planejador de investigação: escolhe especialistas por NECESSIDADE e registra o motivo de cada escolha e de cada corte."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from .contracts import DEPTHS, SPECIALISTS

STRONG_SUPPORT = ("supported_visual", "supported_measured")
USABLE_SUPPORT = STRONG_SUPPORT + ("mentioned_speech", "suggested_metadata")
GROUPS = {"tecnico": {"tutorial", "demonstracao_ferramenta"}, "automacao": {"automacao"},
          "edicao": {"edicao_audiovisual", "cinematografia", "motion_design", "referencia_estetica"}, "marketing": {"marketing_vendas"}}
# Ordem de prioridade por tipo de referência. `implementacao` sempre vem depois de `reproducao` (depende dela).
ORDER = {
    "simples": ["audiovisual"],
    "tutorial_tecnico": ["reproducao", "implementacao", "audiovisual"],
    "edit_cinematografico": ["audiovisual", "criativo"],
    "workflow_automacao": ["reproducao", "implementacao"],
    "marketing": ["criativo", "audiovisual"],
    "complexo": ["audiovisual", "reproducao", "criativo", "implementacao"],
}
DEPENDS = {"implementacao": ["reproducao"]}
BASE_CALLS = {"light": 1, "standard": 2, "deep": 4}
EST_FALLBACK = 0.0


def classify_reference(bundle: Dict[str, Any]) -> Dict[str, Any]:
    if not bundle["evidence"]:
        return {"reference_kind": "sem_evidencia", "reasons": ["a referência não tem análise corrente; nada a investigar ainda"]}
    cats = [c for c in bundle["facets"].get("categories", []) if c["support"] in USABLE_SUPPORT]
    names = {c["category"] for c in cats}
    hit = {g: sorted(names & members) for g, members in GROUPS.items() if names & members}
    strong = [c["category"] for c in cats if c["support"] in STRONG_SUPPORT]
    desc = ", ".join(f"{c['category']} ({c['support']})" for c in cats) or "nenhuma categoria com suporte"
    if len(hit) >= 3 and len(strong) >= 3:
        kind = "complexo"
    elif "automacao" in names and not (names & {"edicao_audiovisual", "cinematografia", "motion_design"}):
        kind = "workflow_automacao"
    elif "tecnico" in hit:
        kind = "tutorial_tecnico"
    elif "edicao" in hit:
        kind = "edit_cinematografico"
    elif "marketing" in hit:
        kind = "marketing"
    else:
        kind = "simples"
    return {"reference_kind": kind, "reasons": [f"categorias com suporte: {desc}", f"grupos acionados: {', '.join(sorted(hit)) or 'nenhum'}; fortes: {len(strong)}"]}


def plan(bundle: Dict[str, Any], depth: str = "standard", limits: Optional[Dict[str, Any]] = None,
         estimate=lambda s: 0.0, registered=lambda s: True) -> Dict[str, Any]:
    if depth not in DEPTHS:
        raise ValueError(f"profundidade inválida: {depth}")
    limits = dict(limits or {})
    info = classify_reference(bundle)
    kind = info["reference_kind"]
    out: Dict[str, Any] = {"reference_kind": kind, "kind_reasons": info["reasons"], "depth": depth, "limits": limits, "tasks": []}
    if kind == "sem_evidencia":
        return out
    order = ORDER[kind]
    n = BASE_CALLS[depth] + (1 if kind == "complexo" and depth == "standard" else 0)
    max_calls = int(limits["max_calls"]) if limits.get("max_calls") is not None else None
    max_usd = float(limits["max_usd"]) if limits.get("max_usd") is not None else None
    spent, calls, chosen = 0.0, 0, set()
    for i, spec in enumerate(order):
        deps = DEPENDS.get(spec, [])
        est = float(estimate(spec))
        t = {"specialist": spec, "kind": SPECIALISTS[spec]["kind"], "depends_on": [d for d in deps if d in order], "est_usd": est,
             "selected": False, "reason": ""}
        if i >= n:
            t["reason"] = f"fora da profundidade '{depth}' (limite de {n} especialista(s)); prioridade {i + 1} para '{kind}'"
        elif max_calls is not None and calls >= max_calls:
            t["reason"] = f"limite_de_chamadas ({max_calls})"
        elif max_usd is not None and spent + est > max_usd:
            t["reason"] = f"limite_de_custo (estimado {spent + est:.2f} > {max_usd:.2f} USD)"
        elif any(d not in chosen for d in t["depends_on"]):
            t["reason"] = "dependência não selecionada: " + ", ".join(d for d in t["depends_on"] if d not in chosen)
        else:
            t["selected"] = True
            chosen.add(spec)
            calls += 1
            spent += est
            why = {"audiovisual": "evidências visuais e medidas precisam de leitura separando observação de inferência",
                   "reproducao": "há processo/ferramenta a reproduzir; reprodução técnica priorizada",
                   "criativo": "narrativa, gancho e direção de arte alimentam a adaptação comercial",
                   "implementacao": "transforma processos e ferramentas já identificados em requisitos implementáveis (depende de reproducao)"}[spec]
            t["reason"] = f"{kind}: {why}"
            if not registered(spec):
                t["reason"] += " [sem provedor registrado: ficará bloqueada até haver um]"
        out["tasks"].append(t)
    out["estimated_usd"] = round(spent, 4)
    return out

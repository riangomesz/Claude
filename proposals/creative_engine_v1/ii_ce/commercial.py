"""Perfis comerciais (arquivos JSON versionados, fora do código) e motor de adaptação criativa.

A saída é PROPOSTA: usa princípios criativos observados (ou ditos) na referência, nunca copia planos, textos ou identidade do autor.
Cada princípio aponta para as chaves de afirmação que o sustentam e para o estado de verificação delas."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List

from .contracts import SCHEMA_PROFILE, ContractError, canonical_json, clean_text, digest
from .knowledge_base import PRINCIPLES

REQUIRED = ("profile_id", "version", "name", "summary", "offerings", "audiences", "constraints", "angles")
ANGLE_REQUIRED = ("id", "name", "objective", "audience", "concept", "message", "structure", "art_direction", "camera", "editing", "tools", "quality", "principles", "opportunity", "result")


def load_profile(path: Path) -> Dict[str, Any]:
    try:
        p = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ContractError(f"perfil ilegível: {path}: {exc}") from exc
    if not isinstance(p, dict) or p.get("schema_version") != SCHEMA_PROFILE:
        raise ContractError(f"perfil fora do esquema {SCHEMA_PROFILE}: {path}")
    miss = [k for k in REQUIRED if k not in p]
    if miss or not isinstance(p["angles"], list) or not p["angles"]:
        raise ContractError(f"perfil incompleto ({miss or 'angles'}): {path}")
    for a in p["angles"]:
        am = [k for k in ANGLE_REQUIRED if k not in a]
        if am or any(x not in PRINCIPLES for x in a["principles"]):
            raise ContractError(f"ângulo inválido em {p['profile_id']} ({am or 'princípio desconhecido'})")
    p["hash"] = digest(p, n=16)
    return p


def load_profiles(directory: Path, ids: Iterable[str]) -> Dict[str, Dict[str, Any]]:
    out = {}
    for pid in ids:
        if not pid.replace("_", "").isalnum():
            raise ContractError(f"id de perfil inválido: {pid}")
        f = Path(directory) / f"{pid}.json"
        if not f.is_file():
            raise ContractError(f"perfil não encontrado: {pid}")
        out[pid] = load_profile(f)
    return out


def derive_principles(bundle: Dict[str, Any], groups: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Princípios criativos presentes na referência. Só entra o que tem base em afirmações NÃO rejeitadas por humano."""
    live = {g["key"]: g for g in groups if g.get("human_state") != "rejected"}
    keys = set(live)
    cats = {c["category"] for c in bundle["facets"].get("categories", []) if c["support"] in ("supported_visual", "supported_measured", "mentioned_speech")}
    n_scenes = len([k for k in keys if k.startswith("cena:")])

    def has(*prefixes):
        return sorted(k for k in keys if any(k == p or k.startswith(p) for p in prefixes))
    rules = {
        "gancho_verbal": has("narrativa:gancho"),
        "texto_na_tela": has("tecnica:legenda_sobreposta", "tecnica:legenda_animada", "tecnica:tipografia"),
        "demonstracao_de_processo": has("passo:", "visual:ui_screen_visible", "visual:step_sequence_visible") + (["categoria:tutorial"] if "tutorial" in cats or "demonstracao_ferramenta" in cats else []),
        "enfase_por_escala": has("tecnica:punch_in"),
        "ritmo_de_corte": has("tecnica:jump_cut", "tecnica:corte") + (["cena:*"] if n_scenes >= 3 else []),
        "prova_visual": has("visual:"),
        "composicao_cuidada": has("tecnica:composicao_cinematografica") + (["categoria:cinematografia"] if "cinematografia" in cats else []),
        "chamada_comercial": has("narrativa:oferta") + (["categoria:marketing_vendas"] if "marketing_vendas" in cats else []),
    }
    out = {}
    for p, basis in rules.items():
        if basis:
            states = sorted({live[k]["state"] for k in basis if k in live})
            out[p] = {"mechanism": PRINCIPLES[p], "basis": basis, "states": states or ["categoria"]}
    return out


def adapt(bundle: Dict[str, Any], groups: List[Dict[str, Any]], profile: Dict[str, Any], n: int = 2) -> List[Dict[str, Any]]:
    principles = derive_principles(bundle, groups)
    pset = set(principles)
    angles = sorted(profile["angles"], key=lambda a: (-len(pset & set(a["principles"])), a["id"]))
    unverified = [g for g in groups if g["state"] in ("hypothesis", "claimed", "unverified", "contradicted") and g["kind"] in ("technique", "tool", "process")]
    out = []
    for a in angles[:n]:
        used = [p for p in a["principles"] if p in pset]
        missing = [p for p in a["principles"] if p not in pset]
        complexity = "baixa" if len(a["tools"]) <= 2 else "média" if len(a["tools"]) == 3 else "alta"
        out.append({
            "proposal_id": "prop_" + digest(profile["profile_id"], profile["version"], a["id"], sorted(used)),
            "profile_id": profile["profile_id"], "profile_version": profile["version"], "angle_id": a["id"], "origin": "proposta",
            "objetivo_comercial": a["objective"], "publico_alvo": a["audience"],
            "conceito_criativo": a["concept"], "mensagem_central": a["message"], "estrutura_narrativa": list(a["structure"]),
            "direcao_de_arte": a["art_direction"] + " Linguagem visual do perfil: " + ", ".join(profile.get("visual_language", [])) + ".",
            "linguagem_de_camera": a["camera"], "estrategia_de_edicao": a["editing"], "ferramentas_indicadas": list(a["tools"]),
            "resultado_esperado": a["result"], "medicao_de_qualidade": list(a["quality"]),
            "oportunidade_comercial": a["opportunity"], "complexidade": complexity,
            "principios_aplicados": [{"principle": p, "mechanism": principles[p]["mechanism"], "basis_keys": principles[p]["basis"], "basis_states": principles[p]["states"]} for p in used],
            "principios_do_angulo_sem_base_na_referencia": missing,
            "riscos_e_restricoes": list(profile["constraints"]) + ["não copiar planos, textos, voz ou identidade do autor da referência"] +
                                   ([f"{len(unverified)} técnica(s)/ferramenta(s) da referência ainda não verificadas: validar antes de prometer o mesmo resultado"] if unverified else []),
            "requisitos": sorted({t for t in a["tools"]}),
        })
    return out

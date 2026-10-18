"""Regras centrais de apoio (support) de categorias. Ordinal, sem números de confiança."""
from __future__ import annotations

from typing import Dict, Iterable, Mapping

CATEGORIES = (
    "conhecimento",
    "tutorial",
    "demonstracao_ferramenta",
    "automacao",
    "motion_design",
    "edicao_audiovisual",
    "marketing_vendas",
    "cinematografia",
    "referencia_estetica",
)

# Do mais forte ao mais fraco.
SUPPORT_LEVELS = (
    "supported_visual",    # sustentado por evidência visual
    "supported_measured",  # sustentado por medição
    "mentioned_speech",    # mencionado na fala
    "suggested_metadata",  # sugerido por metadados
    "hypothesis",          # hipótese (inferência)
    "insufficient",        # insuficiente
)

STATUS_TO_SUPPORT: Dict[str, str] = {
    "observed_visual": "supported_visual",
    "measured_signal": "supported_measured",
    "transcript_claim": "mentioned_speech",
    "metadata_claim": "suggested_metadata",
    "inference": "hypothesis",
    "unverified": "insufficient",
}

# Nomes de categoria do contrato v1 -> v2.
V1_TO_V2_CATEGORY = {
    "automacao_ia": "automacao",
    "conteudo_cinematografico": "cinematografia",
}


def category_support(evidence: Iterable[Mapping]) -> str:
    """Nível do apoio = status da melhor evidência a favor; sem evidência = insufficient."""
    levels = {STATUS_TO_SUPPORT.get(e.get("status"), "insufficient") for e in evidence}
    for lvl in SUPPORT_LEVELS:
        if lvl in levels:
            return lvl
    return "insufficient"


def stronger(a: str, b: str) -> bool:
    return SUPPORT_LEVELS.index(a) < SUPPORT_LEVELS.index(b)

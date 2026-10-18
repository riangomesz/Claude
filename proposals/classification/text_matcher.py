"""
Proposta: matcher de texto por fronteira de palavra, sem acento, com ranking multi-rótulo.

Substitui o padrão `kw in texto` de core/curation.py::suggest_editorial_category, que
casa substrings ("bot" em "robotics", "copy" em "copy of receipt") e devolve o primeiro
rótulo que casar, em vez do melhor. Somente stdlib; não importa nada do Projeto-MVP.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Dict, Iterable, List, Sequence, Tuple


def normalize(text: str) -> str:
    """Minúsculas, sem acentos, '#' e pontuação viram espaço.

    Acentos (marcas combinantes) são removidos; qualquer outro caractere fora do ASCII
    (travessão, aspas curvas, emoji, reticências) vira espaço para não colar palavras vizinhas.
    """
    t = unicodedata.normalize("NFKD", str(text or "").lower())
    t = "".join("" if unicodedata.combining(ch) else (ch if ch.isascii() else " ") for ch in t)
    t = re.sub(r"[^a-z0-9.+]+", " ", t)
    # ponto só é preservado dentro de um token ("make.com", "1.5"); reticências e ponto final viram espaço
    t = re.sub(r"(?<![a-z0-9])\.+|\.+(?![a-z0-9])", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def _compile(keyword: str) -> re.Pattern[str]:
    words = normalize(keyword).split()
    body = r"\s+".join(re.escape(w) for w in words)
    return re.compile(rf"(?<![a-z0-9]){body}(?![a-z0-9])")


class RankedMatcher:
    """rules: {rótulo: [palavras ou frases]}. Cada palavra distinta conta uma vez."""

    def __init__(self, rules: Dict[str, Sequence[str]]):
        self._rules: Dict[str, List[Tuple[str, re.Pattern[str]]]] = {
            label: [(k, _compile(k)) for k in kws] for label, kws in rules.items()
        }

    def rank(self, text: str) -> List[Tuple[str, List[str]]]:
        """Rótulos com pelo menos um acerto, do mais ao menos evidenciado (empate: ordem das regras)."""
        norm = f" {normalize(text)} "
        hits = []
        for order, (label, pats) in enumerate(self._rules.items()):
            matched = [k for k, p in pats if p.search(norm.strip())]
            if matched:
                hits.append((-len(matched), order, label, matched))
        hits.sort()
        return [(label, matched) for _, _, label, matched in hits]

    def best(self, text: str) -> Tuple[str, List[str]] | None:
        ranked = self.rank(text)
        return ranked[0] if ranked else None


def has_any(text: str, keywords: Iterable[str]) -> List[str]:
    """Palavras de `keywords` presentes em `text` por fronteira de palavra."""
    norm = normalize(text)
    return [k for k in keywords if _compile(k).search(norm)]

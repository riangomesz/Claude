"""Classificador textual v2 (Tarefa 04), base para a evidência textual do classificador multimodal.

Evolui o `text_matcher.RankedMatcher`:
1. Fronteira de palavra e sem acento (herdado de text_matcher.normalize).
2. Termos FORTES e FRACOS. Termo fraco é ambíguo entre PT/EN ou é palavra comum ("ia" = verbo ir,
   "ai" = interjeição, "app", "edit", "corte"); sozinho não atribui categoria, só reforça um forte.
3. Contextos de exclusão: um termo dentro de uma frase excluída não conta ("corte de cabelo").
4. Hashtags compostas: "#motiondesign" casa com a frase "motion design".
5. Saída sem ordem arbitrária: categorias em ordem canônica e as evidências (termos e posições) expostas.
   Não há score numérico: `strength` é "strong" (≥1 termo forte) ou "weak_only" (pendente de revisão).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from ._matcher import compile_keyword, normalize
from .evidence_rules import CATEGORIES

RULES: Dict[str, Dict[str, List[str]]] = {
    "conhecimento": {
        "strong": ["voce sabia", "aprenda", "entenda", "explicando", "ensinando", "curiosidade", "did you know", "learn how", "explained"],
        "weak": ["dica", "dicas", "tip", "tips"],
        "exclude": [],
    },
    "tutorial": {
        "strong": ["tutorial", "passo a passo", "como fazer", "como criar", "step by step", "how to", "aprenda a", "guia completo"],
        "weak": ["primeiro", "em seguida", "depois", "first", "then", "next"],
        "exclude": [],
    },
    "demonstracao_ferramenta": {
        "strong": ["ferramenta", "plataforma", "aplicativo", "software", "olha so essa", "demonstracao", "tool", "review da"],
        "weak": ["app", "site", "olha aqui", "demo"],
        "exclude": ["app store"],
    },
    "automacao": {
        "strong": ["automacao", "automatizar", "automatiza", "automation", "automate", "n8n", "zapier", "make.com", "webhook",
                   "workflow", "fluxo automatico", "agente de ia", "agentes de ia", "ai agent", "ai agents", "rpa"],
        "weak": ["bot", "agente", "agent", "integracao"],
        "exclude": ["agente de viagens", "agente secreto", "agente imobiliario"],
    },
    "motion_design": {
        "strong": ["motion design", "motion graphics", "after effects", "keyframes", "keyframe", "tipografia animada",
                   "kinetic typography", "animacao 2d", "2d animation", "lottie"],
        "weak": ["motion", "animacao", "animation", "easing"],
        "exclude": ["slow motion", "stop motion"],
    },
    "edicao_audiovisual": {
        "strong": ["edicao de video", "video editing", "capcut", "premiere pro", "davinci resolve", "jump cut", "b-roll", "b roll",
                   "transicao", "transition", "color grading", "sound design", "decupagem"],
        "weak": ["edit", "edicao", "corte", "cortes", "cut", "premiere", "davinci"],
        "exclude": ["corte de cabelo", "corte de gastos", "corte de energia", "hair cut", "haircut", "edicao limitada", "limited edition"],
    },
    "marketing_vendas": {
        "strong": ["link na bio", "desconto", "cupom", "oferta", "compre agora", "garanta ja", "black friday", "link in bio",
                   "discount", "coupon", "vagas limitadas", "teste gratis", "gratis por", "free trial", "copywriting",
                   "prospeccao", "leads", "trafego pago", "funil de vendas", "geracao de leads", "lead generation"],
        "weak": ["gratis", "free", "clientes", "vendas", "venda", "sales", "assine", "storytelling", "viral", "copy"],
        "exclude": ["software livre"],
    },
    "cinematografia": {
        "strong": ["cinematografia", "cinematografico", "cinematic", "cinematography", "filmmaking", "direcao de fotografia",
                   "lente anamorfica", "anamorphic", "plano sequencia"],
        "weak": ["lente", "lens", "camera", "enquadramento"],
        "exclude": ["camera de seguranca", "camera do celular quebrou"],
    },
    "referencia_estetica": {
        "strong": ["moodboard", "referencia visual", "direcao de arte", "art direction", "paleta de cores", "color palette", "aesthetic"],
        "weak": ["estetica", "referencia", "vibe", "inspiracao", "inspiration"],
        "exclude": ["estetica automotiva", "clinica de estetica", "referencia bibliografica"],
    },
}

# Termos ambíguos globais (não pertencem a uma categoria): registrados para auditoria, nunca atribuem nada.
AMBIGUOUS_GLOBAL = {"ia", "ai", "dev", "make", "tech", "tools", "pro"}
# "IA" como tema só conta em frases inequívocas, que reforçam automação/ferramenta.
AI_STRONG_PHRASES = ["inteligencia artificial", "artificial intelligence", "ia generativa", "generative ai", "chatgpt",
                     "midjourney", "comfyui", "stable diffusion", "claude", "gemini", "openai", "llm"]


def _compile_with_compound(term: str) -> List[re.Pattern]:
    pats = [compile_keyword(term)]
    words = normalize(term).split()
    if len(words) > 1:  # hashtag composta: "motion design" -> "motiondesign"
        pats.append(compile_keyword("".join(words)))
    return pats


@dataclass
class Hit:
    term: str
    kind: str  # strong | weak
    start: int
    end: int


@dataclass
class CategoryMatch:
    category: str
    strength: str  # strong | weak_only
    hits: List[Hit] = field(default_factory=list)

    @property
    def terms(self) -> List[str]:
        return sorted({h.term for h in self.hits})


@dataclass
class TextResult:
    language: str
    matches: List[CategoryMatch]
    ai_topic_terms: List[str]
    excluded: List[str]
    ambiguous_seen: List[str]

    def categories(self, include_weak: bool = False) -> List[str]:
        return [m.category for m in self.matches if include_weak or m.strength == "strong"]


_PT = {"de", "que", "para", "com", "uma", "voce", "nao", "isso", "como", "esse", "essa", "aqui", "muito", "mais", "olha", "eu"}
_EN = {"the", "and", "you", "this", "that", "with", "for", "how", "what", "your", "is", "are", "it", "to", "of"}


def detect_language(norm_text: str) -> str:
    words = norm_text.split()
    pt = sum(w in _PT for w in words)
    en = sum(w in _EN for w in words)
    if pt == en:
        return "undetermined"
    return "pt" if pt > en else "en"


class TextClassifier:
    def __init__(self, rules: Optional[Dict[str, Dict[str, List[str]]]] = None):
        rules = rules or RULES
        unknown = set(rules) - set(CATEGORIES)
        if unknown:
            raise ValueError(f"categorias desconhecidas nas regras: {sorted(unknown)}")
        self._rules = {}
        for cat in CATEGORIES:  # ordem canônica, independente da ordem do dict recebido
            r = rules.get(cat)
            if not r:
                continue
            self._rules[cat] = {
                "strong": [(t, p) for t in r.get("strong", []) for p in _compile_with_compound(t)],
                "weak": [(t, p) for t in r.get("weak", []) for p in _compile_with_compound(t)],
                "exclude": [(t, p) for t in r.get("exclude", []) for p in _compile_with_compound(t)],
            }
        self._ai = [(t, p) for t in AI_STRONG_PHRASES for p in _compile_with_compound(t)]
        self._amb = [(t, compile_keyword(t)) for t in sorted(AMBIGUOUS_GLOBAL)]

    def classify(self, text: str) -> TextResult:
        norm = normalize(text)
        matches: List[CategoryMatch] = []
        excluded: List[str] = []
        for cat, r in self._rules.items():
            ex_spans: List[Tuple[int, int]] = []
            for term, pat in r["exclude"]:
                for m in pat.finditer(norm):
                    ex_spans.append(m.span())
            hits: List[Hit] = []
            for kind in ("strong", "weak"):
                for term, pat in r[kind]:
                    for m in pat.finditer(norm):
                        s, e = m.span()
                        if any(a <= s and e <= b for a, b in ex_spans):
                            excluded.append(f"{cat}:{term}")
                            continue
                        hits.append(Hit(term, kind, s, e))
            # um termo mais longo engole um mais curto na mesma posição ("motion design" ⊃ "motion")
            hits = [h for h in hits if not any(o is not h and o.start <= h.start and h.end <= o.end and (o.end - o.start) > (h.end - h.start) for o in hits)]
            if not hits:
                continue
            uniq = {}
            for h in sorted(hits, key=lambda h: (h.start, h.end, h.term)):
                uniq.setdefault((h.term, h.start), h)
            hits = list(uniq.values())
            strength = "strong" if any(h.kind == "strong" for h in hits) else "weak_only"
            matches.append(CategoryMatch(cat, strength, hits))
        ai_terms = sorted({t for t, p in self._ai if p.search(norm)})
        amb = sorted({t for t, p in self._amb if p.search(norm)})
        return TextResult(detect_language(norm), matches, ai_terms, sorted(set(excluded)), amb)


# ---------------------------------------------------------------------------
# Comparação com o comportamento anterior (curation.suggest_editorial_category)
# ---------------------------------------------------------------------------

LEGACY_TO_V2 = {
    "Ferramentas de IA": "demonstracao_ferramenta",
    "Automação": "automacao",
    "Ideias de Negócio": "marketing_vendas",
    "Design e Motion": "motion_design",
    "Engenharia Reversa Audiovisual": "edicao_audiovisual",
    "Marketing e Conteúdo": "marketing_vendas",
    "Criativo": "referencia_estetica",
    "Referências Visuais": "referencia_estetica",
}


# "Ferramentas de IA" no legado é um TEMA, não um formato: no v2 vira a faceta ai_topic_terms.
LEGACY_AS_FACET = {"Ferramentas de IA"}


def compare_with_legacy(cases: Sequence[dict], clf: Optional[TextClassifier] = None) -> List[dict]:
    """Para cada caso do golden, informa o rótulo legado, as categorias v2 e se há concordância.

    Concordância = a categoria legada mapeada está entre as categorias fortes v2, ou ambos não atribuem nada.
    Diferenças não são erros por definição: casos `known_defect` DEVEM divergir do legado.
    """
    clf = clf or TextClassifier()
    out = []
    for c in cases:
        text = " ".join([c.get("caption", "")] + list(c.get("hashtags", [])))
        res = clf.classify(text)
        legacy = c.get("suggested_category")
        mapped = LEGACY_TO_V2.get(legacy) if legacy else None
        strong = res.categories()
        if legacy in LEGACY_AS_FACET:
            agree = bool(res.ai_topic_terms) or mapped in strong
        else:
            agree = (mapped in strong) if mapped else (not strong)
        out.append({"caption": c.get("caption"), "legacy": legacy, "legacy_mapped": mapped, "v2_strong": strong,
                    "v2_weak_only": [m.category for m in res.matches if m.strength == "weak_only"],
                    "ai_topic_terms": res.ai_topic_terms, "agree": agree, "known_defect": bool(c.get("known_defect"))})
    return out

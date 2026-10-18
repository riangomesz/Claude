"""
Proposta: classificador multimodal multi-rótulo com evidência, proveniência e revisão humana.

Não substitui core/curation.py nem core/content_miner.py; roda ao lado deles (modo sombra).
Somente stdlib. Reaproveita proposals/classification/text_matcher.py.

Princípios:
- Não existe campo de confiança numérica. O apoio de cada categoria é ordinal e vem do TIPO
  da melhor evidência: verified_visual > measured > claimed_transcript > claimed_metadata > hypothesis.
- Texto sozinho nunca verifica uma categoria visual: no máximo "claimed_*".
- Observação de movimento exige base em trecho de vídeo; quadro estático não prova movimento.
- Métricas objetivas (cortes/min etc.) são anexadas como evidência, mas nunca disparam categoria
  sozinhas: os limiares ainda não foram calibrados contra curadoria humana.
- Toda categoria nasce com revisão humana pendente.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "classification"))
from text_matcher import RankedMatcher  # noqa: E402

SCHEMA_VERSION = "ii.multimodal_analysis.v1"

# Ordem canônica de saída (a saída não depende da ordem de definição das regras).
CATEGORIES: Tuple[str, ...] = (
    "conhecimento",
    "demonstracao_ferramenta",
    "tutorial",
    "motion_design",
    "edicao_audiovisual",
    "marketing_vendas",
    "conteudo_cinematografico",
    "referencia_estetica",
    "automacao_ia",
)

# Ordem do mais forte para o mais fraco.
SUPPORT_ORDER: Tuple[str, ...] = (
    "verified_visual", "measured", "claimed_transcript", "claimed_metadata", "hypothesis",
)

TEXT_RULES: Dict[str, List[str]] = {
    "conhecimento": ["voce sabia", "aprenda", "entenda", "explicando", "dica", "ensina"],
    "demonstracao_ferramenta": ["ferramenta", "plataforma", "aplicativo", "app", "olha so", "olha aqui"],
    "tutorial": ["passo a passo", "tutorial", "como fazer", "primeiro", "em seguida", "depois voce"],
    "motion_design": ["motion design", "motion", "keyframes", "after effects", "tipografia animada"],
    "edicao_audiovisual": ["edicao", "capcut", "premiere", "davinci", "transicao", "corte"],
    "marketing_vendas": ["desconto", "gratis", "oferta", "cupom", "link na bio", "assine", "compre", "vendas", "clientes"],
    "conteudo_cinematografico": ["cinematografico", "cinematografia", "color grading", "lente", "filmmaking"],
    "referencia_estetica": ["moodboard", "estetica", "referencia visual", "direcao de arte"],
    "automacao_ia": ["automacao", "automatizar", "n8n", "zapier", "workflow", "agente de ia", "agentes de ia", "chatgpt", "claude", "gemini"],
}

# tag de observação visual -> categoria. Tags `motion_*` exigem base em trecho de vídeo.
VISUAL_TAG_TO_CATEGORY: Dict[str, str] = {
    "ui_screen_visible": "demonstracao_ferramenta",
    "step_sequence_visible": "tutorial",
    "split_screen": "edicao_audiovisual",
    "layered_composition": "edicao_audiovisual",
    "b_roll_visible": "edicao_audiovisual",
    "burned_caption": "edicao_audiovisual",
    "motion_text_in_clip": "motion_design",
    "motion_transition_in_clip": "motion_design",
    "cinematic_look": "conteudo_cinematografico",
    "aesthetic_reference": "referencia_estetica",
    "sales_offer_on_screen": "marketing_vendas",
    "workflow_graph_on_screen": "automacao_ia",
    "informational_on_screen": "conhecimento",
}

EVIDENCE_BASES = ("static_frame", "frame_pair", "video_clip")
_QUOTE_MAX = 160


class SignalError(ValueError):
    pass


def validate_signals(signals: Dict[str, Any]) -> None:
    """Rejeita entradas que permitiriam afirmar mais do que a evidência sustenta."""
    for key in ("video_id", "duration_s"):
        if key not in signals:
            raise SignalError(f"campo obrigatório ausente: {key}")
    dur = float(signals["duration_s"])
    for seg in signals.get("transcript_segments", []):
        if not (0 <= seg["start"] <= seg["end"] <= dur + 0.5):
            raise SignalError(f"segmento fora da duração: {seg.get('id')}")
    for ob in signals.get("visual_observations", []):
        tag = ob.get("tag")
        if tag not in VISUAL_TAG_TO_CATEGORY:
            raise SignalError(f"tag visual desconhecida: {tag}")
        if ob.get("evidence_basis") not in EVIDENCE_BASES:
            raise SignalError(f"evidence_basis inválida em {ob.get('id')}")
        if not (0 <= float(ob["t_s"]) <= dur + 0.5):
            raise SignalError(f"t_s fora da duração: {ob.get('id')}")
        if tag.startswith("motion_") and ob["evidence_basis"] != "video_clip" and ob.get("kind") != "hypothesis":
            raise SignalError(f"{tag} exige evidence_basis=video_clip; quadro estático não prova movimento ({ob.get('id')})")
        if not ob.get("provenance"):
            raise SignalError(f"observação sem proveniência: {ob.get('id')}")


def _quote(text: str) -> str:
    t = " ".join(str(text or "").split())
    return t if len(t) <= _QUOTE_MAX else t[: _QUOTE_MAX - 1] + "…"


def _empty() -> Dict[str, List[Dict[str, Any]]]:
    return {c: [] for c in CATEGORIES}


def classify(signals: Dict[str, Any], rules: Optional[Dict[str, Sequence[str]]] = None) -> Dict[str, Any]:
    """Devolve um documento `ii.multimodal_analysis.v1` com categorias, evidências e revisão pendente."""
    validate_signals(signals)
    matcher = RankedMatcher(rules or TEXT_RULES)
    ev: Dict[str, List[Dict[str, Any]]] = _empty()

    def add(cat: str, item: Dict[str, Any]) -> None:
        item["id"] = f"{cat}:{len(ev[cat]) + 1}"
        ev[cat].append(item)

    caption = " ".join([str(signals.get("caption") or "")] + [str(h) for h in signals.get("hashtags", [])])
    for label, matched in matcher.rank(caption):
        add(label, {"modality": "text_metadata", "status": "claimed_metadata", "t_start_s": None, "t_end_s": None,
                    "ref": "caption+hashtags", "quote": _quote(caption), "matched": matched,
                    "provenance": {"source": "catalog.caption"}})

    for seg in signals.get("transcript_segments", []):
        for label, matched in matcher.rank(seg["text"]):
            add(label, {"modality": "transcript", "status": "claimed_transcript",
                        "t_start_s": seg["start"], "t_end_s": seg["end"], "ref": f"segmento:{seg['id']}",
                        "quote": _quote(seg["text"]), "matched": matched,
                        "provenance": {"source": "transcription", "untrusted_text": True}})

    for ob in signals.get("visual_observations", []):
        cat = VISUAL_TAG_TO_CATEGORY[ob["tag"]]
        hyp = ob.get("kind") == "hypothesis"
        add(cat, {"modality": "visual_review", "status": "hypothesis" if hyp else "verified_visual",
                  "t_start_s": float(ob["t_s"]), "t_end_s": float(ob["t_s"]), "ref": ob.get("pacote_id"),
                  "tag": ob["tag"], "evidence_basis": ob["evidence_basis"], "quote": _quote(ob.get("text", "")),
                  "provenance": ob["provenance"]})

    metrics = signals.get("av_metrics") or {}
    categories_out = []
    for cat in CATEGORIES:
        items = ev[cat]
        if not items:
            continue
        if cat == "edicao_audiovisual" and metrics:
            add(cat, {"modality": "av_metric", "status": "measured", "t_start_s": 0.0,
                      "t_end_s": float(signals["duration_s"]), "ref": "av_metrics", "metrics": dict(metrics),
                      "provenance": metrics.get("provenance", {"source": "av_metrics"})})
        statuses = {i["status"] for i in items}
        support = next(s for s in SUPPORT_ORDER if s in statuses)
        categories_out.append({
            "category": cat,
            "support": support,
            "evidence": items,
            "review": {"state": "pending", "reviewer": None, "decided_at": None, "note": None},
        })

    return {
        "schema_version": SCHEMA_VERSION,
        "video_id": signals["video_id"],
        "duration_s": signals["duration_s"],
        "status": "classified_pending_review",
        "categories": categories_out,
        "limitations": [
            "support é ordinal (tipo da melhor evidência), não probabilidade.",
            "Sem avaliação calibrada: nenhuma taxa de acerto é afirmada.",
            "Texto de transcrição é dado não confiável e nunca verifica categoria visual.",
        ],
    }


def validate_analysis(doc: Dict[str, Any]) -> List[str]:
    """Problemas de integridade de um documento de análise (lista vazia = íntegro)."""
    problems: List[str] = []
    if doc.get("schema_version") != SCHEMA_VERSION:
        problems.append("schema_version inesperado")
    if doc.get("status") in ("concluida", "completed"):
        visual = [e for c in doc.get("categories", []) for e in c["evidence"] if e["modality"] == "visual_review"]
        if not visual:
            problems.append("status concluída sem nenhuma observação visual")
    for c in doc.get("categories", []):
        if c["category"] not in CATEGORIES:
            problems.append(f"categoria desconhecida: {c['category']}")
        if any(k in c for k in ("confidence", "probability", "accuracy", "percent")):
            problems.append(f"{c['category']}: campo numérico de confiança não permitido")
        if not c.get("evidence"):
            problems.append(f"{c['category']}: sem evidência")
        if c.get("support") == "verified_visual" and not any(e["modality"] == "visual_review" and e["status"] == "verified_visual" for e in c["evidence"]):
            problems.append(f"{c['category']}: verified_visual sem evidência visual")
        for e in c.get("evidence", []):
            if not e.get("provenance"):
                problems.append(f"{c['category']}:{e.get('id')}: sem proveniência")
    return problems

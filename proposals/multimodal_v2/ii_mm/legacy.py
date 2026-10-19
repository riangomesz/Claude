"""Adaptadores do formato LEGADO do Projeto-MVP para o contrato v2 (Missão Suprema 02, Tarefa 05).

Regras comuns:
- Aceitam entradas parciais; o que não tem correspondência vai para `LegacyReport.unmapped`.
- Preservam identificadores originais (`reference.legacy_item_id`, `x_legacy`).
- Não reclassificam: rótulos legados entram como `inference` com a regra original na proveniência;
  decisões humanas legadas são listadas em `human_decisions` para importação explícita pela revisão.
- Reversíveis quando a estrutura permite: `to_legacy_fields(doc)` devolve os campos guardados.
- Nada aqui abre banco, arquivo de mídia ou rede: recebem dicts já lidos.

Formatos de origem (commit c6845a4):
- `instagram_items` (65 colunas no DDL real montado pela fixture legada) ou `InstagramItem` (pydantic).
- `VisualMacroAnalysis` (core/vision_client.py): status 'observado' | 'simulacao_teste' | 'erro_api'.
- Candidatos de `temporal_intelligence.transition_detector.detect_transitions_in_window`.
- Ficha `ii.intelligence.card.v1/v2` (ii_coverage/ii_coverage.js e fase5.js).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from . import adapters as A
from .contract import make_evidence
from .normalize import Normalizer

# Colunas de instagram_items e o destino no contrato v2.
INSTAGRAM_ITEM_MAPPING: Dict[str, str] = {
    "id": "reference.legacy_item_id",
    "canonical_shortcode": "video.video_id",
    "url": "reference.origin_url",
    "origin_platform": "reference.platform",
    "owner_username": "reference.author_handle (metadata_claim)",
    "caption": "evidence metadata_claim (caption)",
    "hashtags_json": "evidence metadata_claim (hashtags)",
    "audio_transcript_segments_json": "transcript + evidence transcript_claim",
    "audio_transcript": "evidence transcript_claim sem segmentação (só se não houver segmentos)",
    "audio_transcript_source": "provenance.source da transcrição",
    "audio_transcript_language": "x_legacy",
    "curation_category": "evidence inference (rótulo legado) + curation_rule",
    "curation_rule": "provenance.rule do rótulo legado",
    "editorial_category": "evidence inference (rótulo legado) ou decisão humana listada",
    "editorial_category_source": "decide se editorial_category é decisão humana",
    "media_sha256": "video.content_sha256 (deduplicação por conteúdo)",
    "media_duration_sec": "video.duration_s",
    "media_width": "video.width",
    "media_height": "video.height",
    "media_fps": "video.fps",
}
# Campos de curadoria/estado preservados de forma reversível, sem virar evidência.
LEGACY_PRESERVED = (
    "fbid", "post_type", "owner_name", "saved_timestamp", "saved_date", "source_file", "zip_internal_path",
    "timestamp_meaning", "has_media_file", "local_media_path", "status", "review_status", "lifecycle_stage",
    "linked_analysis_id", "linked_analysis_path", "thematic_relevance", "visual_relevance", "marked_for_deep_analysis",
    "is_archived", "curator_note", "triage_decision", "triage_timestamp", "quality_rating", "media_status",
    "capture_session_id", "captured_at", "provenance_occurrences_json", "editorial_tags_json", "editorial_updated_at",
    "curation_updated_at", "audio_transcript_status", "audio_transcript_updated_at", "audio_transcript_language",
    "created_at", "updated_at",
    "media_source", "media_error", "media_error_kind", "media_attempts", "media_last_attempt_at", "media_acquired_at",
    "media_vcodec", "media_acodec", "media_size_bytes", "media_thumbnail_path", "media_provenance_json",
)
HUMAN_EDITORIAL_SOURCES = {"manual", "manual_do_usuario", "usuario", "user", "human", "curador"}
# Revalidado na Missão Suprema 03 contra c6845a4: editorial_category só é GRAVADA por fluxo humano
# (review_server: payload.get("source", "human"); painel: source 'manual'). A sugestão automática é calculada
# na hora e não é gravada. Por isso só origens explicitamente automáticas viram rótulo de classificador;
# origem nula ou desconhecida é tratada como decisão humana (sem reclassificar).
AUTOMATIC_EDITORIAL_SOURCES = {"sugestao_automatica", "suggestion", "suggested", "auto", "automatic", "classifier", "ii_mm"}
PLATFORM_MAP = {"instagram": "instagram", "youtube": "youtube", "tiktok": "tiktok", "x": "x", "twitter": "x", "vimeo": "vimeo"}


@dataclass
class LegacyReport:
    source: str
    mapped: List[str] = field(default_factory=list)
    preserved: List[str] = field(default_factory=list)
    unmapped: List[str] = field(default_factory=list)
    human_decisions: List[Dict[str, Any]] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    blocking: Optional[str] = None


def _json_list(raw: Any, report: LegacyReport, name: str) -> List[Any]:
    if raw in (None, ""):
        return []
    if isinstance(raw, list):
        return raw
    try:
        v = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        report.warnings.append(f"{name}: JSON ilegível, ignorado")
        return []
    if not isinstance(v, list):
        report.warnings.append(f"{name}: esperado lista JSON")
        return []
    return v


def from_instagram_item(row: Dict[str, Any], duration_s: Optional[float] = None,
                        content_sha256: Optional[str] = None) -> tuple:
    """Linha de `instagram_items` (ou InstagramItem.model_dump()) → (Normalizer | None, LegacyReport).

    `duration_s` vem da mídia (ex.: media_duration_sec / ffprobe). Sem ela o documento não pode ser
    montado (o contrato exige duração) e o relatório sai com `blocking`.
    """
    rep = LegacyReport("instagram_items")
    row = dict(row)
    if "hashtags" in row and "hashtags_json" not in row:  # InstagramItem usa lista
        row["hashtags_json"] = row.pop("hashtags")
    item_id = row.get("id")
    shortcode = row.get("canonical_shortcode") or item_id
    if not shortcode:
        rep.blocking = "sem id nem canonical_shortcode"
        return None, rep
    duration_s = duration_s if duration_s is not None else row.get("media_duration_sec")
    try:
        duration_s = float(duration_s) if duration_s is not None else None
    except (TypeError, ValueError):
        duration_s = None
    if not duration_s or duration_s <= 0:
        rep.blocking = "duração da mídia ausente: informe duration_s (ffprobe) para montar o documento"
        return None, rep
    raw_platform = (row.get("origin_platform") or "instagram").lower()
    platform = PLATFORM_MAP.get(raw_platform, "other")
    if platform == "other":
        rep.warnings.append(f"origin_platform '{raw_platform}' sem correspondência; usado 'other'")
    media_sha = row.get("media_sha256")
    if content_sha256 is None and isinstance(media_sha, str) and len(media_sha) == 64 and all(c in "0123456789abcdef" for c in media_sha):
        content_sha256 = media_sha
    elif media_sha and content_sha256 is None:
        rep.warnings.append("media_sha256 inválido; documento sem hash de conteúdo")
    n = Normalizer(f"ig_{shortcode}", platform, shortcode, duration_s, content_sha256=content_sha256,
                   origin_url=row.get("url"), author_handle=row.get("owner_username") or None)
    n.doc["reference"]["legacy_item_id"] = item_id
    for col, key in (("media_width", "width"), ("media_height", "height"), ("media_fps", "fps")):
        if isinstance(row.get(col), (int, float)) and row[col] > 0:
            n.doc["video"][key] = row[col]
    rep.mapped += [k for k in ("id", "canonical_shortcode", "url", "origin_platform", "owner_username", "media_sha256",
                               "media_duration_sec", "media_width", "media_height", "media_fps") if row.get(k) is not None]

    hashtags = [str(h) for h in _json_list(row.get("hashtags_json"), rep, "hashtags_json")]
    if row.get("caption") or hashtags:
        n.add_metadata(row.get("caption"), hashtags, source="instagram_items")
        rep.mapped += [k for k in ("caption", "hashtags_json") if row.get(k)]

    segs = _json_list(row.get("audio_transcript_segments_json"), rep, "audio_transcript_segments_json")
    tsource = row.get("audio_transcript_source") or "transcription"
    if segs:
        res = A.transcript_from_segments(segs, source=tsource)
        n.add_transcript(res, extractor=tsource)
        rep.mapped += ["audio_transcript_segments_json", "audio_transcript_source"]
        rep.warnings += [f"segmentos: {e}" for e in res.errors]
    elif (row.get("audio_transcript") or "").strip():
        # texto sem tempos: vale para o vídeo inteiro e fica marcado como não segmentado
        res = A.transcript_from_segments([{"id": "untimed", "start": 0.0, "end": duration_s, "text": row["audio_transcript"]}], source=tsource)
        for eid in n.add_transcript(res, extractor=tsource):
            n._ev[eid]["provenance"]["untimed"] = True
        rep.mapped.append("audio_transcript")
        rep.warnings.append("transcrição sem segmentos: registrada para o vídeo inteiro (untimed)")

    if row.get("curation_category"):
        n.add_legacy_label(row["curation_category"], row.get("curation_rule") or "sem regra", source="core.curation.curation_category")
        rep.mapped += [k for k in ("curation_category", "curation_rule") if row.get(k)]
    if row.get("editorial_category"):
        src = (row.get("editorial_category_source") or "").strip().lower()
        if src in AUTOMATIC_EDITORIAL_SOURCES:
            n.add_legacy_label(row["editorial_category"], f"editorial_category ({src})", source="core.curation.editorial_category")
        else:
            note = ("decisão humana legada: importar via ReviewService, não como evidência" if src in HUMAN_EDITORIAL_SOURCES else
                    f"origem {'não registrada' if not src else repr(src) + ' desconhecida'}: tratada como decisão humana, "
                    "pois o Projeto-MVP só grava editorial_category por fluxo humano")
            rep.human_decisions.append({"field": "editorial_category", "value": row["editorial_category"], "source": src or None, "note": note})
        rep.mapped += [k for k in ("editorial_category", "editorial_category_source") if row.get(k)]
    if row.get("triage_decision"):
        rep.human_decisions.append({"field": "triage_decision", "value": row["triage_decision"], "source": "triagem",
                                    "note": "decisão de manter/descartar; não é categoria de conteúdo"})

    legacy = {k: row[k] for k in LEGACY_PRESERVED if k in row and row[k] is not None}
    rep.preserved = sorted(legacy)
    n.doc["x_legacy"] = {"source": "instagram_items", "item_id": item_id, "fields": legacy}
    known = set(INSTAGRAM_ITEM_MAPPING) | set(LEGACY_PRESERVED)
    rep.unmapped = sorted(k for k in row if k not in known and row[k] not in (None, ""))
    rep.mapped = sorted(set(rep.mapped))
    return n, rep


def to_legacy_fields(doc: Dict[str, Any]) -> Dict[str, Any]:
    """Reverso parcial: campos legados preservados + identificadores originais."""
    x = doc.get("x_legacy") or {}
    out = dict(x.get("fields", {}))
    out["id"] = doc["reference"].get("legacy_item_id", x.get("item_id"))
    out["canonical_shortcode"] = doc["video"]["video_id"]
    out["url"] = doc["reference"].get("origin_url")
    out["owner_username"] = doc["reference"].get("author_handle")
    return out


def from_vision_macro(n: Normalizer, analysis: Dict[str, Any], analysis_ref: str) -> LegacyReport:
    """`VisualMacroAnalysis` do vision_client → evidências. Simulação ou erro NUNCA viram evidência.

    `verifiable_observations` são afirmações do modelo sobre o conjunto de frames, sem frame nem tag:
    entram como `unverified` até uma revisão ligá-las a frames. `inferred_hypotheses` → `inference`.
    """
    rep = LegacyReport("vision_client.VisualMacroAnalysis")
    status = analysis.get("status", "observado")
    if status != "observado":
        rep.blocking = f"status '{status}': simulação ou erro de API não pode virar evidência"
        return rep
    for obs in analysis.get("verifiable_observations") or []:
        n.add_unverified(f"[modelo, não auditado] {obs}", source=f"vision_client:{analysis_ref}")
    for hyp in analysis.get("inferred_hypotheses") or []:
        n._add(make_evidence(
            n.video_key, status="inference", source_type="derived", claim=str(hyp), tag="model_hypothesis",
            provenance={"source": f"vision_client:{analysis_ref}"}))
    for lim in analysis.get("limitations_or_ambiguities") or []:
        n.doc["pending"].append({"pending_id": f"vision:{len(n.doc['pending']) + 1}", "description": f"limitação declarada: {lim}", "blocking": False})
    rep.mapped = [k for k in ("verifiable_observations", "inferred_hypotheses", "limitations_or_ambiguities") if analysis.get(k)]
    rep.preserved = [k for k in ("art_direction", "dominant_palette", "lighting_and_atmosphere", "pacing_and_rhythm",
                                 "style_tags", "audio_visual_coherence", "summary_text") if analysis.get(k)]
    n.doc.setdefault("x_legacy_vision", {})[analysis_ref] = {k: analysis[k] for k in rep.preserved}
    rep.warnings.append("observações do modelo entram como 'unverified': revisar e ligar a frames antes de usar como observed_visual")
    return rep


def from_transition_candidates(n: Normalizer, candidates: List[Dict[str, Any]], source: str = "temporal_intelligence") -> LegacyReport:
    """Candidatos por limiar (detect_transitions_in_window) → medição + hipótese do tipo de evento."""
    rep = LegacyReport("temporal_intelligence.transition_detector")
    for c in candidates:
        t = c.get("timestamp_evento_s")
        if not isinstance(t, (int, float)) or t < 0 or t > n.duration + 0.5:
            rep.warnings.append(f"candidato sem timestamp válido: {str(c)[:80]}")
            continue
        n._add(make_evidence(n.video_key, status="measured_signal", source_type="visual_metric",
                             claim=f"descontinuidade acima do limiar em {c.get('janela', '?')}", t_start_s=float(t),
                             tag="frame_difference_metric", provenance={"source": source, "thresholds": c.get("limiares_utilizados")}))
        if c.get("tipo_candidato"):
            n._add(make_evidence(n.video_key, status="inference", source_type="derived",
                                 claim=f"tipo sugerido pelo limiar: {c['tipo_candidato']} ({c.get('classificacao_evento')})",
                                 t_start_s=float(t), tag="threshold_event_type",
                                 provenance={"source": source, "nivel_evidencia_legado": c.get("nivel_evidencia")}))
    rep.mapped = ["timestamp_evento_s", "tipo_candidato", "classificacao_evento", "nivel_evidencia"]
    rep.warnings.append("limiares do temporal_intelligence foram calibrados num único vídeo: tipos de evento ficam como hipótese")
    return rep


# tipos de observação da Fase 5 → tags do vocabulário (tipos desconhecidos ficam sem tag e são reportados)
FICHA_TIPO_TO_TAG = {"interface": "ui_screen_visible", "legenda": "burned_caption", "texto_em_tela": "typography_styled",
                     "nome_ferramenta": "tool_name_visible", "logotipo": "logo_visible", "tela_dividida": "split_screen",
                     "sobreposicao": "overlay_layer", "oferta": "sales_offer_on_screen", "b_roll": "b_roll_visible"}


def from_intelligence_card(n: Normalizer, card: Dict[str, Any]) -> LegacyReport:
    """Ficha ii.intelligence.card.v1/v2 → evidências preservando a separação feita pelo ii_coverage."""
    rep = LegacyReport(card.get("schema_version", "ficha_desconhecida"))
    if card.get("schema_version") not in ("ii.intelligence.card.v1", "ii.intelligence.card.v2"):
        rep.blocking = f"schema não suportado: {card.get('schema_version')}"
        return rep
    sep = card.get("separacao_de_evidencias") or {}
    segs = ((sep.get("conteudo_falado") or {}).get("segmentos")) or []
    if segs:
        n.add_transcript(A.transcript_from_segments({"segmentos": segs}, source="ficha:conteudo_falado"))
        rep.mapped.append("separacao_de_evidencias.conteudo_falado")
    vis = ((sep.get("elementos_visiveis") or {}).get("fase5")) or []
    frames = [{"pacote_id": o["frame_id"], "t_s": o["timestamp_s"], "sha256": o["sha256_frame"], "file": o.get("arquivo")}
              for o in vis if o.get("frame_id") and isinstance(o.get("timestamp_s"), (int, float)) and o.get("sha256_frame")]
    if frames:
        n.add_frames(A.frames_from_manifest({"frames": frames}))
    for o in vis:
        tag = FICHA_TIPO_TO_TAG.get(o.get("tipo"))
        if tag is None:
            rep.unmapped.append(f"tipo de observação sem tag: {o.get('tipo')}")
        text = " ".join(x for x in (o.get("descricao"), f"texto literal: {o['texto_literal']}" if o.get("texto_literal") else None) if x)
        if not text or o.get("frame_id") not in n._frames:
            rep.warnings.append(f"observação {o.get('id')} sem texto ou frame verificável; ignorada")
            continue
        f = n._frames[o["frame_id"]]
        n._add(make_evidence(n.video_key, status="observed_visual", source_type="human_observation", claim=text,
                             t_start_s=f["t_s"], ref=o["frame_id"], tag=tag, basis="static_frame",
                             provenance={"source": "ficha:elementos_visiveis.fase5", "observation_id": o.get("id"),
                                         "artifact_sha256": f["sha256"], "status_verificacao": o.get("status_verificacao")}))
    if vis:
        rep.mapped.append("separacao_de_evidencias.elementos_visiveis.fase5")
    if ((sep.get("movimento_confirmado") or {}).get("itens")):
        rep.unmapped.append("movimento_confirmado.itens não vazio: exige trecho de vídeo (video_clip) para importar")
    hyps = (sep.get("hipoteses") or {}).get("fase5") or []
    for h in hyps:
        text = h if isinstance(h, str) else (h.get("descricao") or h.get("texto") or json.dumps(h, ensure_ascii=False))
        n._add(make_evidence(n.video_key, status="inference", source_type="derived", claim=str(text), tag="card_hypothesis",
                             provenance={"source": "ficha:hipoteses.fase5"}))
    ext = sep.get("conhecimento_externo") or {}
    if isinstance(ext, dict) and ext.get("utilizado"):
        for item in ext.get("itens") or []:
            n.add_external_knowledge(str(item), source="ficha:conhecimento_externo")
    for al in ((card.get("alegacoes_vs_evidencias") or {}).get("itens")) or []:
        claim = al.get("alegacao") or al.get("descricao") or json.dumps(al, ensure_ascii=False)
        n.add_unverified(f"alegação do criador: {claim}", source="ficha:alegacoes_vs_evidencias")
    for c in card.get("categorias") or []:
        name = c.get("categoria") if isinstance(c, dict) else str(c)
        n.add_legacy_label(name, f"ficha ({(c or {}).get('status') if isinstance(c, dict) else 'sem status'})", source="ficha:categorias")
    for p in card.get("evidencias_pendentes") or []:
        n.doc["pending"].append({"pending_id": f"ficha:{p.get('id')}", "description": p.get("descricao", ""),
                                 "blocking": False, "interval_s": p.get("intervalo_s")})
    rep.mapped += [k for k in ("alegacoes_vs_evidencias", "categorias", "evidencias_pendentes") if card.get(k)]
    rep.preserved = [k for k in ("assunto_principal", "ferramenta_mencionada", "estrutura_narrativa", "possibilidades_de_reproducao",
                                 "cobertura_visual", "notas_de_curadoria") if card.get(k)]
    n.doc["x_legacy_card"] = {k: card[k] for k in rep.preserved}
    return rep

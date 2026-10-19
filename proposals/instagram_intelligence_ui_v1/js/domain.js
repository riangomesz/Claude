// Vocabulário do domínio: enums do backend (ii_be / ii_mm) → rótulos de interface.
export const CATEGORIES = [
  ["conhecimento", "Conhecimento", "CON"],
  ["tutorial", "Tutorial", "TUT"],
  ["demonstracao_ferramenta", "Demonstração de ferramenta", "FER"],
  ["automacao", "Automação", "AUT"],
  ["motion_design", "Motion design", "MOT"],
  ["edicao_audiovisual", "Edição audiovisual", "EDI"],
  ["marketing_vendas", "Marketing e vendas", "MKT"],
  ["cinematografia", "Cinematografia", "CIN"],
  ["referencia_estetica", "Referência estética", "EST"],
];
const CAT = Object.fromEntries(CATEGORIES.map(([k, l, s], i) => [k, { label: l, short: s, color: `var(--chart-${i + 1})` }]));

export const RATINGS = [["excelente", "Excelente", 4], ["muito_bom", "Muito bom", 3], ["bom", "Bom", 2], ["ruim", "Ruim", 1]];
const RAT = Object.fromEntries(RATINGS.map(([k, l, n]) => [k, { label: l, stars: n }]));

// Decisão humana de triagem. "aguardando" = nenhuma decisão registrada.
export const CURATION = [["aguardando", "Aguardando curadoria", "pending"], ["manter", "Manter", "success"], ["revisar", "Revisar", "warning"], ["descartar", "Descartar", "danger"]];
const CUR = Object.fromEntries(CURATION.map(([k, l, kind]) => [k, { label: l, kind }]));

export const PROCESSING = [["concluido", "Concluído", "Pronto", "success"], ["processando", "Em processamento", "Processando", "info"],
  ["na_fila", "Na fila", "Na fila", "pending"], ["falhou", "Falhou", "Falhou", "danger"], ["sem_midia", "Sem mídia", "Sem mídia", "neutral"]];
const PROC = Object.fromEntries(PROCESSING.map(([k, l, s, kind]) => [k, { label: l, short: s, kind }]));

export const PLATFORMS = [["instagram", "Instagram", "camera"], ["tiktok", "TikTok", "music"], ["youtube", "YouTube", "video"]];
const PLAT = Object.fromEntries(PLATFORMS.map(([k, l, ic]) => [k, { label: l, icon: ic }]));

// Etapas reais do agendador (ii_be.scheduler) agrupadas em 5 fases visíveis.
export const STAGE_GROUPS = [
  ["aquisicao", "Aquisição", ["acquire", "probe"]],
  ["audio", "Áudio e fala", ["audio", "transcribe"]],
  ["visual", "Visual", ["scenes", "frames", "metrics", "visual_analysis"]],
  ["evidencias", "Evidências", ["assemble"]],
  ["classificacao", "Classificação", ["classify", "index"]],
];

// Status de evidência do backend (ii_be.search.EVIDENCE_STATUSES), do mais forte ao mais fraco.
export const EVIDENCE = [
  ["observed_visual", "Observado no vídeo", "success", "eye"],
  ["measured_signal", "Sinal medido", "success", "analysis"],
  ["transcript_claim", "Dito na fala", "info", "mic"],
  ["metadata_claim", "Dito na legenda/metadados", "info", "text"],
  ["inference", "Inferência", "warning", "sparkle"],
  ["unverified", "Não verificado", "neutral", "alert"],
];
const EVI = Object.fromEntries(EVIDENCE.map(([k, l, kind, ic]) => [k, { label: l, kind, icon: ic }]));

export const SUPPORT = { supported_visual: "Sustentado por imagem", supported_measured: "Sustentado por medição", mentioned_speech: "Mencionado na fala",
  suggested_metadata: "Sugerido por metadados", hypothesis: "Hipótese", insufficient: "Insuficiente" };

const ACT = { ingest: ["outline", "Ingestão", "inbox"], stage: ["info", "Pipeline", "layers"], analysis: ["success", "Análise", "sparkle"],
  curation: ["pending", "Curadoria", "curation"], failure: ["danger", "Falha", "alert"] };

export const labels = {
  category: (k) => CAT[k]?.label || "Sem categoria",
  categoryShort: (k) => CAT[k]?.short || "—",
  categoryColor: (k) => CAT[k]?.color || "var(--chart-track)",
  rating: (k) => RAT[k]?.label || "Sem nota",
  stars: (k) => RAT[k]?.stars || 0,
  curation: (k) => CUR[k]?.label || CUR.aguardando.label,
  curationKind: (k) => CUR[k]?.kind || "pending",
  processing: (k) => PROC[k]?.label || k,
  processingShort: (k) => PROC[k]?.short || k,
  processingKind: (k) => PROC[k]?.kind || "neutral",
  platform: (k) => PLAT[k]?.label || k,
  platformIcon: (k) => PLAT[k]?.icon || "video",
  evidence: (k) => EVI[k] || { label: k, kind: "neutral", icon: "alert" },
  support: (k) => SUPPORT[k] || k,
  activityKind: (k) => ACT[k] || ["outline", k],
  activityIcon: (k) => ACT[k]?.[2] || "activity",
};

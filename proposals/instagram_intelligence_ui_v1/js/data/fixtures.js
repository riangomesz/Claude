// DADOS FICTÍCIOS DE DEMONSTRAÇÃO. Nenhum item abaixo existe no catálogo real.
// Autores, links e números foram inventados para exercitar a interface; a UI sempre mostra "Modo demonstração" ao usá-los.
export const DEMO_NOTICE = "Dados fictícios de demonstração — nada aqui vem do catálogo real.";

const ALL_DONE = { acquire: "done", probe: "done", audio: "done", transcribe: "done", scenes: "done", frames: "done", metrics: "done",
  visual_analysis: "done", assemble: "done", classify: "done", index: "done" };
const upTo = (stage, current = "running") => {
  const order = Object.keys(ALL_DONE);
  const i = order.indexOf(stage);
  return Object.fromEntries(order.map((s, j) => [s, j < i ? "done" : j === i ? current : "pending"]));
};

function ref(n, o) {
  return {
    id: `demo-${String(n).padStart(2, "0")}`,
    platform: "instagram",
    url: `https://www.instagram.com/reel/DEMO${String(n).padStart(4, "0")}/`,
    hashtags: [],
    rating: null,
    curation: "aguardando",
    analysis: null,
    evidence: [],
    knowledge: [],
    categories: [],
    ...o,
    thumb: `radial-gradient(120% 70% at 20% 10%, rgba(255,255,255,.35), transparent 60%), linear-gradient(165deg, var(--chart-${(n % 9) + 1}) 0%, var(--thumb-b) 62%, var(--thumb-c) 100%)`,
  };
}

const done = (extra = {}) => ({ state: "concluido", stage: "index", progress: 1, stages: ALL_DONE, ...extra });

export const REFERENCES = [
  ref(1, { title: "Fluxo de legendas automáticas com revisão humana no meio", author: "@estudio.exemplo", duration_s: 74, captured_at: "2026-10-18T14:20:00Z",
    caption: "Mostro o fluxo completo: transcrição, revisão e exportação de legendas.", hashtags: ["#legendas", "#automacao"], category: "automacao",
    categories: [{ category: "automacao", support: "supported_visual", review_state: "pending" }, { category: "tutorial", support: "mentioned_speech", review_state: "pending" }],
    rating: "excelente", curation: "manter", processing: done(),
    analysis: { summary: "Tutorial em tela mostrando um fluxo de transcrição seguido de revisão manual antes de exportar legendas.", analyzed_at: "2026-10-18T14:31:00Z", classifier_version: "demo",
      facets: [["Gancho", "Pergunta direta nos 2 primeiros segundos"], ["Formato", "Gravação de tela com narração"], ["Ritmo", "Cortes a cada 3–4 s"], ["Texto na tela", "Títulos de etapa"], ["Áudio", "Voz + trilha baixa"]] },
    evidence: [
      { id: "e1", status: "observed_visual", source_type: "visual", claim: "Tela do editor de legendas visível com linha do tempo.", t_start_s: 9 },
      { id: "e2", status: "transcript_claim", source_type: "transcript", claim: "\"Primeiro eu deixo a transcrição rodar sozinha.\"", t_start_s: 12 },
      { id: "e3", status: "measured_signal", source_type: "metrics", claim: "Média de 1 corte a cada 3,6 s.", t_start_s: null },
      { id: "e4", status: "inference", source_type: "classifier", claim: "Provável público: editores iniciantes.", t_start_s: null },
    ],
    knowledge: [{ kind: "processo", name: "Transcrever → revisar → exportar", demonstrated: true }, { kind: "ferramenta", name: "Editor de legendas (genérico)", demonstrated: true }] }),
  ref(2, { title: "Transição de match cut com objeto em movimento", author: "@corte.seco", duration_s: 31, captured_at: "2026-10-18T10:05:00Z", category: "edicao_audiovisual",
    categories: [{ category: "edicao_audiovisual", support: "supported_visual", review_state: "pending" }],
    processing: done(), rating: "muito_bom",
    analysis: { summary: "Demonstração curta de match cut usando um objeto que cruza o quadro.", analyzed_at: "2026-10-18T10:12:00Z", classifier_version: "demo",
      facets: [["Gancho", "Resultado final primeiro"], ["Formato", "Antes/depois"], ["Ritmo", "Rápido"]] },
    evidence: [{ id: "e1", status: "observed_visual", source_type: "visual", claim: "Objeto cruza o quadro e o corte acontece no meio do movimento.", t_start_s: 4 },
      { id: "e2", status: "unverified", source_type: "metadata", claim: "Legenda cita um plugin pago, não mostrado no vídeo.", t_start_s: null }],
    knowledge: [{ kind: "tecnica", name: "Match cut por movimento", demonstrated: true }, { kind: "ferramenta", name: "Plugin citado na legenda", demonstrated: false }] }),
  ref(3, { title: "Paleta de cor para vídeos de produto em fundo claro", author: "@luz.difusa", platform: "tiktok", duration_s: 46, captured_at: "2026-10-17T19:40:00Z",
    category: "cinematografia", categories: [{ category: "cinematografia", support: "supported_measured", review_state: "pending" }], processing: done(),
    analysis: { summary: "Explica escolha de paleta e iluminação difusa para produto.", analyzed_at: "2026-10-17T19:52:00Z", classifier_version: "demo",
      facets: [["Gancho", "Comparação lado a lado"], ["Iluminação", "Difusa, alta-chave"]] },
    evidence: [{ id: "e1", status: "measured_signal", source_type: "metrics", claim: "Luminância média alta em 92% dos quadros.", t_start_s: null },
      { id: "e2", status: "transcript_claim", source_type: "transcript", claim: "\"Uso duas fontes rebatidas no teto.\"", t_start_s: 18 }] }),
  ref(4, { title: "Roteiro de 3 atos para anúncio de 15 segundos", author: "@copy.curta", duration_s: 15, captured_at: "2026-10-17T16:00:00Z", category: "marketing_vendas",
    categories: [{ category: "marketing_vendas", support: "mentioned_speech", review_state: "pending" }], processing: done(), rating: "bom", curation: "revisar",
    analysis: { summary: "Estrutura de anúncio curto: problema, demonstração, chamada.", analyzed_at: "2026-10-17T16:09:00Z", classifier_version: "demo", facets: [["Formato", "Fala para câmera"]] },
    evidence: [{ id: "e1", status: "transcript_claim", source_type: "transcript", claim: "\"Todo anúncio curto precisa de três atos.\"", t_start_s: 2 },
      { id: "e2", status: "inference", source_type: "classifier", claim: "Possível oferta comercial no fim.", t_start_s: 13 }] }),
  ref(5, { title: "Animação de texto cinético sincronizada com a batida", author: "@quadro.a.quadro", duration_s: 22, captured_at: "2026-10-17T11:30:00Z", category: "motion_design",
    categories: [{ category: "motion_design", support: "supported_visual", review_state: "pending" }], processing: done(), rating: "excelente",
    analysis: { summary: "Texto cinético com cortes sincronizados ao áudio.", analyzed_at: "2026-10-17T11:41:00Z", classifier_version: "demo", facets: [["Ritmo", "Sincronizado à batida"], ["Texto na tela", "Tipografia animada"]] },
    evidence: [{ id: "e1", status: "observed_visual", source_type: "visual", claim: "Palavras surgem a cada batida.", t_start_s: 1 }, { id: "e2", status: "measured_signal", source_type: "audio", claim: "Picos de áudio alinhados aos cortes.", t_start_s: null }],
    knowledge: [{ kind: "tecnica", name: "Sincronizar texto ao áudio", demonstrated: true }] }),
  ref(6, { title: "Montando uma automação que salva links em planilha", author: "@sem.codigo", platform: "youtube", duration_s: 58, captured_at: "2026-10-16T21:10:00Z",
    category: "demonstracao_ferramenta", categories: [{ category: "demonstracao_ferramenta", support: "supported_visual", review_state: "pending" }, { category: "automacao", support: "hypothesis", review_state: "pending" }],
    processing: done(),
    analysis: { summary: "Demonstração de ferramenta de automação sem código salvando links.", analyzed_at: "2026-10-16T21:22:00Z", classifier_version: "demo", facets: [["Formato", "Gravação de tela"]] },
    evidence: [{ id: "e1", status: "observed_visual", source_type: "visual", claim: "Editor de fluxos com três nós conectados.", t_start_s: 20 }],
    knowledge: [{ kind: "processo", name: "Capturar link → planilha", demonstrated: true }, { kind: "ferramenta", name: "Ferramenta de automação sem código", demonstrated: true }] }),
  ref(7, { title: "Iluminação de três pontos com uma única lâmpada", author: "@luz.difusa", duration_s: 39, captured_at: "2026-10-16T13:00:00Z", category: "cinematografia",
    categories: [{ category: "cinematografia", support: "mentioned_speech", review_state: "pending" }], processing: done(), curation: "descartar", rating: "ruim",
    analysis: { summary: "Promete técnica que não é demonstrada no vídeo.", analyzed_at: "2026-10-16T13:08:00Z", classifier_version: "demo", facets: [] },
    evidence: [{ id: "e1", status: "transcript_claim", source_type: "transcript", claim: "\"Com uma lâmpada só dá para fazer três pontos.\"", t_start_s: 3 },
      { id: "e2", status: "unverified", source_type: "classifier", claim: "Nenhum quadro mostra o esquema de luz.", t_start_s: null }] }),
  ref(8, { title: "Referência visual: interiores em tons terrosos", author: "@moodboard.vivo", duration_s: 12, captured_at: "2026-10-15T18:25:00Z", category: "referencia_estetica",
    categories: [{ category: "referencia_estetica", support: "supported_visual", review_state: "pending" }], processing: done(), rating: "muito_bom", curation: "manter",
    analysis: { summary: "Sequência de planos estáticos de interiores com paleta terrosa.", analyzed_at: "2026-10-15T18:31:00Z", classifier_version: "demo", facets: [["Paleta", "Terrosa"], ["Movimento", "Planos estáticos"]] },
    evidence: [{ id: "e1", status: "observed_visual", source_type: "visual", claim: "Planos de interior com madeira e cerâmica.", t_start_s: 2 }] }),
  ref(9, { title: "Como eu organizo referências antes de editar", author: "@corte.seco", duration_s: 63, captured_at: "2026-10-19T08:10:00Z", category: null,
    processing: { state: "processando", stage: "transcribe", progress: 0.38, stages: upTo("transcribe") } }),
  ref(10, { title: "Teste de lente anamórfica no celular", author: "@lente.livre", platform: "tiktok", duration_s: 27, captured_at: "2026-10-19T07:45:00Z", category: null,
    processing: { state: "processando", stage: "visual_analysis", progress: 0.72, stages: upTo("visual_analysis") } }),
  ref(11, { title: "Checklist de exportação para Reels", author: "@estudio.exemplo", duration_s: 41, captured_at: "2026-10-19T07:20:00Z", category: null,
    processing: { state: "na_fila", stage: "acquire", progress: 0, stages: upTo("acquire", "pending") } }),
  ref(12, { title: "Tutorial de máscara animada (download falhou)", author: "@quadro.a.quadro", duration_s: null, captured_at: "2026-10-18T22:00:00Z", category: null,
    processing: { state: "falhou", stage: "acquire", progress: 0, stages: upTo("acquire", "failed"), error: "Mídia indisponível na origem (HTTP 404). Nenhuma nova tentativa automática." } }),
  ref(13, { title: "Narrativa em plano-sequência no metrô", author: "@lente.livre", duration_s: 52, captured_at: "2026-10-18T20:30:00Z", category: null,
    processing: { state: "falhou", stage: "transcribe", progress: 0.3, stages: upTo("transcribe", "failed"), error: "Transcrição excedeu o tempo limite (lease vencido duas vezes)." } }),
  ref(14, { title: "Gancho visual com zoom digital nos primeiros 2 s", author: "@copy.curta", duration_s: 18, captured_at: "2026-10-15T09:00:00Z", category: "edicao_audiovisual",
    categories: [{ category: "edicao_audiovisual", support: "supported_measured", review_state: "pending" }], processing: done(),
    analysis: { summary: "Zoom digital rápido como gancho de abertura.", analyzed_at: "2026-10-15T09:06:00Z", classifier_version: "demo", facets: [["Gancho", "Zoom digital"]] },
    evidence: [{ id: "e1", status: "measured_signal", source_type: "metrics", claim: "Escala do quadro sobe 40% em 0,8 s.", t_start_s: 0 }] }),
];

export const ACTIVITY = [
  { at: "2026-10-19T08:12:00Z", kind: "stage", ref_id: "demo-09", text: "Transcrição iniciada · Como eu organizo referências…" },
  { at: "2026-10-19T07:58:00Z", kind: "stage", ref_id: "demo-10", text: "Análise visual em andamento · Teste de lente anamórfica…" },
  { at: "2026-10-19T07:21:00Z", kind: "ingest", ref_id: "demo-11", text: "Nova referência catalogada · Checklist de exportação…" },
  { at: "2026-10-18T22:04:00Z", kind: "failure", ref_id: "demo-12", text: "Aquisição falhou · mídia indisponível na origem" },
  { at: "2026-10-18T20:51:00Z", kind: "failure", ref_id: "demo-13", text: "Transcrição excedeu o tempo limite" },
  { at: "2026-10-18T14:40:00Z", kind: "curation", ref_id: "demo-01", text: "Curador marcou como Manter · Fluxo de legendas…" },
  { at: "2026-10-18T14:31:00Z", kind: "analysis", ref_id: "demo-01", text: "Análise concluída · Automação (sustentado por imagem)" },
  { at: "2026-10-18T10:12:00Z", kind: "analysis", ref_id: "demo-02", text: "Análise concluída · Edição audiovisual" },
];

// Taxa diária de etapas concluídas sem falha (últimos 7 dias), só para o gráfico demonstrativo.
export const HEALTH_SERIES = [0.81, 0.86, 0.84, 0.9, 0.88, 0.93, 0.86];

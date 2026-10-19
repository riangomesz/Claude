// Telas. Cada view recebe ctx = { adapter, state, go, openDetail, rerender } e devolve { title, subtitle, body }.
import { h, fmt, SurfaceCard, MetricCard, StatusBadge, ReferenceCard, FilterBar, SearchInput, ActivityFeed, EmptyState, ErrorState,
  LoadingState, Tabs, DetailPanel, confirmAction, toast, Stars, ThemeSwitcher } from "./ui.js";
import { icon } from "./icons.js";
import { labels, CATEGORIES, RATINGS, CURATION, PROCESSING, PLATFORMS, STAGE_GROUPS, EVIDENCE } from "./domain.js";

const SVG = "http://www.w3.org/2000/svg";
const s = (tag, attrs = {}) => { const el = document.createElementNS(SVG, tag); for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v); return el; };

// Carrega dados com estados de carregamento e erro; `build` recebe os dados e devolve o conteúdo.
function loadInto(load, build, kind = "grid") {
  const host = h("div", { class: "view" }, LoadingState(kind));
  const run = () => {
    host.replaceChildren(LoadingState(kind));
    load().then((data) => host.replaceChildren(build(data)))
      .catch((err) => host.replaceChildren(SurfaceCard({}, ErrorState({ text: err.message || "Erro inesperado.", onRetry: run }))));
  };
  run();
  return host;
}

/* ============ Visão Geral ============ */

function hero(sum) {
  const failLink = sum.failures
    ? h("a", { class: "badge badge-danger", href: "#/library?processing=falhou", style: { "text-decoration": "none" } }, icon("alert", 12),
      `${sum.failures} ${sum.failures === 1 ? "falha exige" : "falhas exigem"} atenção`)
    : StatusBadge("success", "Nenhuma falha pendente", "curation");
  return SurfaceCard({ title: "Catálogo audiovisual", sub: "Referências salvas, analisadas e à espera da sua decisão", className: "span-2 hero-card", demo: true },
    h("div", { class: "hero-top" },
      h("p", { class: "hero-value" }, fmt.int(sum.catalogued), h("small", null, "referências catalogadas")),
      failLink),
    h("div", { class: "hero-body" },
      h("div", { class: "orbs", role: "list", "aria-label": "Indicadores do catálogo" },
        h("div", { role: "listitem" }, MetricCard({ label: "Aguardando curadoria", value: fmt.int(sum.awaitingCuration), href: "#/curation" })),
        h("div", { role: "listitem" }, MetricCard({ label: "Análises concluídas", value: fmt.int(sum.analysed), focus: true, href: "#/analysis" })),
        h("div", { role: "listitem" }, MetricCard({ label: "Em processamento", value: fmt.int(sum.processing), href: "#/library?processing=processando" }))),
      h("div", { class: "hero-actions" },
        h("a", { class: "btn btn-primary", href: "#/curation" }, icon("curation", 16), "Iniciar curadoria"),
        h("a", { class: "btn btn-secondary", href: "#/library" }, icon("library", 16), "Abrir biblioteca"))));
}

function categoryBars(sum) {
  const entries = CATEGORIES.map(([k]) => [k, sum.categories[k] || 0]);
  const max = Math.max(1, ...entries.map(([, n]) => n));
  let active = entries.reduce((a, b) => (b[1] > a[1] ? b : a))[0];
  const foot = h("div", { class: "bars-foot" });
  const updateFoot = () => foot.replaceChildren(h("span", null, `${labels.category(active)}: ${sum.categories[active] || 0} de ${sum.analysed}`),
    h("a", { class: "link-btn", href: `#/library?category=${active}` }, "Ver na biblioteca"));
  const bars = h("div", { class: "bars", role: "group", "aria-label": "Referências analisadas por categoria" }, entries.map(([k, n]) => {
    const btn = h("button", { type: "button", class: "bar", style: { "--h": `${Math.round((n / max) * 100)}%` }, "aria-pressed": String(k === active),
      "aria-label": `${labels.category(k)}: ${n} ${n === 1 ? "referência" : "referências"}`,
      onClick: () => {
        active = k;
        bars.querySelectorAll(".bar").forEach((b) => { const on = b === btn; b.setAttribute("aria-pressed", String(on)); b.parentElement.classList.toggle("is-active", on); });
        updateFoot();
      } }, h("span", { class: "tooltip", "aria-hidden": "true" }, String(n)));
    return h("div", { class: `bar-col ${k === active ? "is-active" : ""}` }, btn, h("span", { class: "bar-label", "aria-hidden": "true", title: labels.category(k) }, labels.categoryShort(k)));
  }));
  updateFoot();
  return SurfaceCard({ title: "Distribuição por categoria", sub: "Categoria principal sugerida pela análise", demo: true },
    sum.analysed ? [bars, foot] : EmptyState({ icon: "analysis", title: "Sem análises ainda", text: "A distribuição aparece quando houver referências analisadas." }));
}

function healthCard(sum) {
  const series = sum.healthSeries || [];
  const rate = sum.analysed + sum.failures ? sum.analysed / (sum.analysed + sum.failures) : null;
  let chart = h("p", { class: "card-sub" }, "Série histórica indisponível nesta fonte de dados.");
  if (series.length > 1) {
    const W = 300, H = 96, pad = 10, lo = Math.min(...series) - 0.05, hi = Math.max(...series) + 0.02;
    const pts = series.map((v, i) => [pad + (i * (W - 2 * pad)) / (series.length - 1), pad + (1 - (v - lo) / (hi - lo)) * (H - 2 * pad - 14)]);
    const d = pts.map(([x, y], i) => `${i ? "L" : "M"}${x.toFixed(1)} ${y.toFixed(1)}`).join(" ");
    const svg = s("svg", { class: "health-chart", viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": `Taxa diária de etapas sem falha, de ${fmt.pct(series[0])} a ${fmt.pct(series.at(-1))}` });
    svg.append(s("path", { d }));
    const [lx, ly] = pts.at(-1);
    svg.append(s("circle", { cx: lx, cy: ly, r: 4 }));
    const t1 = s("text", { x: pad, y: H - 2 }); t1.textContent = "7 dias atrás";
    const t2 = s("text", { x: W - pad, y: H - 2, "text-anchor": "end" }); t2.textContent = "hoje";
    svg.append(t1, t2);
    chart = svg;
  }
  return SurfaceCard({ title: "Saúde do pipeline", sub: "Análises concluídas frente a falhas", accent: true, demo: true },
    h("p", { class: "health-value" }, rate == null ? "—" : fmt.pct(rate)), chart);
}

function pipelineCard(sum, refs, ctx) {
  const active = refs.filter((r) => r.processing.state !== "concluido").sort((a, b) => (a.processing.state === "falhou") - (b.processing.state === "falhou"));
  const stageOf = (r) => STAGE_GROUPS.find(([, , st]) => st.includes(r.processing.stage))?.[1] || "—";
  return SurfaceCard({ title: "Progresso do pipeline", sub: "Etapas concluídas no catálogo inteiro e itens ainda em andamento", className: "span-2", demo: true },
    h("div", { class: "stages" }, sum.stageTotals.map((st) => h("div", { class: "stage" },
      h("div", { class: "stage-track", role: "progressbar", "aria-label": st.label, "aria-valuenow": Math.round(st.ratio * 100), "aria-valuemin": 0, "aria-valuemax": 100 },
        h("div", { class: "stage-fill", style: { "--p": fmt.pct(st.ratio) } })),
      h("small", null, st.label), h("small", { class: "stage-pct" }, fmt.pct(st.ratio))))),
    active.length
      ? h("ul", { class: "list" }, active.map((r) => h("li", null, h("button", { type: "button", class: "row row-btn", onClick: () => ctx.openDetail(r.id) },
        h("span", { class: "row-icon" }, icon(r.processing.state === "falhou" ? "alert" : "layers", 14)),
        h("span", { class: "row-title" }, r.title),
        h("span", { class: "row-meta hide-sm" }, stageOf(r)),
        h("span", { class: `badge badge-${labels.processingKind(r.processing.state)} hide-sm` }, labels.processing(r.processing.state)),
        h("span", { class: "row-value" }, r.processing.state === "falhou" ? "—" : fmt.pct(r.processing.progress))))))
      : EmptyState({ icon: "curation", title: "Nada em andamento", text: "Todas as referências terminaram o processamento." }));
}

function railCards(refs, activity, ctx) {
  const waiting = refs.filter((r) => r.analysis && r.curation === "aguardando");
  return h("div", { class: "rail" },
    h("section", { class: "card tip-card", "aria-labelledby": "tip-t" },
      h("h3", { id: "tip-t" }, "A curadoria é sua"),
      h("p", null, "A análise sugere categorias e mostra as evidências. Manter, revisar ou descartar é sempre uma decisão humana."),
      h("a", { class: "link-btn", href: "#/curation" }, "Ver fila de curadoria")),
    SurfaceCard({ title: "Atividade recente", className: "feed-card", action: h("a", { class: "link-btn", href: "#/activity" }, "Ver tudo") },
      ActivityFeed(activity.slice(0, 5), { onOpen: ctx.openDetail, labels })),
    SurfaceCard({ title: "Ações rápidas", sub: "Revisão rápida das referências analisadas" },
      waiting.length
        ? h("div", { class: "quick-thumbs" }, waiting.slice(0, 4).map((r) => h("button", { type: "button", class: "quick-thumb", "aria-label": `Revisar: ${r.title}`,
          onClick: () => ctx.openDetail(r.id, "curadoria") }, h("span", { class: "mini", style: { background: r.thumb } }), h("span", null, r.author.split(".")[0]))))
        : h("p", { class: "card-sub" }, "Nenhuma referência aguardando decisão."),
      h("div", { class: "quick-foot" },
        h("div", null, h("strong", null, String(waiting.length)), h("div", { class: "card-sub" }, "aguardando decisão")),
        h("a", { class: "btn btn-primary btn-sm", href: "#/curation" }, "Começar"))));
}

export function overview(ctx) {
  return {
    title: "Inteligência audiovisual",
    subtitle: "Panorama do catálogo, do pipeline de análise e da curadoria",
    body: loadInto(() => Promise.all([ctx.adapter.overview(), ctx.adapter.listReferences(), ctx.adapter.listActivity()]),
      ([sum, refs, activity]) => {
        if (!sum.catalogued) {
          return SurfaceCard({}, EmptyState({ icon: "inbox", title: "Catálogo vazio", text: "Nenhuma referência catalogada ainda. Elas aparecem aqui assim que o backend registrar a primeira ingestão." }));
        }
        return h("div", { class: "overview" },
          h("div", { class: "bento" }, hero(sum), categoryBars(sum), healthCard(sum), pipelineCard(sum, refs, ctx)),
          railCards(refs, activity, ctx));
      }, "overview"),
  };
}

/* ============ Biblioteca / Curadoria ============ */

const ALL = ["all", "Todos"];
const FILTERS = [
  { key: "platform", label: "Plataforma", options: [ALL, ...PLATFORMS.map(([k, l]) => [k, l])] },
  { key: "category", label: "Categoria", options: [ALL, ...CATEGORIES.map(([k, l]) => [k, l]), ["none", "Sem categoria"]] },
  { key: "rating", label: "Avaliação", options: [ALL, ...RATINGS.map(([k, l]) => [k, l]), ["none", "Sem nota"]] },
  { key: "curation", label: "Curadoria", options: [ALL, ...CURATION.map(([k, l]) => [k, l])] },
  { key: "processing", label: "Processamento", options: [ALL, ...PROCESSING.map(([k, l]) => [k, l])] },
];
const SORTS = [["recent", "Mais recentes"], ["oldest", "Mais antigas"], ["rating", "Melhor avaliadas"], ["title", "Título (A–Z)"]];
const RATING_ORDER = Object.fromEntries(RATINGS.map(([k, , n]) => [k, n]));

export function applyFilters(refs, { query, filters, sort }) {
  const q = (query || "").trim().toLowerCase();
  const out = refs.filter((r) => {
    for (const [k, v] of Object.entries(filters)) {
      if (v === "all") continue;
      const val = k === "processing" ? r.processing.state : r[k];
      if (v === "none" ? val != null : val !== v) return false;
    }
    if (!q) return true;
    return [r.title, r.author, r.caption, labels.category(r.category), ...(r.hashtags || [])].join(" ").toLowerCase().includes(q);
  });
  const cmp = {
    recent: (a, b) => (b.captured_at || "").localeCompare(a.captured_at || ""),
    oldest: (a, b) => (a.captured_at || "").localeCompare(b.captured_at || ""),
    rating: (a, b) => (RATING_ORDER[b.rating] || 0) - (RATING_ORDER[a.rating] || 0),
    title: (a, b) => a.title.localeCompare(b.title, "pt-BR"),
  }[sort] || (() => 0);
  return out.sort(cmp);
}

function libraryBody(ctx, refs, { lockCuration } = {}) {
  const st = ctx.state;
  const grid = h("div", { class: "ref-grid", id: "ref-grid" });
  const meta = h("div", { class: "result-meta", "aria-live": "polite" });
  const filters = lockCuration ? FILTERS.filter((f) => f.key !== "curation" && f.key !== "processing") : FILTERS;
  const values = lockCuration ? { ...st.filters, curation: "aguardando", processing: "concluido" } : st.filters;
  const anyActive = () => st.query || filters.some((f) => st.filters[f.key] !== "all");
  const clear = () => { st.query = ""; FILTERS.forEach((f) => (st.filters[f.key] = "all")); ctx.rerender(); };
  const draw = () => {
    const vis = applyFilters(refs, { query: st.query, filters: lockCuration ? { ...st.filters, curation: "aguardando", processing: "concluido" } : st.filters, sort: st.sort });
    meta.replaceChildren(h("span", null, `${vis.length} de ${refs.length} ${refs.length === 1 ? "referência" : "referências"}`),
      ...(anyActive() ? [h("button", { type: "button", class: "link-btn", onClick: clear }, "Limpar filtros")] : []));
    if (!refs.length) {
      grid.replaceChildren(h("div", { style: { "grid-column": "1 / -1" } }, SurfaceCard({}, lockCuration
        ? EmptyState({ icon: "curation", title: "Fila de curadoria vazia", text: "Nenhuma referência analisada aguarda decisão." })
        : EmptyState({ icon: "inbox", title: "Catálogo vazio", text: "Nenhuma referência catalogada ainda." }))));
      return;
    }
    grid.replaceChildren(...(vis.length ? vis.map((r) => ReferenceCard(r, { selected: st.selected === r.id, onOpen: (x) => ctx.openDetail(x.id, lockCuration ? "curadoria" : undefined), labels }))
      : [h("div", { style: { "grid-column": "1 / -1" } }, SurfaceCard({}, EmptyState({ icon: "search", title: "Nada encontrado", text: "Nenhuma referência corresponde à busca e aos filtros.",
        action: h("button", { type: "button", class: "btn btn-secondary btn-md", onClick: clear }, "Limpar filtros") })))]));
  };
  const sortSel = h("div", { class: "field" }, h("label", { for: "sort" }, "Ordenar"),
    h("select", { class: "select", id: "sort", onChange: (e) => { st.sort = e.target.value; draw(); } }, SORTS.map(([v, l]) => h("option", { value: v, selected: st.sort === v }, l))));
  const toolbar = h("div", { class: "toolbar" },
    h("div", { class: "toolbar-row" },
      SearchInput({ value: st.query, placeholder: "Buscar por título, autor, legenda ou hashtag", label: "Buscar na biblioteca", id: "lib-search", onInput: (v) => { st.query = v; draw(); } }),
      sortSel),
    FilterBar({ filters, values, onChange: (k, v) => { st.filters[k] = v; draw(); } }),
    meta);
  ctx.redrawGrid = draw;
  draw();
  return h("div", null, toolbar, grid);
}

export function library(ctx) {
  return {
    title: "Biblioteca",
    subtitle: "Todas as referências catalogadas, com filtros por plataforma, categoria, avaliação e estado",
    body: loadInto(() => ctx.adapter.listReferences(), (refs) => libraryBody(ctx, refs)),
  };
}

export function curation(ctx) {
  return {
    title: "Curadoria",
    subtitle: "Referências analisadas que aguardam a sua decisão: manter, revisar ou descartar",
    body: loadInto(() => ctx.adapter.listReferences(), (refs) => libraryBody(ctx, refs, { lockCuration: true })),
  };
}

/* ============ Análises, Conhecimento, Automações, Atividades ============ */

export function analysis(ctx) {
  return {
    title: "Análises",
    subtitle: "Resultado da análise audiovisual por referência e força das evidências",
    body: loadInto(() => ctx.adapter.listReferences(), (refs) => {
      const done = refs.filter((r) => r.analysis);
      const ev = {};
      done.forEach((r) => r.evidence.forEach((e) => (ev[e.status] = (ev[e.status] || 0) + 1)));
      const total = Object.values(ev).reduce((a, b) => a + b, 0);
      return h("div", { class: "overview" },
        SurfaceCard({ title: "Referências analisadas", sub: `${done.length} com análise corrente`, demo: true },
          done.length ? h("ul", { class: "list" }, done.map((r) => h("li", null, h("button", { type: "button", class: "row row-btn", onClick: () => ctx.openDetail(r.id, "analise") },
            h("span", { class: "row-icon" }, icon("sparkle", 14)),
            h("span", { class: "row-title" }, r.title),
            h("span", { class: "row-meta hide-sm" }, labels.category(r.category)),
            h("span", { class: "badge badge-outline hide-sm" }, labels.support(r.categories[0]?.support)),
            h("span", { class: "row-value" }, `${r.evidence.length} evid.`)))))
            : EmptyState({ icon: "analysis", title: "Nenhuma análise concluída", text: "As análises aparecem aqui quando o pipeline terminar a classificação." })),
        h("div", { class: "rail" }, SurfaceCard({ title: "Evidências por status", sub: "Do mais forte (observado) ao mais fraco (não verificado)" },
          total ? h("div", { class: "cat-bars" }, EVIDENCE.map(([k, l, , ic]) => h("div", { class: "cat-row" }, icon(ic, 16),
            h("div", { class: "cat-name" }, h("span", null, l), h("div", { class: "cat-track" }, h("div", { class: "cat-fill", style: { "--c": "var(--accent-gradient)", "--p": fmt.pct((ev[k] || 0) / total) } }))),
            h("span", { class: "cat-count" }, String(ev[k] || 0)))))
            : h("p", { class: "card-sub" }, "Sem evidências registradas."))));
    }),
  };
}

export function knowledge(ctx) {
  return {
    title: "Conhecimento",
    subtitle: "Ferramentas, processos e técnicas extraídos das referências — demonstrados ou só mencionados",
    body: loadInto(() => ctx.adapter.listReferences(), (refs) => {
      const items = refs.flatMap((r) => r.knowledge.map((k) => ({ ...k, ref: r })));
      return SurfaceCard({ title: "Itens extraídos", sub: `${items.length} itens em ${new Set(items.map((i) => i.ref.id)).size} referências`, demo: true },
        items.length ? h("ul", { class: "list" }, items.map((k) => h("li", null, h("button", { type: "button", class: "row row-btn", onClick: () => ctx.openDetail(k.ref.id, "conhecimento") },
          h("span", { class: "row-icon" }, icon(k.kind === "ferramenta" ? "tool" : k.kind === "processo" ? "layers" : "sparkle", 14)),
          h("span", { class: "row-title" }, k.name),
          h("span", { class: "row-meta hide-sm" }, k.ref.title),
          h("span", { class: "badge badge-outline hide-sm" }, k.kind),
          k.demonstrated ? StatusBadge("success", "Demonstrado") : StatusBadge("warning", "Só mencionado")))))
          : EmptyState({ icon: "knowledge", title: "Nenhum conhecimento extraído", text: "Itens aparecem quando a análise identifica ferramentas, processos ou técnicas." }));
    }, "list"),
  };
}

export function automations() {
  return {
    title: "Automações",
    subtitle: "Integrações e fluxos automáticos",
    body: h("div", { class: "view" }, SurfaceCard({ className: "placeholder-card" }, EmptyState({ icon: "automation", title: "Nenhuma automação conectada",
      text: "Esta interface não dispara automações. A integração com o orquestrador de fluxos depende de ambiente e autorização próprios e não faz parte desta proposta." }))),
  };
}

export function activity(ctx) {
  return {
    title: "Atividades",
    subtitle: "Eventos de ingestão, pipeline, análise e curadoria",
    body: loadInto(() => ctx.adapter.listActivity(), (items) => SurfaceCard({ title: "Linha do tempo", sub: ctx.adapter.mode === "live" ? "A API ainda não expõe eventos para leitura" : null, demo: ctx.adapter.mode === "demo" },
      ActivityFeed(items, { onOpen: ctx.openDetail, labels })), "list"),
  };
}

export function settings(ctx) {
  const demo = ctx.adapter.mode === "demo";
  const link = (q, l) => h("a", { class: "btn btn-secondary btn-sm", href: `?${q}${location.hash}` }, l);
  return {
    title: "Configurações",
    subtitle: "Aparência e fonte de dados desta interface",
    body: h("div", { class: "settings-grid view" },
      SurfaceCard({ title: "Aparência", sub: "Claro, escuro ou seguir o sistema. A escolha fica salva neste navegador." }, ThemeSwitcher()),
      SurfaceCard({ title: "Fonte de dados", sub: ctx.adapter.notice },
        h("ul", { class: "kv-list" },
          h("li", null, h("span", null, "Modo"), demo ? StatusBadge("pending", "Demonstração") : StatusBadge("success", "ii.be.api.v1")),
          h("li", null, h("span", null, "Curadoria"), h("span", null, demo ? "Só nesta aba, descartada ao recarregar" : "Registrada no backend local"))),
        demo ? h("div", null, h("p", { class: "note" }, "Simular estados da interface:"),
          h("div", { class: "choice-row", style: { "margin-top": "8px" } }, link("simulate=slow", "Carregamento lento"), link("simulate=error", "Erro"), link("simulate=empty", "Catálogo vazio"),
            h("a", { class: "btn btn-secondary btn-sm", href: `${location.pathname}${location.hash}` }, "Normal"))) : null)),
  };
}

/* ============ Painel de detalhe ============ */

function stageList(ref) {
  return h("ul", { class: "kv-list" }, STAGE_GROUPS.map(([, label, stages]) => {
    const vals = stages.map((x) => ref.processing.stages?.[x] || "pending");
    const state = vals.includes("failed") ? ["danger", "Falhou"] : vals.every((v) => v === "done") ? ["success", "Concluída"]
      : vals.includes("running") ? ["info", "Em andamento"] : ["pending", "Pendente"];
    return h("li", null, h("span", null, label), StatusBadge(state[0], state[1]));
  }));
}

function tabVideo(ref) {
  return h("div", null,
    h("div", { class: "section" }, h("h3", null, "Mídia e processamento"),
      h("ul", { class: "kv-list" },
        h("li", null, h("span", null, "Plataforma"), h("span", null, labels.platform(ref.platform))),
        h("li", null, h("span", null, "Duração"), h("span", null, fmt.dur(ref.duration_s))),
        h("li", null, h("span", null, "Estado"), StatusBadge(labels.processingKind(ref.processing.state), labels.processing(ref.processing.state))),
        ref.processing.state !== "concluido" ? h("li", null, h("span", null, "Progresso"), h("span", null, fmt.pct(ref.processing.progress || 0))) : null),
      ref.processing.error ? h("p", { class: "note", role: "note" }, icon("alert", 12), " ", ref.processing.error) : null),
    h("div", { class: "section" }, h("h3", null, "Etapas"), stageList(ref)));
}

function tabMeta(ref, ctx) {
  const demo = ctx.adapter.mode === "demo";
  const row = (k, v) => [h("dt", null, k), h("dd", null, v)];
  return h("div", null,
    h("div", { class: "section" }, h("dl", { class: "meta-grid" },
      row("Autor", ref.author), row("Plataforma", labels.platform(ref.platform)), row("Catalogada em", fmt.time(ref.captured_at)), row("Duração", fmt.dur(ref.duration_s)),
      row("Identificador", ref.id),
      row("Link original", demo ? h("span", { title: "Link fictício da demonstração" }, "fictício (demonstração)")
        : h("a", { href: ref.url, target: "_blank", rel: "noopener noreferrer" }, "Abrir na origem")),
      row("Hashtags", ref.hashtags?.length ? ref.hashtags.join(" ") : "—"))),
    h("div", { class: "section" }, h("h3", null, "Legenda"), h("p", { class: "card-sub" }, ref.caption || "Sem legenda registrada.")));
}

function noAnalysis(ref) {
  const why = { processando: "O pipeline ainda está processando esta referência.", na_fila: "A referência está na fila e ainda não foi processada.",
    falhou: "O processamento falhou antes da análise. Veja o motivo na aba Vídeo.", sem_midia: "A mídia ainda não foi adquirida." }[ref.processing.state] || "Nenhuma análise corrente.";
  return EmptyState({ icon: "analysis", title: "Análise ainda não disponível", text: why });
}

function tabAnalysis(ref) {
  if (!ref.analysis) return noAnalysis(ref);
  const a = ref.analysis;
  return h("div", null,
    h("div", { class: "section" }, h("h3", null, "Resumo"), h("p", { class: "card-sub" }, a.summary || "Resumo não informado pela fonte.")),
    h("div", { class: "section" }, h("h3", null, "Categorias sugeridas"),
      ref.categories.length ? h("ul", { class: "kv-list" }, ref.categories.map((c) => h("li", null, h("span", null, labels.category(c.category)),
        h("span", { class: "ref-badges" }, StatusBadge("outline", labels.support(c.support)), c.review_state === "pending" ? StatusBadge("pending", "Aguarda revisão") : null))))
        : h("p", { class: "card-sub" }, "Nenhuma categoria sugerida.")),
    a.facets?.length ? h("div", { class: "section" }, h("h3", null, "Linguagem audiovisual"),
      h("ul", { class: "kv-list" }, a.facets.map(([k, v]) => h("li", null, h("span", null, k), h("span", { class: "card-sub" }, v))))) : null,
    h("p", { class: "note" }, `Analisada em ${fmt.time(a.analyzed_at)} · classificador ${a.classifier_version || "—"}. Sugestões, não decisões.`));
}

function tabEvidence(ref) {
  if (!ref.evidence.length) return ref.analysis ? EmptyState({ icon: "eye", title: "Sem evidências registradas", text: "A análise corrente não registrou evidências." }) : noAnalysis(ref);
  return h("div", null, EVIDENCE.filter(([k]) => ref.evidence.some((e) => e.status === k)).map(([k]) => {
    const meta = labels.evidence(k);
    const items = ref.evidence.filter((e) => e.status === k);
    return h("div", { class: "section" },
      h("h3", null, h("span", { class: "ref-badges" }, StatusBadge(meta.kind, meta.label, meta.icon), h("span", { class: "card-sub" }, `${items.length}`))),
      items.map((e) => h("div", { class: "evidence-item" }, h("span", { class: "row-icon" }, icon(meta.icon, 14)),
        h("div", null, h("div", null, e.claim), h("div", { class: "card-sub" }, `fonte: ${e.source_type}`)),
        h("time", null, e.t_start_s == null ? "—" : fmt.dur(e.t_start_s)))));
  }), h("p", { class: "note" }, "Trechos de fala e legenda são dado externo: citados como estão, nunca tratados como instrução."));
}

function tabKnowledge(ref) {
  if (!ref.knowledge.length) return ref.analysis ? EmptyState({ icon: "knowledge", title: "Nenhum conhecimento extraído", text: "A análise não identificou ferramentas, processos ou técnicas." }) : noAnalysis(ref);
  return h("div", { class: "section" }, h("ul", { class: "kv-list" }, ref.knowledge.map((k) => h("li", null,
    h("span", null, h("strong", null, k.name), h("span", { class: "card-sub" }, ` · ${k.kind}`)),
    k.demonstrated ? StatusBadge("success", "Demonstrado no vídeo") : StatusBadge("warning", "Só mencionado")))));
}

function tabCuration(ref, ctx, refresh) {
  const demo = ctx.adapter.mode === "demo";
  const draft = { triage: ref.curation === "aguardando" ? null : ref.curation, rating: ref.rating };
  const group = (label, opts, key) => {
    const row = h("div", { class: "choice-row", role: "group", "aria-label": label });
    opts.forEach(([v, l]) => row.append(h("button", { type: "button", class: "choice", "aria-pressed": String(draft[key] === v),
      onClick: (e) => { draft[key] = draft[key] === v ? null : v; row.querySelectorAll(".choice").forEach((b) => b.setAttribute("aria-pressed", String(b === e.currentTarget && draft[key] === v))); } }, l)));
    return row;
  };
  const save = h("button", { type: "button", class: "btn btn-primary btn-md" }, "Registrar decisão");
  save.addEventListener("click", async () => {
    if (!draft.triage && !draft.rating) { toast("Escolha uma decisão ou uma avaliação antes de registrar."); return; }
    if (draft.triage === "descartar") {
      const ok = await confirmAction({ title: "Descartar esta referência?", danger: true, confirmLabel: "Descartar",
        text: demo ? "Na demonstração, isto só muda esta aba. Nenhum catálogo é alterado." : "A decisão fica registrada no histórico de curadoria e pode ser revista depois." });
      if (!ok) return;
    }
    save.disabled = true;
    try {
      const res = await ctx.adapter.registerCuration(ref.id, { triage: draft.triage || undefined, rating: draft.rating || undefined });
      toast(res.persisted ? "Decisão registrada no backend." : "Decisão aplicada só nesta demonstração — o catálogo real não foi alterado.");
      refresh(res.reference);
    } catch (err) {
      toast(err.message);
      save.disabled = false;
    }
  });
  return h("div", null,
    h("div", { class: "section" }, h("h3", null, "Decisão"), group("Decisão de curadoria", CURATION.filter(([k]) => k !== "aguardando"), "triage"),
      h("p", { class: "note" }, `Estado atual: ${labels.curation(ref.curation)}`)),
    h("div", { class: "section" }, h("h3", null, "Avaliação"), group("Avaliação", RATINGS.map(([k, l]) => [k, l]), "rating"),
      ref.rating ? h("p", { class: "note" }, "Atual: ", Stars(labels.stars(ref.rating)), ` ${labels.rating(ref.rating)}`) : null),
    h("div", { class: "section" }, h("label", { class: "card-sub", for: "cur-note" }, "Observação (opcional, não enviada nesta versão)"),
      h("textarea", { class: "input", id: "cur-note", rows: "3", placeholder: "Por que manter, revisar ou descartar?" })),
    h("div", { style: { display: "flex", gap: "8px", "margin-top": "16px", "flex-wrap": "wrap", "align-items": "center" } }, save,
      demo ? h("span", { class: "note", style: { margin: 0 } }, "Modo demonstração: a decisão vale só nesta aba e some ao recarregar.") : null));
}

export function openDetail(ctx, id, tab) {
  ctx.state.selected = id;
  document.querySelectorAll(".ref-card").forEach((c) => c.setAttribute("aria-pressed", String(c.dataset.ref === id)));
  const dp = DetailPanel({ title: "Carregando…", onClose: () => { ctx.state.selected = null; document.querySelectorAll(".ref-card").forEach((c) => c.setAttribute("aria-pressed", "false")); } });
  dp.body.append(LoadingState("list"));
  const fill = (ref, keepTab) => {
    dp.panel.querySelector("#detail-title").textContent = ref.title;
    const sub = dp.panel.querySelector(".detail-head .card-sub") || h("p", { class: "card-sub" });
    sub.textContent = `${ref.author} · ${labels.platform(ref.platform)}`;
    dp.panel.querySelector("#detail-title").after(sub);
    const refresh = (updated) => { fill(updated, "curadoria"); ctx.onDataChanged?.(); };
    const tabs = Tabs({ idPrefix: "dt", active: keepTab || tab || "video", tabs: [
      { id: "video", label: "Vídeo", render: () => tabVideo(ref) },
      { id: "metadados", label: "Metadados", render: () => tabMeta(ref, ctx) },
      { id: "analise", label: "Análise audiovisual", render: () => tabAnalysis(ref) },
      { id: "evidencias", label: "Evidências", render: () => tabEvidence(ref) },
      { id: "curadoria", label: "Curadoria", render: () => tabCuration(ref, ctx, refresh) },
      { id: "conhecimento", label: "Conhecimento", render: () => tabKnowledge(ref) },
    ] });
    dp.tabsSlot.replaceChildren(tabs.list);
    dp.body.replaceChildren(h("div", { class: "detail-grid" },
      h("div", { class: "media" }, h("div", { class: "thumb" }, h("div", { class: "thumb-art", style: { background: ref.thumb } }),
        h("div", { class: "thumb-top" }, h("span", { class: "chip-dark" }, icon(labels.platformIcon(ref.platform), 12), labels.platform(ref.platform)), h("span", { class: "chip-dark" }, fmt.dur(ref.duration_s))),
        h("div", { class: "thumb-bottom" }, h("span", { class: "chip-dark" }, icon("play", 12), "Prévia"))),
        h("p", { class: "media-note" }, ctx.adapter.mode === "demo" ? "Prévia ilustrativa: a demonstração não carrega mídia." : "Reprodução depende de mídia local servida pelo backend.")),
      tabs.panel));
  };
  ctx.adapter.getReference(id).then((ref) => fill(ref))
    .catch((err) => dp.body.replaceChildren(ErrorState({ text: err.message, onRetry: () => { dp.close(); openDetail(ctx, id, tab); } })));
}

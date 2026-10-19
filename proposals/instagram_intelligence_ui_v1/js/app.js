// Ponto de entrada: tema, adaptador de dados, roteamento por hash e montagem do AppShell.
import { initTheme } from "./theme.js";
import { createAdapter } from "./data/adapter.js";
import { h, Sidebar, Header, SearchInput } from "./ui.js";
import * as V from "./views.js";

initTheme();

const ROUTES = {
  overview: V.overview, library: V.library, curation: V.curation, analysis: V.analysis, knowledge: V.knowledge,
  automations: V.automations, activity: V.activity, settings: V.settings,
};
const FILTER_KEYS = ["platform", "category", "rating", "curation", "processing"];

const state = {
  route: "overview",
  query: "",
  filters: Object.fromEntries(FILTER_KEYS.map((k) => [k, "all"])),
  sort: "recent",
  selected: null,
  lastHash: null,
};

const adapter = createAdapter();
const root = document.getElementById("app");
let firstRender = true;

const ctx = {
  adapter,
  state,
  go: (hash) => { location.hash = hash; },
  rerender: () => render(),
  openDetail: (id, tab) => V.openDetail(ctx, id, tab),
  // Depois de uma decisão de curadoria, só a grade/tela por trás do painel é redesenhada.
  onDataChanged: () => render({ keepFocus: true }),
};

function parseHash() {
  const m = location.hash.match(/^#\/([\w-]+)(?:\?(.*))?$/);
  const route = m && ROUTES[m[1]] ? m[1] : "overview";
  const params = new URLSearchParams(m?.[2] || "");
  return { route, params };
}

function render({ keepFocus } = {}) {
  const { route, params } = parseHash();
  const changed = route !== state.route;
  state.route = route;
  // Filtros vindos do link valem só quando o hash muda; depois o usuário manda.
  if (location.hash !== state.lastHash && [...params.keys()].some((k) => FILTER_KEYS.includes(k))) {
    FILTER_KEYS.forEach((k) => (state.filters[k] = params.get(k) || "all"));
  }
  state.lastHash = location.hash;
  const view = ROUTES[route](ctx);
  const search = route === "library" || route === "curation" ? null
    : SearchInput({ placeholder: "Buscar referências", label: "Buscar referências na biblioteca", id: "global-search",
      onEnter: (v) => { state.query = v; ctx.go("#/library"); } });
  const status = adapter.mode === "demo" ? "demo" : "live";
  const main = h("main", { id: "main", class: "main", tabindex: "-1" },
    Header({ title: view.title, subtitle: view.subtitle, status, search }),
    view.body);
  root.replaceChildren(Sidebar(route), main);
  document.title = `${view.title} · Instagram Intelligence`;
  if (!firstRender && changed && !keepFocus) document.getElementById("page-title")?.focus({ preventScroll: true });
  if (changed && !firstRender) window.scrollTo({ top: 0 });
  firstRender = false;
}

window.addEventListener("hashchange", () => render());
render();

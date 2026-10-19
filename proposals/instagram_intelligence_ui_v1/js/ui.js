// Componentes reutilizáveis. Todo texto entra como nó de texto (sem innerHTML com dado externo).
import { icon } from "./icons.js";
import { getPreference, setPreference, onThemeChange } from "./theme.js";

export function h(tag, attrs, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k === "class") el.className = v;
    else if (k === "style" && typeof v === "object") for (const [p, val] of Object.entries(v)) el.style.setProperty(p, val);
    else if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2).toLowerCase(), v);
    else if (k === "value" || k === "checked" || k === "selected") el[k] = v;
    else el.setAttribute(k, v === true ? "" : String(v));
  }
  append(el, children);
  return el;
}

function append(el, children) {
  for (const c of children.flat(Infinity)) {
    if (c == null || c === false) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
}

export const fmt = {
  int: (n) => new Intl.NumberFormat("pt-BR").format(n),
  pct: (x) => `${Math.round(x * 100)}%`,
  dur: (s) => (s == null ? "—" : `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, "0")}`),
  date: (iso) => (iso ? new Date(iso).toLocaleDateString("pt-BR", { day: "2-digit", month: "short" }) : "—"),
  time: (iso) => (iso ? new Date(iso).toLocaleString("pt-BR", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" }) : "—"),
};

/* ---------- AppShell, Sidebar, Header ---------- */

export const NAV = [
  { id: "overview", label: "Visão Geral", icon: "overview" },
  { id: "library", label: "Biblioteca", icon: "library" },
  { id: "curation", label: "Curadoria", icon: "curation" },
  { id: "analysis", label: "Análises", icon: "analysis" },
  { id: "knowledge", label: "Conhecimento", icon: "knowledge" },
  { id: "automations", label: "Automações", icon: "automation" },
  { id: "activity", label: "Atividades", icon: "activity" },
];
export const NAV_SETTINGS = { id: "settings", label: "Configurações", icon: "settings" };

function navItem(item, route) {
  return h("a", { class: "nav-item", href: `#/${item.id}`, "aria-label": item.label, "aria-current": route === item.id ? "page" : null },
    icon(item.icon, 20), h("span", { class: "tip", "aria-hidden": "true" }, item.label));
}

export function Sidebar(route) {
  return h("aside", { class: "sidebar" },
    h("a", { class: "brand-mark", href: "#/overview", "aria-label": "Instagram Intelligence — início" }, icon("logo", 28)),
    h("nav", { class: "nav", "aria-label": "Seções" }, NAV.map((n) => navItem(n, route))),
    h("div", { class: "nav-bottom" }, navItem(NAV_SETTINGS, route)));
}

export function ThemeSwitcher() {
  const opts = [["light", "Claro", "sun"], ["dark", "Escuro", "moon"], ["system", "Sistema", "system"]];
  const group = h("div", { class: "segmented theme-switch", role: "group", "aria-label": "Tema da interface" });
  const sync = () => group.querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.pref === getPreference())));
  for (const [pref, label, ic] of opts) {
    group.append(h("button", { type: "button", "data-pref": pref, title: `Tema ${label.toLowerCase()}`, onClick: () => setPreference(pref) },
      icon(ic, 14), h("span", { class: "lbl" }, label)));
  }
  sync();
  // Remove o ouvinte quando o seletor sai do DOM (a tela é redesenhada a cada navegação).
  const off = onThemeChange(() => (group.isConnected ? sync() : off()));
  return group;
}

export function StatusIndicator(status) {
  const map = {
    demo: ["Modo demonstração", ""],
    live: ["API local conectada", "live"],
    error: ["API indisponível", "error"],
    loading: ["Conectando…", ""],
  };
  const [text, cls] = map[status] || map.demo;
  return h("span", { class: "status-pill", role: "status", title: status === "demo" ? "Dados fictícios de demonstração" : text },
    h("span", { class: `status-dot ${cls}`, "aria-hidden": "true" }), text);
}

export function Header({ title, subtitle, status, search }) {
  return h("header", { class: "header" },
    h("div", { class: "title" }, h("h1", { id: "page-title", tabindex: "-1" }, title), subtitle ? h("p", null, subtitle) : null),
    h("div", { class: "header-actions" }, search || null, StatusIndicator(status), ThemeSwitcher()));
}

/* ---------- superfícies e métricas ---------- */

export function SurfaceCard({ title, sub, action, accent, className, demo, labelledBy }, ...children) {
  const id = title ? `card-${Math.random().toString(36).slice(2, 8)}` : null;
  return h("section", { class: `card ${accent ? "card-accent" : ""} ${className || ""}`.trim(), "aria-labelledby": labelledBy || id },
    title || action ? h("div", { class: "card-head" },
      h("div", null, title ? h("h2", { class: "card-title", id }, title) : null, sub ? h("p", { class: "card-sub" }, sub) : null),
      h("div", { class: "card-tools" }, demo ? h("span", { class: "demo-flag" }, "demo") : null, action || null)) : null,
    children);
}

export function MetricCard({ label, value, focus, href, hint }) {
  return h(href ? "a" : "div", { class: `orb ${focus ? "is-focus" : ""}`, href, title: hint || null },
    h("strong", null, value), h("span", null, label));
}

export function StatusBadge(kind, text, ic) {
  return h("span", { class: `badge badge-${kind}` }, ic ? icon(ic, 12) : null, text);
}

/* ---------- busca e filtros ---------- */

export function SearchInput({ value = "", placeholder = "Buscar", label = "Buscar", onInput, onEnter, id }) {
  const inputId = id || `s-${Math.random().toString(36).slice(2, 8)}`;
  let t;
  const input = h("input", { class: "input", type: "search", id: inputId, value, placeholder, autocomplete: "off",
    onInput: (e) => { clearTimeout(t); t = setTimeout(() => onInput?.(e.target.value), 160); },
    onKeydown: (e) => { if (e.key === "Enter") onEnter?.(e.target.value); } });
  return h("div", { class: "search", role: "search" }, h("label", { class: "sr-only", for: inputId }, label), icon("search", 16), input);
}

export function FilterBar({ filters, values, onChange }) {
  return h("div", { class: "filters" }, filters.map((f) => {
    const id = `f-${f.key}`;
    return h("div", { class: "field" },
      h("label", { for: id }, f.label),
      h("select", { class: "select", id, onChange: (e) => onChange(f.key, e.target.value) },
        f.options.map(([v, l]) => h("option", { value: v, selected: values[f.key] === v }, l))));
  }));
}

/* ---------- referência ---------- */

export function Stars(n) {
  return h("span", { class: "stars", role: "img", "aria-label": `${n} de 4` }, Array.from({ length: n }, () => icon("star", 12)));
}

export function ReferenceCard(ref, { selected, onOpen, labels }) {
  const art = h("div", { class: "thumb-art", style: { background: ref.thumb } });
  return h("button", { type: "button", class: "ref-card", "aria-pressed": String(!!selected), "data-ref": ref.id,
    "aria-label": `${ref.title}. ${labels.platform(ref.platform)}, ${labels.category(ref.category)}, ${labels.curation(ref.curation)}`, onClick: () => onOpen(ref) },
    h("div", { class: "thumb" }, art,
      h("div", { class: "thumb-top" }, h("span", { class: "chip-dark" }, icon(labels.platformIcon(ref.platform), 12), labels.platform(ref.platform)),
        h("span", { class: "chip-dark" }, fmt.dur(ref.duration_s))),
      h("div", { class: "thumb-bottom" }, h("span", { class: "chip-dark" }, labels.processingShort(ref.processing.state)))),
    h("div", { class: "ref-body" },
      h("p", { class: "ref-title" }, ref.title),
      h("span", { class: "ref-author" }, ref.author),
      h("div", { class: "ref-badges" },
        StatusBadge("outline", labels.category(ref.category)),
        ref.rating ? StatusBadge("info", labels.rating(ref.rating)) : null,
        // Sem análise ainda não há o que curar: o selo só aparece com análise ou decisão registrada.
        ref.analysis || ref.curation !== "aguardando" ? StatusBadge(labels.curationKind(ref.curation), labels.curation(ref.curation)) : null)));
}

/* ---------- feed, estados ---------- */

export function ActivityFeed(items, { onOpen, labels }) {
  if (!items.length) return EmptyState({ icon: "activity", title: "Sem atividade registrada", text: "Os eventos do pipeline e da curadoria aparecem aqui." });
  return h("ul", { class: "list feed" }, items.map((a) => {
    const inner = [h("span", { class: "row-icon" }, icon(labels.activityIcon(a.kind), 14)),
      h("span", { class: "row-text" }, h("span", { class: "row-title" }, a.text), h("span", { class: "row-meta" }, fmt.time(a.at))),
      StatusBadge(labels.activityKind(a.kind)[0], labels.activityKind(a.kind)[1])];
    return h("li", null, a.ref_id && onOpen ? h("button", { type: "button", class: "row", onClick: () => onOpen(a.ref_id) }, inner) : h("div", { class: "row" }, inner));
  }));
}

export function EmptyState({ icon: ic = "inbox", title, text, action }) {
  return h("div", { class: "empty" }, h("div", { class: "empty-icon" }, icon(ic, 24)), h("h3", null, title), text ? h("p", null, text) : null, action || null);
}

export function ErrorState({ title = "Não foi possível carregar", text, onRetry }) {
  return h("div", { class: "empty is-error", role: "alert" }, h("div", { class: "empty-icon" }, icon("alert", 24)), h("h3", null, title), text ? h("p", null, text) : null,
    onRetry ? h("button", { type: "button", class: "btn btn-secondary btn-md", onClick: onRetry }, icon("refresh", 16), "Tentar de novo") : null);
}

export function LoadingState(kind = "grid", count = 8) {
  const wrap = h("div", { "aria-busy": "true", "aria-live": "polite" }, h("span", { class: "sr-only" }, "Carregando…"));
  if (kind === "grid") wrap.append(h("div", { class: "loading-grid" }, Array.from({ length: count }, () => h("div", { class: "skeleton", style: { "aspect-ratio": "9 / 19" } }))));
  else wrap.append(h("div", { class: "bento" }, h("div", { class: "skeleton span-2", style: { height: "260px" } }),
    h("div", { class: "skeleton", style: { height: "240px" } }), h("div", { class: "skeleton", style: { height: "240px" } })));
  return wrap;
}

/* ---------- Tabs (padrão WAI-ARIA, ativação automática) ---------- */

export function Tabs({ tabs, active, onChange, idPrefix = "tab" }) {
  const list = h("div", { class: "tabs", role: "tablist", "aria-label": "Seções do detalhe" });
  const panel = h("div", { class: "tab-panel", role: "tabpanel", tabindex: "0" });
  const select = (id, focus) => {
    list.querySelectorAll('[role="tab"]').forEach((b) => {
      const on = b.dataset.id === id;
      b.setAttribute("aria-selected", String(on));
      b.tabIndex = on ? 0 : -1;
      if (on) { panel.setAttribute("aria-labelledby", b.id); if (focus) b.focus(); }
    });
    panel.replaceChildren(tabs.find((t) => t.id === id).render());
    panel.style.animation = "none"; void panel.offsetWidth; panel.style.animation = "";
    onChange?.(id);
  };
  tabs.forEach((t) => list.append(h("button", { type: "button", role: "tab", class: "tab", id: `${idPrefix}-${t.id}`, "data-id": t.id, onClick: () => select(t.id) }, t.label)));
  list.addEventListener("keydown", (e) => {
    const ids = tabs.map((t) => t.id);
    const cur = ids.indexOf(document.activeElement?.dataset?.id);
    if (cur < 0) return;
    const next = { ArrowRight: cur + 1, ArrowLeft: cur - 1, Home: 0, End: ids.length - 1 }[e.key];
    if (next == null) return;
    e.preventDefault();
    select(ids[(next + ids.length) % ids.length], true);
  });
  select(active || tabs[0].id);
  return { list, panel, select };
}

/* ---------- camada modal: foco preso, Esc, foco devolvido ---------- */

const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

function trapFocus(container, onEscape) {
  const handler = (e) => {
    if (e.key === "Escape") { e.preventDefault(); onEscape(); return; }
    if (e.key !== "Tab") return;
    const items = [...container.querySelectorAll(FOCUSABLE)].filter((x) => x.offsetParent !== null || x === document.activeElement);
    if (!items.length) return;
    const first = items[0], last = items[items.length - 1];
    if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
  };
  container.addEventListener("keydown", handler);
}

export function DetailPanel({ title, subtitle, onClose, labelId = "detail-title" }) {
  const layer = document.getElementById("layer");
  const returnTo = document.activeElement;
  const overlay = h("div", { class: "overlay", "aria-hidden": "true" });
  const body = h("div", { class: "detail-body" });
  const closeBtn = h("button", { type: "button", class: "icon-btn", "aria-label": "Fechar detalhe" }, icon("close", 18));
  const tabsSlot = h("div");
  const panel = h("div", { class: "detail", role: "dialog", "aria-modal": "true", "aria-labelledby": labelId },
    h("div", { class: "detail-head" }, h("div", { style: { "min-width": "0" } }, h("h2", { id: labelId }, title), subtitle ? h("p", { class: "card-sub" }, subtitle) : null), closeBtn),
    tabsSlot, body);
  let closed = false;
  const close = () => {
    if (closed) return;
    closed = true;
    overlay.classList.remove("open");
    panel.classList.remove("open");
    document.body.style.overflow = "";
    const done = () => { overlay.remove(); panel.remove(); };
    matchMedia("(prefers-reduced-motion: reduce)").matches ? done() : setTimeout(done, 260);
    if (returnTo && document.contains(returnTo)) returnTo.focus();
    onClose?.();
  };
  overlay.addEventListener("click", close);
  closeBtn.addEventListener("click", close);
  trapFocus(panel, close);
  layer.append(overlay, panel);
  document.body.style.overflow = "hidden";
  requestAnimationFrame(() => { overlay.classList.add("open"); panel.classList.add("open"); closeBtn.focus(); });
  return { panel, body, tabsSlot, close };
}

export function confirmAction({ title, text, confirmLabel = "Confirmar", cancelLabel = "Cancelar", danger = false }) {
  return new Promise((resolve) => {
    const layer = document.getElementById("layer");
    const returnTo = document.activeElement;
    const ok = h("button", { type: "button", class: `btn btn-md ${danger ? "btn-danger" : "btn-primary"}` }, confirmLabel);
    const cancel = h("button", { type: "button", class: "btn btn-md btn-secondary" }, cancelLabel);
    const dialog = h("div", { class: "dialog", role: "alertdialog", "aria-modal": "true", "aria-labelledby": "dlg-t", "aria-describedby": "dlg-d" },
      h("h2", { id: "dlg-t" }, title), h("p", { id: "dlg-d" }, text), h("div", { class: "dialog-actions" }, cancel, ok));
    const backdrop = h("div", { class: "dialog-backdrop" }, dialog);
    const finish = (v) => { backdrop.remove(); if (returnTo && document.contains(returnTo)) returnTo.focus(); resolve(v); };
    ok.addEventListener("click", () => finish(true));
    cancel.addEventListener("click", () => finish(false));
    backdrop.addEventListener("click", (e) => { if (e.target === backdrop) finish(false); });
    trapFocus(dialog, () => finish(false));
    layer.append(backdrop);
    cancel.focus();
  });
}

export function toast(message) {
  const region = document.getElementById("toasts");
  const el = h("div", { class: "toast" }, message);
  region.append(el);
  setTimeout(() => el.remove(), 4200);
}

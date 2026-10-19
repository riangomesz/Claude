// Tema: preferência (light | dark | system) persistida; data-theme sempre recebe o tema resolvido.
const KEY = "ii-theme";
const PREFS = ["light", "dark", "system"];
const mq = window.matchMedia ? window.matchMedia("(prefers-color-scheme: dark)") : { matches: false, addEventListener() {} };
const listeners = new Set();

export function getPreference() {
  try {
    const v = localStorage.getItem(KEY);
    return PREFS.includes(v) ? v : "system";
  } catch {
    return "system";
  }
}

export function resolve(pref = getPreference()) {
  return pref === "system" ? (mq.matches ? "dark" : "light") : pref;
}

function apply(pref, animate) {
  const root = document.documentElement;
  const theme = resolve(pref);
  const reduce = window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (animate && !reduce) {
    root.classList.add("theme-transition");
    clearTimeout(apply.t);
    apply.t = setTimeout(() => root.classList.remove("theme-transition"), 320);
  }
  root.setAttribute("data-theme", theme);
  root.setAttribute("data-theme-pref", pref);
  document.querySelector('meta[name="theme-color"]')?.setAttribute("content", theme === "dark" ? "#0B111C" : "#C3CCEE");
  listeners.forEach((fn) => fn({ pref, theme }));
}

export function setPreference(pref) {
  if (!PREFS.includes(pref)) return;
  try {
    localStorage.setItem(KEY, pref);
  } catch {
    /* armazenamento bloqueado: o tema vale só nesta sessão */
  }
  apply(pref, true);
}

export function onThemeChange(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

export function initTheme() {
  apply(getPreference(), false);
  mq.addEventListener("change", () => {
    if (getPreference() === "system") apply("system", true);
  });
}

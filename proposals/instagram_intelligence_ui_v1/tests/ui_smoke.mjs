// Teste de fumaça da interface (Playwright + Chromium). Sem dependência no repositório:
//   NODE_PATH=$(npm root -g) node tests/ui_smoke.mjs [--out DIR] [--shots]
// Sobe um http.server do Python na pasta da proposta, percorre 7 larguras × 2 temas e testa os fluxos principais.
import { spawn } from "node:child_process";
import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { chromium } = require("playwright");

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const args = process.argv.slice(2);
const OUT = args.includes("--out") ? resolve(args[args.indexOf("--out") + 1]) : join(ROOT, "tests", "output");
const SHOTS = args.includes("--shots");
const PORT = 8000 + Math.floor(Math.random() * 900);
const BASE = `http://127.0.0.1:${PORT}/index.html`;
const WIDTHS = [1440, 1280, 1024, 768, 430, 390, 375];
const HEIGHT = { 1440: 900, 1280: 800, 1024: 768, 768: 1024, 430: 932, 390: 844, 375: 812 };

const results = [];
const check = (name, ok, detail = "") => { results.push({ name, ok: !!ok, detail }); console.log(`${ok ? "PASS" : "FAIL"}  ${name}${detail ? `  — ${detail}` : ""}`); };

async function waitServer() {
  for (let i = 0; i < 50; i++) {
    try { const r = await fetch(BASE); if (r.ok) return; } catch { /* ainda subindo */ }
    await new Promise((r) => setTimeout(r, 100));
  }
  throw new Error("http.server não subiu");
}

function watch(page, bag) {
  page.on("console", (m) => { if (m.type() === "error") bag.push(m.text()); });
  page.on("pageerror", (e) => bag.push(String(e)));
}

const overflow = (page) => page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);

async function main() {
  mkdirSync(OUT, { recursive: true });
  const server = spawn("python3", ["-m", "http.server", String(PORT), "--bind", "127.0.0.1"], { cwd: ROOT, stdio: "ignore" });
  const browser = await chromium.launch(process.env.PLAYWRIGHT_BROWSERS_PATH ? {} : { executablePath: "/opt/pw-browsers/chromium" });
  try {
    await waitServer();

    // 1) Larguras × temas (tema vindo da preferência do sistema)
    for (const scheme of ["light", "dark"]) {
      for (const w of WIDTHS) {
        const ctx = await browser.newContext({ viewport: { width: w, height: HEIGHT[w] }, colorScheme: scheme });
        const page = await ctx.newPage();
        const errors = [];
        watch(page, errors);
        await page.goto(`${BASE}#/overview`);
        await page.waitForSelector(".hero-value");
        const theme = await page.getAttribute("html", "data-theme");
        const ov1 = await overflow(page);
        if (SHOTS) await page.screenshot({ path: join(OUT, `overview-${w}-${scheme}.png`), fullPage: true });
        await page.goto(`${BASE}#/library`);
        await page.waitForSelector(".ref-card");
        const ov2 = await overflow(page);
        if (SHOTS) await page.screenshot({ path: join(OUT, `library-${w}-${scheme}.png`), fullPage: false });
        await page.locator(".ref-card").first().click();
        await page.waitForSelector(".detail.open .tab-panel");
        await page.waitForTimeout(350); // fim da transição de entrada (300 ms)
        const ov3 = await overflow(page);
        const panelBox = await page.locator(".detail").boundingBox();
        if (SHOTS) await page.screenshot({ path: join(OUT, `detail-${w}-${scheme}.png`) });
        check(`${w}px ${scheme}: tema do sistema aplicado`, theme === scheme, `data-theme=${theme}`);
        check(`${w}px ${scheme}: sem rolagem horizontal`, ov1 <= 0 && ov2 <= 0 && ov3 <= 0, `visão=${ov1} biblioteca=${ov2} detalhe=${ov3}`);
        check(`${w}px ${scheme}: painel cabe na tela`, panelBox && panelBox.x >= 0 && panelBox.x + panelBox.width <= w + 1, JSON.stringify(panelBox && { x: Math.round(panelBox.x), w: Math.round(panelBox.width) }));
        check(`${w}px ${scheme}: sem erro de console`, errors.length === 0, errors.slice(0, 2).join(" | "));
        await ctx.close();
      }
    }

    // 2) Fluxos em 1440 claro
    const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, colorScheme: "light" });
    const page = await ctx.newPage();
    const errors = [];
    watch(page, errors);
    await page.goto(`${BASE}#/overview`);
    await page.waitForSelector(".hero-value");

    // Tema manual + persistência
    await page.locator('.theme-switch button[data-pref="dark"]').click();
    check("tema manual: escuro aplicado", (await page.getAttribute("html", "data-theme")) === "dark");
    check("tema manual: salvo em localStorage", (await page.evaluate(() => localStorage.getItem("ii-theme"))) === "dark");
    await page.reload();
    await page.waitForSelector(".hero-value");
    check("tema manual: persiste após recarregar", (await page.getAttribute("html", "data-theme")) === "dark");
    // Sem flash: com o módulo JS bloqueado, o script inline ainda define o tema antes do paint
    await page.route("**/js/app.js", (r) => r.abort());
    await page.reload();
    check("sem flash: tema resolvido pelo script inline (app.js bloqueado)", (await page.getAttribute("html", "data-theme")) === "dark");
    await page.unroute("**/js/app.js");
    errors.length = 0; // o único erro até aqui é o bloqueio proposital do app.js
    await page.reload();
    await page.waitForSelector(".hero-value");
    await page.locator('.theme-switch button[data-pref="system"]').click();
    check("tema sistema: volta a seguir o sistema (claro)", (await page.getAttribute("html", "data-theme")) === "light");

    // Teclado: primeiro Tab vai para o link de pular
    await page.reload();
    await page.waitForSelector(".hero-value");
    await page.keyboard.press("Tab");
    check("teclado: primeiro foco é o link 'Pular para o conteúdo'", (await page.evaluate(() => document.activeElement?.className)) === "skip-link");

    // Navegação pela barra lateral
    const titles = { library: "Biblioteca", curation: "Curadoria", analysis: "Análises", knowledge: "Conhecimento", automations: "Automações", activity: "Atividades", settings: "Configurações", overview: "Inteligência audiovisual" };
    for (const [id, title] of Object.entries(titles)) {
      await page.locator(`.sidebar .nav-item[href="#/${id}"]`).click();
      await page.waitForFunction((t) => document.querySelector("h1")?.textContent === t, title);
      const current = await page.getAttribute(`.sidebar .nav-item[href="#/${id}"]`, "aria-current");
      check(`navegação: ${title}`, current === "page");
    }

    // Biblioteca: filtros, busca, ordenação
    await page.goto(`${BASE}#/library`);
    await page.waitForSelector(".ref-card");
    const total = await page.locator(".ref-card").count();
    check("biblioteca: 14 referências demonstrativas", total === 14, `${total}`);
    check("biblioteca: barra de resultado sem texto 'null'", !(await page.locator(".result-meta").textContent()).includes("null"));
    await page.selectOption("#f-platform", "tiktok");
    check("filtro plataforma=TikTok", (await page.locator(".ref-card").count()) === 2, `${await page.locator(".ref-card").count()}`);
    await page.selectOption("#f-platform", "all");
    await page.selectOption("#f-processing", "falhou");
    check("filtro processamento=falhou", (await page.locator(".ref-card").count()) === 2);
    await page.selectOption("#f-processing", "all");
    await page.fill("#lib-search", "legendas");
    await page.waitForFunction(() => document.querySelectorAll(".ref-card").length === 1);
    check("busca 'legendas' → 1 resultado", true);
    await page.fill("#lib-search", "zzzz-inexistente");
    await page.waitForSelector(".empty");
    check("busca sem resultado mostra estado vazio", await page.locator(".empty h3").textContent() === "Nada encontrado");
    await page.locator(".result-meta .link-btn").click();
    await page.waitForFunction(() => document.querySelectorAll(".ref-card").length === 14);
    check("limpar filtros restaura a lista", true);
    await page.selectOption("#sort", "title");
    const first = await page.locator(".ref-card .ref-title").first().textContent();
    check("ordenar por título", first.startsWith("Animação"), first);
    // Link do gráfico/hero com filtro na URL
    await page.goto(`${BASE}#/library?processing=falhou`);
    await page.waitForFunction(() => document.querySelectorAll(".ref-card").length === 2);
    check("filtro vindo do link (#/library?processing=falhou)", true);

    // Painel de detalhe: abas, teclado, Esc devolve o foco
    await page.goto(`${BASE}#/library`);
    await page.waitForSelector(".ref-card");
    await page.selectOption("#f-processing", "all");
    await page.selectOption("#sort", "recent");
    const card = page.locator('.ref-card[data-ref="demo-01"]');
    await card.focus();
    await page.keyboard.press("Enter");
    await page.waitForSelector('.detail.open [role="tab"]');
    check("detalhe: 6 abas", (await page.locator('.detail [role="tab"]').count()) === 6);
    check("detalhe: foco inicial no botão fechar", (await page.evaluate(() => document.activeElement?.getAttribute("aria-label"))) === "Fechar detalhe");
    await page.locator('.detail [role="tab"]').first().focus();
    await page.keyboard.press("ArrowRight");
    check("abas: seta direita seleciona Metadados", (await page.getAttribute("#dt-metadados", "aria-selected")) === "true");
    await page.locator("#dt-evidencias").click();
    const groups = await page.locator(".detail .tab-panel .section").count();
    check("evidências agrupadas por status (4 grupos em demo-01)", groups === 4, `${groups}`);
    await page.keyboard.press("Escape");
    await page.waitForSelector(".detail", { state: "detached" });
    check("Esc fecha e devolve o foco ao card", (await page.evaluate(() => document.activeElement?.dataset?.ref)) === "demo-01");
    // Referência sem análise: estado honesto
    await page.locator('.ref-card[data-ref="demo-12"]').click();
    await page.locator("#dt-analise").click();
    check("sem análise: estado vazio explica o motivo", (await page.locator(".detail .empty p").textContent()).includes("falhou"));
    await page.keyboard.press("Escape");

    // Curadoria local (demonstração)
    await page.goto(`${BASE}#/curation`);
    await page.waitForSelector(".ref-card");
    const before = await page.locator(".ref-card").count();
    await page.locator(".ref-card").first().click();
    await page.waitForSelector("#dt-curadoria[aria-selected='true']");
    await page.locator(".detail .choice", { hasText: "Descartar" }).click();
    await page.locator(".detail .btn-primary", { hasText: "Registrar decisão" }).click();
    await page.waitForSelector('[role="alertdialog"]');
    check("descartar pede confirmação", true);
    await page.locator('[role="alertdialog"] button', { hasText: "Cancelar" }).click();
    await page.locator(".detail .choice", { hasText: "Manter" }).click();
    await page.locator(".detail .btn-primary", { hasText: "Registrar decisão" }).click();
    await page.waitForSelector(".toast");
    const toastText = await page.locator(".toast").first().textContent();
    check("curadoria: aviso de que o catálogo real não mudou", toastText.includes("catálogo real não foi alterado"), toastText);
    await page.keyboard.press("Escape");
    await page.waitForFunction((n) => document.querySelectorAll(".ref-card").length === n - 1, before);
    check("curadoria: item sai da fila após a decisão local", true);
    await page.reload();
    await page.waitForSelector(".ref-card");
    check("curadoria demo não persiste ao recarregar", (await page.locator(".ref-card").count()) === before);
    check("fluxos: sem erro de console", errors.length === 0, errors.slice(0, 2).join(" | "));
    await ctx.close();

    // 3) Estados simulados
    for (const [sim, sel, test] of [["error", '[role="alert"]', "erro com botão de tentar de novo"], ["empty", ".empty h3", "catálogo vazio"]]) {
      const c = await browser.newContext({ viewport: { width: 1280, height: 800 } });
      const p = await c.newPage();
      await p.goto(`${BASE.replace("index.html", `index.html?simulate=${sim}`)}#/overview`);
      await p.waitForSelector(sel);
      const ok = sim === "error" ? (await p.locator('[role="alert"] button').count()) === 1 : (await p.locator(".empty h3").textContent()) === "Catálogo vazio";
      check(`simulate=${sim}: ${test}`, ok);
      await c.close();
    }
    const c = await browser.newContext({ viewport: { width: 1280, height: 800 } });
    const p = await c.newPage();
    await p.goto(`${BASE.replace("index.html", "index.html?simulate=slow")}#/library`);
    check("simulate=slow: esqueleto com aria-busy", (await p.locator('[aria-busy="true"] .skeleton').count()) > 0);
    await p.waitForSelector(".ref-card", { timeout: 5000 });
    await c.close();

    // 4) Movimento reduzido
    const rm = await browser.newContext({ viewport: { width: 1280, height: 800 }, reducedMotion: "reduce" });
    const rp = await rm.newPage();
    await rp.goto(`${BASE}#/overview`);
    await rp.waitForSelector(".btn");
    const dur = await rp.evaluate(() => parseFloat(getComputedStyle(document.querySelector(".btn")).transitionDuration));
    check("prefers-reduced-motion: transições anuladas", dur < 0.01, `${dur}s`);
    await rm.close();
  } finally {
    await browser.close();
    server.kill();
  }
  const failed = results.filter((r) => !r.ok);
  writeFileSync(join(OUT, "ui_smoke_results.json"), JSON.stringify({ total: results.length, failed: failed.length, results }, null, 2));
  console.log(`\n${results.length - failed.length}/${results.length} verificações passaram.`);
  process.exit(failed.length ? 1 : 0);
}

main().catch((e) => { console.error(e); process.exit(2); });

// Fonte de dados. A interface só conversa com um adaptador; nunca com fixtures ou fetch diretamente.
//  - DemoAdapter: fixtures fictícias, em memória. Curadoria fica só nesta aba (não toca catálogo nenhum).
//  - HttpAdapter: contrato ii.be.api.v1 (POST /v1/<operação>). NÃO foi executado contra um backend nesta missão.
// Seleção por query string: ?simulate=slow|error|empty (demo) ou ?api=same-origin (HTTP na mesma origem).
import { REFERENCES, ACTIVITY, HEALTH_SERIES, DEMO_NOTICE } from "./fixtures.js";
import { STAGE_GROUPS } from "../domain.js";

export class ApiError extends Error {
  constructor(code, message) {
    super(message);
    this.code = code;
  }
}

const clone = (x) => (typeof structuredClone === "function" ? structuredClone(x) : JSON.parse(JSON.stringify(x)));

export function summarize(refs, extra = {}) {
  const by = (fn) => refs.filter(fn).length;
  const analysed = refs.filter((r) => r.analysis);
  const catCount = {};
  analysed.forEach((r) => { if (r.category) catCount[r.category] = (catCount[r.category] || 0) + 1; });
  const stageTotals = STAGE_GROUPS.map(([id, label, stages]) => {
    let doneCount = 0, total = 0;
    refs.forEach((r) => stages.forEach((s) => { total += 1; if (r.processing.stages?.[s] === "done") doneCount += 1; }));
    return { id, label, ratio: total ? doneCount / total : 0 };
  });
  return {
    catalogued: refs.length,
    awaitingCuration: by((r) => r.analysis && r.curation === "aguardando"),
    analysed: analysed.length,
    processing: by((r) => r.processing.state === "processando" || r.processing.state === "na_fila"),
    failures: by((r) => r.processing.state === "falhou"),
    categories: catCount,
    stageTotals,
    ...extra,
  };
}

export class DemoAdapter {
  constructor(simulate) {
    this.mode = "demo";
    this.notice = DEMO_NOTICE;
    this.simulate = simulate;
    this.refs = simulate === "empty" ? [] : clone(REFERENCES);
    this.activity = simulate === "empty" ? [] : clone(ACTIVITY);
  }
  async _wait() {
    await new Promise((r) => setTimeout(r, this.simulate === "slow" ? 1600 : 120));
    if (this.simulate === "error") throw new ApiError("UNAVAILABLE", "Simulação de erro: a fonte de dados não respondeu.");
  }
  async overview() {
    await this._wait();
    return summarize(this.refs, { healthSeries: this.refs.length ? HEALTH_SERIES : [] });
  }
  async listReferences() {
    await this._wait();
    return clone(this.refs);
  }
  async getReference(id) {
    await this._wait();
    const r = this.refs.find((x) => x.id === id);
    if (!r) throw new ApiError("NOT_FOUND", "Referência não encontrada.");
    return clone(r);
  }
  async listActivity() {
    await this._wait();
    return clone(this.activity);
  }
  // Decisão humana registrada SÓ nesta aba. Recarregar a página descarta.
  async registerCuration(id, { triage, rating, note }) {
    await this._wait();
    const r = this.refs.find((x) => x.id === id);
    if (!r) throw new ApiError("NOT_FOUND", "Referência não encontrada.");
    if (triage) r.curation = triage;
    if (rating !== undefined) r.rating = rating;
    if (note !== undefined) r.note = note;
    this.activity.unshift({ at: new Date().toISOString(), kind: "curation", ref_id: id, text: `Decisão local (demonstração) · ${r.title}` });
    return { persisted: false, reference: clone(r) };
  }
}

// ---------- ii.be.api.v1 ----------
// O servidor local (ii_be.http_local) não responde preflight CORS: a UI precisa ser servida na MESMA origem
// (ex.: pelo review_server ou por proxy reverso). Por isso a única base aceita aqui é a própria origem.
const TRIAGE_TO_API = { manter: "manter", revisar: "revisar_depois", descartar: "descartar" };
const TRIAGE_FROM_API = { manter: "manter", revisar_depois: "revisar", descartar: "descartar" };
// Estados de job do ii_be.queue (ACTIVE + terminais) reduzidos ao que a interface mostra.
const STAGE_STATE = { done: "done", queued: "pending", waiting_dependency: "pending", retry_scheduled: "running", claimed: "running", running: "running",
  completed: "done", failed: "failed", dead_letter: "failed", cancelled: "pending", not_planned: "pending" };

export class HttpAdapter {
  constructor({ reviewer } = {}) {
    this.mode = "live";
    this.notice = "Dados do backend local (ii.be.api.v1).";
    this.reviewer = reviewer || null;
    this.etags = new Map();
  }
  async call(op, body = {}) {
    const res = await fetch(`/v1/${op}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    let json;
    try { json = await res.json(); } catch { throw new ApiError("BAD_RESPONSE", `Resposta inválida (${res.status}).`); }
    if (!json.ok) throw new ApiError(json.error?.code || "ERROR", json.error?.message || "Erro desconhecido.");
    return json.data;
  }
  _base(row) {
    return {
      id: row.reference_id, platform: row.platform, url: row.origin_url, author: row.author_handle ? `@${row.author_handle.replace(/^@/, "")}` : "—",
      title: row.metadata?.title || row.metadata?.caption?.slice(0, 90) || row.canonical_key || row.reference_id,
      caption: row.metadata?.caption || "", hashtags: row.metadata?.hashtags || [], duration_s: row.metadata?.duration_s ?? null,
      captured_at: row.created_at, category: null, categories: [], rating: null, curation: "aguardando",
      processing: { state: row.analysed ? "concluido" : row.media_available ? "na_fila" : "sem_midia", stage: null, progress: row.analysed ? 1 : 0, stages: {} },
      analysis: row.analysed ? { summary: null, facets: [], analyzed_at: null, classifier_version: null } : null,
      evidence: [], knowledge: [],
      thumb: "linear-gradient(165deg, var(--thumb-a), var(--thumb-b) 62%, var(--thumb-c))",
    };
  }
  async listReferences() {
    const out = [];
    let cursor = null;
    do {
      const page = await this.call("list_references", { limit: 200, ...(cursor ? { cursor } : {}) });
      out.push(...page.items.map((r) => this._base(r)));
      cursor = page.next_cursor || null;
    } while (cursor && out.length < 2000);
    return out;
  }
  async getReference(id) {
    const [row, proc, ev, cur, cls] = await Promise.all([
      this.call("get_reference", { reference_id: id }),
      this.call("get_processing", { reference_id: id }),
      this.call("get_evidence", { reference_id: id, limit: 200 }),
      this.call("get_curation", { reference_id: id }),
      this.call("get_classification", { reference_id: id }).catch(() => null),
    ]);
    const r = this._base({ ...row, analysed: !!row.analysis_id, media_available: row.media_state === "available" });
    // get_processing devolve stages como objeto { etapa: { status, job: { last_error, ... } } }
    const entries = Object.entries(proc.stages || {});
    const stages = Object.fromEntries(entries.map(([s, st]) => [s, STAGE_STATE[st.status] || "pending"]));
    const vals = Object.values(stages);
    const failed = vals.includes("failed"), running = vals.includes("running");
    r.processing = { state: failed ? "falhou" : running ? "processando" : vals.length && vals.every((v) => v === "done") ? "concluido" : r.processing.state,
      stage: entries.find(([, st]) => st.status !== "done")?.[0] || null,
      progress: vals.length ? vals.filter((v) => v === "done").length / vals.length : 0, stages,
      error: entries.map(([, st]) => st.job?.last_error).find(Boolean) };
    r.evidence = (ev.items || []).map((e) => ({ id: e.evidence_id, status: e.status, source_type: e.source_type, claim: e.claim, t_start_s: e.t_start_s }));
    if (cls) {
      r.categories = (cls.categories || []).map((c) => ({ category: c.category, support: c.support, review_state: c.review_state }));
      r.category = r.categories[0]?.category || null;
    }
    r.curation = TRIAGE_FROM_API[cur.triage] || "aguardando";
    r.rating = cur.rating || null;
    this.etags.set(id, cur.etag);
    return r;
  }
  async overview() {
    const refs = await this.listReferences();
    const failures = await this.call("list_failures", { limit: 200 }).catch(() => ({ items: [] }));
    return summarize(refs, { failures: (failures.items || []).length, healthSeries: [] });
  }
  async listActivity() {
    return []; // ii.be.api.v1 ainda não expõe o outbox de eventos para leitura.
  }
  async registerCuration(id, { triage, rating }) {
    if (!this.reviewer) throw new ApiError("NO_REVIEWER", "Informe o nome do curador em Configurações antes de registrar decisões.");
    const send = (action, value) => this.call("register_curation", {
      reference_id: id, action, reviewer: `human:${this.reviewer}`, params: { value }, expected_etag: this.etags.get(id),
      idempotency_key: `ui-${id}-${action}-${value}-${Date.now()}`,
    });
    if (triage) await send("triage", TRIAGE_TO_API[triage]);
    if (rating) await send("rating", rating);
    return { persisted: true, reference: await this.getReference(id) };
  }
}

export function createAdapter(search = location.search) {
  const p = new URLSearchParams(search);
  if (p.get("api") === "same-origin") return new HttpAdapter({ reviewer: p.get("reviewer") });
  return new DemoAdapter(p.get("simulate"));
}

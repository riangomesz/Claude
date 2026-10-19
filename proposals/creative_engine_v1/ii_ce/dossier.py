"""Dossiê de inteligência criativa por referência (Markdown + JSON/CSV + manifest). Gerado do banco, de forma determinística:
sem horário no corpo, mesmo estado = mesmos bytes = mesma versão (nada é duplicado). Seção sem dados diz que não há dados."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

from . import _be  # noqa: F401
from ii_be.db import tx
from . import analysis as AN
from . import events as EV
from .commercial import adapt, derive_principles
from .contracts import DOMAIN_LABEL, GENERATOR_VERSION, SCHEMA_MANIFEST, SPECIALISTS, VERIFICATION, canonical_json, clean_text, digest
from .evidence import ev_index, seconds
from .kit import build_kit, shot_list_csv
from .reconcile import latest_reviews

PROFILE_FILE = {"rian_rocha_ia": "04_APLICACAO_RIAN_ROCHA_IA.md", "objetaria": "05_APLICACAO_OBJETARIA.md"}
STATE_PT = {"supported": "sustentada", "supported_static": "aparece no quadro (movimento não comprovado)", "claimed": "dita, não vista", "hypothesis": "hipótese",
            "contradicted": "contradição em aberto", "unverified": "não verificada"}
CLASS_PT = {"tecnica_observada": "Técnica observada", "ferramenta_comprovada": "Ferramenta comprovada", "ferramenta_mencionada": "Ferramenta mencionada",
            "ferramenta_sugerida": "Ferramenta sugerida", "hipotese": "Hipótese", "informacao_ausente": "Informação ausente"}
HUMAN_PT = {"confirmed": "confirmado por humano", "rejected": "REJEITADO por humano", "needs_evidence": "humano pediu mais evidência", "corrected": "corrigido por humano"}


class _Ctx:
    def __init__(self, ce, inv_id: str):
        self.ce, self.inv = ce, ce.get(inv_id)
        self.bundle = self.inv["bundle"]
        self.groups = ce.groups(inv_id)
        self.tasks = [dict(t) for t in ce.conn.execute("SELECT specialist, kind, state, attempts, usd, reason, error, result_json FROM ce_tasks WHERE investigation_id = ? ORDER BY rowid", (inv_id,))]
        self.reviews = latest_reviews(ce.conn, self.bundle["reference_id"])
        self.profiles = ce.profiles(self.inv["profile_ids"])
        self.cited: Set[str] = set()
        self.empty: List[str] = []
        self.ev = ev_index(self.bundle)
        self.banner = getattr(ce, "banner", "")
        self.live = [g for g in self.groups if g.get("human_state") != "rejected"]

    def cite(self, ids) -> str:
        ids = [i for i in ids if i in self.ev]
        self.cited.update(ids)
        return " ".join(f"[ev:{i[3:11]}]" for i in ids[:6]) + (f" +{len(ids) - 6}" if len(ids) > 6 else "") if ids else "_sem evidência_"

    def human(self, g) -> str:
        if not g.get("human_state"):
            return ""
        rv = self.reviews.get(g["key"], {})
        extra = f" por {rv.get('reviewer')}" if rv.get("reviewer") else ""
        note = f": {clean_text(rv.get('note'), 200)}" if rv.get("note") else ""
        corr = f" → valor corrigido: {clean_text(rv.get('corrected_value'), 120)}" if rv.get("corrected_value") else ""
        return f" · **{HUMAN_PT[g['human_state']]}**{extra}{note}{corr}"


def q(text: Any, n: int = 300) -> str:
    return clean_text(text, n).replace("|", "¦").replace("<", "‹").replace(">", "›").replace("`", "'")


def table(headers: List[str], rows: List[List[Any]]) -> str:
    if not rows:
        return "_Sem linhas._\n"
    out = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(out) + "\n"


def header(c: _Ctx, title: str) -> str:
    i = c.inv
    banner = f"> ⚠ **{c.banner}**\n>\n" if c.banner else ""
    return (f"# {title}\n\n{banner}> Referência `{i['reference_id']}` · investigação `{i['investigation_id']}` (versão {i['seq']}) · estado: **{i['state']}** · {GENERATOR_VERSION}\n"
            f"> Verificação: " + " · ".join(f"**{STATE_PT[k]}**" for k in STATE_PT) + ". Concordância entre especialistas não eleva o estado.\n\n")


def nodata(c: _Ctx, section: str, why: str) -> str:
    c.empty.append(section)
    return f"_Sem dados: {why}_\n"


def glist(c: _Ctx, groups: List[Dict[str, Any]]) -> str:
    if not groups:
        return "_Nenhuma afirmação._\n"
    return "\n".join(f"- **{STATE_PT[g['state']]}** · {q(g['summary'], 500)} · {c.cite(g['evidence_ids'])} · especialistas: {', '.join(g['agents'])}{c.human(g)}" for g in groups) + "\n"


# ------------------------------------------------------------------------------------------------ seções
def s01(c: _Ctx, segs) -> str:
    out = header(c, "01 · Análise audiovisual")
    if not c.bundle["evidence"]:
        return out + nodata(c, "01", "a referência não tem análise corrente.")
    dur = c.bundle.get("duration_s")
    out += f"Duração medida: **{seconds(dur)}**. Blocos por candidatos a cena (medidos): **{len(segs)}**.\n\n## Sequência\n\n"
    out += table(["#", "início", "fim", "duração", "visual (observado)", "fala", "técnicas"],
                 [[s["index"], seconds(s["start"]), seconds(s["end"]), seconds(s["duration"]),
                   "; ".join(f"{q(v['claim'], 80)} {c.cite([v['id']])}" for v in s["visual"]) or "—",
                   "; ".join(f"“{q(v['claim'], 80)}” {c.cite([v['id']])}" for v in s["speech"]) or "—",
                   ", ".join(f"{t['technique']} ({t['level']})" for t in s["techniques"]) or "—"] for s in segs])
    out += "\nTransições: os limites entre blocos são **candidatos a mudança de cena medidos**; o tipo de transição (corte, wipe, efeito) **não é determinado** por quadros.\n"
    for dom in ("conteudo", "linguagem_audiovisual"):
        gs = [g for g in c.live if g["domain"] == dom and not g["key"].startswith(("cena:",))]
        out += f"\n## {DOMAIN_LABEL[dom]}\n\n" + glist(c, gs)
    return out


def s02(c: _Ctx, rows) -> str:
    out = header(c, "02 · Engenharia reversa")
    if not rows:
        return out + nodata(c, "02", "sem técnicas ou ferramentas identificadas nas evidências.")
    out += "Como o vídeo PODE ter sido feito. Só o que está marcado **observada**/**comprovada** é fato; o restante é hipótese ou informação ausente.\n\n"
    out += table(["classe", "item", "estado", "detalhe", "evidências"], [[CLASS_PT[r["classification"]], q(r["item"], 80), STATE_PT.get(r["state"] or "", "—"), q(r["detail"], 400), c.cite(r["evidence_ids"])] for r in rows])
    return out


def s03(c: _Ctx, rows) -> str:
    out = header(c, "03 · Ferramentas e técnicas")
    tools = [r for r in rows if r["classification"].startswith("ferramenta")]
    techs = [r for r in rows if r["classification"] == "tecnica_observada"]
    if not tools and not techs:
        return out + nodata(c, "03", "nenhuma ferramenta ou técnica identificada.")
    out += "## Ferramentas\n\n" + table(["ferramenta", "classe", "estado", "evidências"], [[q(r["item"], 80), CLASS_PT[r["classification"]], STATE_PT.get(r["state"] or "", "—"), c.cite(r["evidence_ids"])] for r in tools])
    out += "\n## Técnicas\n\n" + table(["técnica", "o que as evidências provam", "estado", "evidências"], [[q(r["item"], 80), q(r["detail"], 300), STATE_PT.get(r["state"] or "", "—"), c.cite(r["evidence_ids"])] for r in techs])
    tk = c.bundle["facets"].get("transferable") or []
    if tk:
        out += "\n## Conhecimento transferível (classificador)\n\n" + "\n".join(f"- {q(json.dumps(x, ensure_ascii=False), 300)}" for x in tk[:10]) + "\n"
    return out


def s_profile(c: _Ctx, pid: str, props: List[Dict[str, Any]], title: str) -> str:
    out = header(c, title)
    if pid not in c.profiles:
        return out + nodata(c, title[:2], f"perfil '{pid}' não foi selecionado nesta investigação.")
    p = c.profiles[pid]
    out += f"Perfil **{p['name']}** v{p['version']} (`{p['hash']}`). Tudo abaixo é **PROPOSTA** original, derivada de princípios da referência; não é observação.\n\n"
    if not props:
        return out + nodata(c, title[:2], "sem análise suficiente para adaptar.")
    for pr in props:
        out += f"## {pr['conceito_criativo'].split('.')[0]} — `{pr['proposal_id']}`\n\n"
        out += table(["campo", "proposta"], [["Objetivo comercial", q(pr["objetivo_comercial"], 400)], ["Público-alvo", q(pr["publico_alvo"], 300)], ["Conceito criativo", q(pr["conceito_criativo"], 400)],
                                             ["Mensagem central", q(pr["mensagem_central"], 300)], ["Estrutura narrativa", " → ".join(pr["estrutura_narrativa"])], ["Direção de arte", q(pr["direcao_de_arte"], 500)],
                                             ["Linguagem de câmera", q(pr["linguagem_de_camera"], 300)], ["Estratégia de edição", q(pr["estrategia_de_edicao"], 300)],
                                             ["Ferramentas indicadas", ", ".join(pr["ferramentas_indicadas"])], ["Resultado esperado", q(pr["resultado_esperado"], 300)],
                                             ["Medição de qualidade", "; ".join(pr["medicao_de_qualidade"])], ["Oportunidade comercial", q(pr["oportunidade_comercial"], 400)],
                                             ["Complexidade", pr["complexidade"]]])
        out += "\n**Princípios emprestados da referência** (com base verificável):\n\n" + ("\n".join(f"- {x['principle']}: {x['mechanism']} — base: {', '.join(x['basis_keys'][:4])} ({', '.join(x['basis_states'])})" for x in pr["principios_aplicados"]) or "- nenhum com base suficiente") + "\n"
        if pr["principios_do_angulo_sem_base_na_referencia"]:
            out += "\nPrincípios do ângulo SEM base na referência (decisão criativa nova): " + ", ".join(pr["principios_do_angulo_sem_base_na_referencia"]) + ".\n"
        out += "\n**Riscos e restrições:** " + "; ".join(pr["riscos_e_restricoes"]) + "\n\n"
    return out


def s06(c: _Ctx, kits: Dict[str, Dict[str, Any]]) -> str:
    out = header(c, "06 · Roteiro original")
    if not kits:
        return out + nodata(c, "06", "sem proposta de adaptação.")
    out += "**PROPOSTA** — nenhuma cena abaixo foi observada na referência. Estrutura gerada de forma determinística; o texto falado deve ser escrito pelo roteirista (ou por um agente criativo, no futuro).\n\n"
    for pid, k in kits.items():
        out += f"## Proposta `{pid}` (ritmo: {k['pacing_source']}, duração-alvo {k['total_duration_s']}s)\n\n### Roteiro\n\n"
        out += table(["bloco", "duração", "intenção", "texto"], [[b["beat"], f"{b['duration_s']}s", q(b["intent"], 200), q(b["texto"], 100)] for b in k["roteiro"]])
        out += "\n### Storyboard textual\n\n" + "\n".join(f"{i}. {q(s, 400)}" for i, s in enumerate(k["storyboard_textual"], 1)) + "\n\n### Shot list\n\n"
        out += table(["shot", "bloco", "início", "dur.", "câmera", "ação", "texto na tela"], [[s["shot_id"], s["beat"], f"{s['start_s']}s", f"{s['duration_s']}s", q(s["camera"], 120), q(s["action"], 120), q(s["on_screen_text"], 40) or "—"] for s in k["shot_list"]])
        out += f"\nArquivos estruturados: `estruturados/shot_list_{pid}.csv` e `.json`.\n\n"
    return out


def s07(c: _Ctx, plan: Dict[str, Any], kits) -> str:
    out = header(c, "07 · Plano de produção")
    if not c.bundle["evidence"]:
        return out + nodata(c, "07", "sem evidências para planejar a reprodução.")
    out += "## A. Plano de reprodução técnica (baseado nas evidências)\n\n"
    for k, v in plan.items():
        title = k.split("_", 1)[1].replace("_", " ").capitalize()
        out += f"### {k.split('_')[0]}. {title}\n\n"
        if isinstance(v, str):
            out += q(v, 500) + "\n\n"
        elif isinstance(v, dict) and "itens" in v:
            out += f"_{v['fonte']}_\n\n" + "\n".join(f"- {q(x, 200)}" for x in v["itens"]) + "\n\n"
        elif isinstance(v, dict):
            out += "\n".join(f"- {kk}: {q(json.dumps(vv, ensure_ascii=False), 300)}" for kk, vv in v.items()) + "\n\n"
        else:
            lines = []
            for x in v:
                if isinstance(x, dict) and "phase" in x:
                    lines.append(f"- **{x['phase']}**: " + " | ".join(q(i, 200) for i in x["items"]))
                elif isinstance(x, dict) and "text" in x:
                    lines.append(f"- ({x['source']}) {q(x['text'], 300)} {c.cite(x.get('evidence_ids', []))}")
                elif isinstance(x, dict):
                    lines.append(f"- {q(json.dumps(x, ensure_ascii=False), 300)}")
                else:
                    lines.append(f"- {q(x, 300)}")
            out += "\n".join(lines) + "\n\n"
    out += "## B. Plano de produção do vídeo original (PROPOSTA)\n\n"
    if not kits:
        return out + nodata(c, "07B", "sem proposta de adaptação.")
    for pid, k in kits.items():
        out += f"### `{pid}`\n\n" + "\n".join(f"- **{f['fase']}**: " + "; ".join(f["tarefas"]) for f in k["plano_de_producao"]) + "\n\n"
        out += "Assets: " + ", ".join(a["asset_ref"] for a in k["assets"]) + "\n\nPrompts sugeridos (a testar; não são os do autor): ver `estruturados/prompts_" + pid + ".json`.\n\nChecklist de entrega:\n\n" + "\n".join(f"- [ ] {q(x, 300)}" for x in k["checklist_entrega"]) + "\n\n"
    return out


def s08(c: _Ctx, questions) -> str:
    out = header(c, "08 · Perguntas em aberto")
    if not questions:
        return out + "_Nenhuma pergunta em aberto registrada._\n"
    by: Dict[str, List[Dict[str, Any]]] = {}
    for x in questions:
        by.setdefault(x["kind"], []).append(x)
    label = {"contradicao": "Contradições", "hipotese_aberta": "Hipóteses abertas", "movimento_nao_comprovado": "Movimento não comprovado", "nao_verificado": "Dito, mas não visto",
             "pergunta_do_especialista": "Perguntas dos especialistas", "provedor_indisponivel": "Provedores indisponíveis", "aprovacao_pendente": "Aprovações pendentes",
             "tarefa_incompleta": "Tarefas incompletas", "tarefa_nao_executada": "Tarefas não executadas", "dados_ausentes": "Dados ausentes", "revisao_humana": "Revisão humana"}
    for kind in sorted(by):
        out += f"## {label.get(kind, kind)}\n\n" + "\n".join(f"- {q(x['text'], 500)}" for x in by[kind]) + "\n\n"
    return out


def s00(c: _Ctx, segs, rows, props, questions) -> str:
    out = header(c, "00 · Resumo executivo")
    b = c.bundle
    if not b["evidence"]:
        return out + nodata(c, "00", "a referência não possui análise corrente; rode o pipeline antes de investigar.")
    cats = [f"{x['category']} ({x['support']})" for x in b["facets"].get("categories", []) if x["support"] not in ("insufficient",)]
    speech = [e for e in b["evidence"] if e["status"] == "transcript_claim"][:3]
    techs = [r for r in rows if r["classification"] == "tecnica_observada"]
    proven = [r["item"] for r in rows if r["classification"] == "ferramenta_comprovada"]
    mentioned = [r["item"] for r in rows if r["classification"] == "ferramenta_mencionada"]
    states: Dict[str, int] = {}
    for g in c.live:
        states[g["state"]] = states.get(g["state"], 0) + 1
    out += "## 1. O que acontece no vídeo?\n\n"
    out += f"Duração **{seconds(b.get('duration_s'))}**, {len(segs)} bloco(s). Categorias com suporte: {', '.join(cats) or 'nenhuma'}.\n"
    out += ("\nPrimeiras falas: " + " / ".join(f"“{q(e['claim'], 90)}” {c.cite([e['id']])}" for e in speech) + "\n") if speech else "\n_Sem transcrição disponível._\n"
    out += f"\nDetalhe: `01_ANALISE_AUDIOVISUAL.md`.\n\n## 2. Como foi produzido e o que é comprovável?\n\n"
    out += f"{len(techs)} técnica(s) observada(s) no quadro; afirmações: " + (", ".join(f"{n} {STATE_PT[k]}" for k, n in sorted(states.items())) or "nenhuma") + ". "
    out += "Movimento, duração e parâmetros **não** são comprovados por quadros estáticos. Detalhe: `02_ENGENHARIA_REVERSA.md`.\n\n## 3. O que posso aproveitar?\n\n"
    out += f"Ferramentas comprovadas: {', '.join(proven) or 'nenhuma'}; apenas mencionadas: {', '.join(mentioned) or 'nenhuma'}; técnicas: {', '.join(r['item'] for r in techs) or 'nenhuma'}. Detalhe: `03_FERRAMENTAS_E_TECNICAS.md`.\n\n"
    out += "## 4. Como criar um vídeo original com qualidade semelhante?\n\n"
    for pid, ps in props.items():
        for pr in ps[:1]:
            out += f"- **{c.profiles[pid]['name']}**: {q(pr['conceito_criativo'], 250)} Mensagem: “{q(pr['mensagem_central'], 150)}” (`{PROFILE_FILE.get(pid, '09_APLICACAO_' + pid.upper() + '.md')}`, `06_ROTEIRO_ORIGINAL.md`, `07_PLANO_DE_PRODUCAO.md`)\n"
    out += "\n## 5. Como virar produto, serviço ou automação?\n\n"
    for pid, ps in props.items():
        for pr in ps[:2]:
            out += f"- {c.profiles[pid]['name']} / {pr['angle_id']}: {q(pr['oportunidade_comercial'], 300)} (complexidade {pr['complexidade']})\n"
    out += f"\n## Estado da investigação\n\n" + table(["especialista", "perfil de trabalho", "estado", "tentativas"], [[t["specialist"], SPECIALISTS[t["specialist"]]["profile"], t["state"], t["attempts"]] for t in c.tasks])
    out += f"\n## Principais incertezas ({len(questions)} no total)\n\n" + "\n".join(f"- {q(x['text'], 250)}" for x in questions[:6]) + "\n\nLista completa: `08_PERGUNTAS_EM_ABERTO.md`.\n"
    return out


def readme(c: _Ctx, files: List[str]) -> str:
    banner = f"> ⚠ **{c.banner}**\n\n" if c.banner else ""
    return (f"# Dossiê de inteligência criativa — `{c.inv['reference_id']}`\n\n{banner}Investigação `{c.inv['investigation_id']}` (versão {c.inv['seq']}), estado **{c.inv['state']}**. Versão do dossiê e hashes: `manifest.json`.\n\n"
            "## Como navegar\n\n" + "\n".join(f"- `{f}`" for f in files) + "\n\n## Como ler os resultados\n\n"
            "- **Evidências**: `[ev:xxxxxxxx]` aponta para o índice de evidências do `manifest.json` (status, tempo, texto).\n"
            "- **Estados de verificação**: " + "; ".join(f"**{STATE_PT[k]}** = {v}" for k, v in VERIFICATION.items()) + ".\n"
            "- **Proposta × análise**: roteiro, adaptações e plano do vídeo original são PROPOSTAS (`origin: proposta`); nunca são observações da referência.\n"
            "- **Revisão humana**: decisões de pessoas ficam no banco e aparecem aqui; o motor não as altera nem as sobrescreve.\n"
            "- Seção sem dados diz explicitamente que não há dados; nada é inventado para preenchê-la.\n")


# ------------------------------------------------------------------------------------------------ montagem
def render_all(c: _Ctx) -> Dict[str, str]:
    b = c.bundle
    segs = AN.segments(b) if b["evidence"] else []
    rows = AN.production_rows(b, c.live)
    plan = AN.reproduction_plan(b, c.live, rows)
    props = {pid: adapt(b, c.live, p) for pid, p in c.profiles.items()} if b["evidence"] else {}
    kits = {}
    for pid, ps in props.items():
        for pr in ps:
            kits[pr["proposal_id"]] = build_kit(pr, b, segs, c.profiles[pid])
    first_kits = {pr["proposal_id"]: kits[pr["proposal_id"]] for ps in props.values() for pr in ps[:1]}
    tq = []
    for t in c.tasks:
        if t["result_json"]:
            tq += json.loads(t["result_json"]).get("questions", [])
    questions = AN.open_questions(c.inv, c.groups, c.tasks, tq)
    files: Dict[str, str] = {
        "01_ANALISE_AUDIOVISUAL.md": s01(c, segs), "02_ENGENHARIA_REVERSA.md": s02(c, rows), "03_FERRAMENTAS_E_TECNICAS.md": s03(c, rows),
    }
    for pid in sorted(c.profiles):
        name = PROFILE_FILE.get(pid, f"09_APLICACAO_{pid.upper()}.md")
        files[name] = s_profile(c, pid, props.get(pid, []), f"{name[:2]} · Aplicação — {c.profiles[pid]['name']}")
    for pid, fname in PROFILE_FILE.items():
        if fname not in files:
            files[fname] = s_profile(c, pid, [], f"{fname[:2]} · Aplicação — {pid}")
    files["06_ROTEIRO_ORIGINAL.md"] = s06(c, first_kits)
    files["07_PLANO_DE_PRODUCAO.md"] = s07(c, plan, first_kits)
    files["08_PERGUNTAS_EM_ABERTO.md"] = s08(c, questions)
    files["00_RESUMO_EXECUTIVO.md"] = s00(c, segs, rows, props, questions)
    for pid, k in kits.items():
        files[f"estruturados/shot_list_{pid}.csv"] = shot_list_csv(k["shot_list"])
        files[f"estruturados/shot_list_{pid}.json"] = json.dumps(k["shot_list"], ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        files[f"estruturados/prompts_{pid}.json"] = json.dumps(k["prompts_sugeridos"], ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        files[f"estruturados/kit_{pid}.json"] = json.dumps(k, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    files["estruturados/plano_reproducao.json"] = json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    files["estruturados/afirmacoes.json"] = json.dumps(c.groups, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    files["estruturados/perguntas_em_aberto.json"] = json.dumps(questions, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    files["README.md"] = readme(c, sorted(k for k in files if k.endswith(".md")))
    return files


def _atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_text(encoding="utf-8") == text:
        return
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".ce_tmp_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def write_dossier(ce, inv_id: str, out_dir: Path) -> Dict[str, Any]:
    c = _Ctx(ce, inv_id)
    files = render_all(c)
    chash = digest({k: hashlib.sha256(v.encode("utf-8")).hexdigest() for k, v in sorted(files.items())}, n=32)
    row = ce.conn.execute("SELECT version FROM ce_dossiers WHERE investigation_id = ? AND content_hash = ?", (inv_id, chash)).fetchone()
    created = row is None
    if created:
        version = (ce.conn.execute("SELECT COALESCE(MAX(version), 0) v FROM ce_dossiers WHERE investigation_id = ?", (inv_id,)).fetchone()["v"]) + 1
    else:
        version = row["version"]
    ref_dir = Path(out_dir) / c.bundle["reference_id"]
    cur = ref_dir / "manifest.json"
    if cur.exists():
        try:
            old = json.loads(cur.read_text(encoding="utf-8"))
        except ValueError:
            old = {}
        if old.get("content_hash") != chash:  # arquiva a versão anterior; nada é perdido
            arch = ref_dir / "_versoes" / f"inv{old.get('seq', 0)}_v{old.get('dossier_version', 0)}"
            arch.mkdir(parents=True, exist_ok=True)
            for item in list(ref_dir.iterdir()):
                if item.name != "_versoes":
                    shutil.move(str(item), str(arch / item.name))
    manifest = {"schema_version": SCHEMA_MANIFEST, "reference_id": c.bundle["reference_id"], "investigation_id": inv_id, "seq": c.inv["seq"], "state": c.inv["state"],
                "dossier_version": version, "content_hash": chash, "input_hash": c.inv["input_hash"], "generator": GENERATOR_VERSION, "banner": c.banner or None,
                "versions": c.inv["versions"], "sections_without_data": sorted(set(c.empty)),
                "files": [{"path": k, "sha256": hashlib.sha256(v.encode("utf-8")).hexdigest(), "bytes": len(v.encode("utf-8"))} for k, v in sorted(files.items())],
                "evidence_index": {i: {"status": c.ev[i]["status"], "t_start": c.ev[i]["t_start"], "source": c.ev[i]["source_type"], "claim": c.ev[i]["claim"]} for i in sorted(c.cited)},
                "claims_by_state": {s: sum(1 for g in c.groups if g["state"] == s) for s in sorted({g["state"] for g in c.groups})},
                "human_reviews": [{"key": k, "decision": r["decision"], "reviewer": r["reviewer"]} for k, r in sorted(c.reviews.items())]}
    for k, v in files.items():
        _atomic(ref_dir / k, v)
    _atomic(ref_dir / "manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    if created:
        now = ce.clock.now()
        with tx(ce.conn) as cn:
            cn.execute("INSERT OR IGNORE INTO ce_dossiers(dossier_id, investigation_id, version, content_hash, path, manifest_json, created_at) VALUES (?,?,?,?,?,?,?)",
                       (f"dos_{digest(inv_id, chash)}", inv_id, version, chash, str(ref_dir), canonical_json(manifest), now))
            EV.emit(cn, "dossier.generated", inv_id, {"version": version, "content_hash": chash, "sections_without_data": manifest["sections_without_data"]}, now, f"{inv_id}|{chash}")
    return {"investigation_id": inv_id, "dossier_version": version, "created": created, "path": str(ref_dir), "content_hash": chash, "files": sorted(files), "sections_without_data": manifest["sections_without_data"]}

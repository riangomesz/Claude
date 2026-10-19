"""Camadas DETERMINÍSTICAS sobre o pacote de evidências e os grupos reconciliados: decomposição, hipóteses de produção,
plano de reprodução e perguntas em aberto. Não chamam modelo. Separam sempre: observado, dito, sugerido e ausente."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from .contracts import MOTION_TECHNIQUES, slug_key
from .evidence import ev_index
from .knowledge_base import DEFAULT_PRODUCTION, PRODUCTION

PHASE = {"b_roll": 1, "jump_cut": 1, "corte": 1, "split_screen": 1, "reenquadramento": 1, "sobreposicao": 2, "mascara": 2, "composicao_cinematografica": 2,
         "movimento_de_camera": 2, "legenda_sobreposta": 3, "legenda_animada": 3, "tipografia": 3, "tipografia_cinetica": 3, "punch_in": 4, "transicao": 4}
PHASE_NAME = {0: "Preparo (roteiro, material, ferramentas)", 1: "Montagem (planos e cortes)", 2: "Camadas e composição", 3: "Texto e legendas",
              4: "Ênfase e movimento", 5: "Acabamento e exportação"}


def segments(bundle: Dict[str, Any]) -> List[Dict[str, Any]]:
    ev = bundle["evidence"]
    scenes = sorted((e for e in ev if e["source_type"] == "scene_detection" and e["t_start"] is not None), key=lambda e: e["t_start"])
    dur = bundle.get("duration_s") or max([e["t_start"] for e in ev if e["t_start"] is not None] + [0.0])
    cuts = [s for s in scenes if 0 < s["t_start"] < (dur or 1e9)]
    bounds = [None] + cuts
    out = []
    for i, b in enumerate(bounds):
        start = 0.0 if b is None else b["t_start"]
        end = cuts[i]["t_start"] if i < len(cuts) else dur
        inside = [e for e in ev if e["t_start"] is not None and start <= e["t_start"] < (end if end is not None else 1e9) and (i == len(cuts) or True)]
        techs = [{"technique": t["technique"], "level": t.get("level"), "evidence_ids": t["evidence_ids"]} for t in bundle["facets"].get("techniques", [])
                 if any(start <= (ts[0] or 0) < (end if end is not None else 1e9) for ts in t.get("timestamps", []))]
        out.append({"index": i + 1, "start": start, "end": end, "duration": None if end is None else round(end - start, 3),
                    "boundary": None if b is None else {"evidence_id": b["id"], "note": "candidato a mudança de cena (medido); tipo de transição NÃO determinado"},
                    "visual": [{"id": e["id"], "tag": e["tag"], "claim": e["claim"], "status": e["status"]} for e in inside if e["source_type"] == "agent_observation"],
                    "speech": [{"id": e["id"], "t": e["t_start"], "claim": e["claim"]} for e in inside if e["status"] == "transcript_claim"],
                    "techniques": techs})
    return out


def production_rows(bundle: Dict[str, Any], groups: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    gstate = {g["key"]: g for g in groups}
    rows: List[Dict[str, Any]] = []
    for t in bundle["facets"].get("techniques", []):
        tech = t["technique"]
        p = PRODUCTION.get(tech, DEFAULT_PRODUCTION)
        g = gstate.get(f"tecnica:{tech}", {})
        rows.append({"classification": "tecnica_observada", "item": tech, "state": g.get("state"), "evidence_ids": t["evidence_ids"],
                     "detail": f"nível '{t.get('level')}': {t.get('proves')}. Não prova: {t.get('does_not_prove')}."})
        rows.append({"classification": "hipotese", "item": tech, "state": "hypothesis", "evidence_ids": t["evidence_ids"],
                     "detail": f"Hipótese de produção: {p['hypothesis']}. Operações prováveis: {'; '.join(p['operations'])}." + (" Movimento NÃO comprovado por quadros." if tech in MOTION_TECHNIQUES and t.get("level") != "temporal_sequence" else "")})
        if p["tools"]:
            rows.append({"classification": "ferramenta_sugerida", "item": ", ".join(p["tools"]), "state": "hypothesis", "evidence_ids": [],
                         "detail": "Sugestão genérica de categoria de ferramenta; software específico NÃO confirmado."})
        rows.append({"classification": "informacao_ausente", "item": tech, "state": None, "evidence_ids": [], "detail": "Não consta nas evidências: " + "; ".join(p["missing"]) + "."})
    for t in bundle["facets"].get("tools", []):
        proven = t.get("status") in ("visually_identified",) or any(x["name"] == t["name"] for x in bundle["facets"].get("tools_visual", []))
        g = gstate.get(f"ferramenta:{slug_key(t['name'])}", {})
        rows.append({"classification": "ferramenta_comprovada" if proven else "ferramenta_mencionada", "item": t["name"], "state": g.get("state"),
                     "evidence_ids": t["evidence_ids"], "detail": "nome ou interface legível no vídeo" if proven else f"citada em fala/legenda ({t.get('status')}); uso no vídeo NÃO demonstrado"})
    return rows


def reproduction_plan(bundle: Dict[str, Any], groups: List[Dict[str, Any]], rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    techs = [t["technique"] for t in bundle["facets"].get("techniques", [])]
    prod = [PRODUCTION.get(t, DEFAULT_PRODUCTION) for t in techs]
    ev = ev_index(bundle)
    steps = [{"source": "dito pelo autor", "text": g["summary"].split("“", 1)[-1].rstrip("”) ").split("” (")[0], "key": g["key"], "evidence_ids": g["evidence_ids"]}
             for g in groups if g["key"].startswith("passo:") and g.get("human_state") != "rejected"]
    by_phase: Dict[int, List[Dict[str, Any]]] = {}
    for t, p in zip(techs, prod):
        by_phase.setdefault(PHASE.get(t, 2), []).append({"technique": t, "operations": p["operations"]})
    order = [{"phase": PHASE_NAME[0], "items": ["definir roteiro e mensagem", "reunir material e ferramentas listados"]}]
    order += [{"phase": PHASE_NAME[k], "items": [f"{x['technique']}: " + "; ".join(x["operations"]) for x in by_phase[k]]} for k in sorted(by_phase)]
    order.append({"phase": PHASE_NAME[5], "items": ["revisar áudio e legibilidade", "exportar no formato de destino"]})
    probe = [e for e in bundle["evidence"] if e["status"] == "measured_signal" and e["tag"] == "probe"]
    uniq = lambda xs: list(dict.fromkeys(x for p in xs for x in p))  # noqa: E731
    tools_seen = [r["item"] for r in rows if r["classification"] in ("ferramenta_comprovada", "ferramenta_mencionada")]
    return {
        "1_resultado_pretendido": "Reproduzir os princípios observados: " + (", ".join(techs) or "nenhuma técnica observada") + ". Reprodução de PRINCÍPIOS, não cópia do vídeo.",
        "2_materiais_necessarios": ["roteiro e texto de tela", "material bruto (gravação de tela, vídeo ou imagens geradas)", "áudio (fala e/ou trilha)"] + [f"acesso a: {t}" for t in tools_seen],
        "3_softwares_possiveis": {"comprovados_ou_mencionados": tools_seen, "sugeridos_por_categoria": uniq(p["tools"] for p in prod), "nota": "sugestões por categoria; software específico NÃO confirmado"},
        "4_etapas_de_producao": steps + [{"source": "inferido das técnicas", "text": f"{k['phase']}: " + " | ".join(k["items"])} for k in order],
        "5_configuracoes_conhecidas": [{"evidence_id": e["id"], "value": e["claim"], "status": "medido"} for e in probe] or ["nenhuma configuração medida disponível"],
        "6_parametros_que_precisam_de_teste": sorted(set(uniq(p["missing"] for p in prod))) or ["indeterminado: sem técnicas observadas"],
        "7_ordem_de_execucao": order,
        "8_criterios_de_qualidade": sorted(set(uniq(p["quality"] for p in prod))) + ["resultado comparado lado a lado com a referência apenas como estudo, nunca publicado como cópia"],
        "9_erros_comuns": {"fonte": "conhecimento geral de produção, NÃO observado neste vídeo", "itens": sorted(set(uniq(p["errors"] for p in prod)))},
        "10_verificacoes_finais": ["texto legível em tela de celular", "áudio sem cortes bruscos", "formato 9:16 e duração de destino", "itens 'não verificados' da engenharia reversa testados ou marcados como hipótese",
                                   "revisão humana das hipóteses aceitas"],
    }


def open_questions(inv: Dict[str, Any], groups: List[Dict[str, Any]], tasks: List[Dict[str, Any]], task_questions: List[str]) -> List[Dict[str, Any]]:
    q: List[Dict[str, Any]] = []
    if not inv["bundle"]["evidence"]:
        q.append({"kind": "dados_ausentes", "text": "A referência não tem análise corrente: nenhuma conclusão pôde ser produzida.", "keys": []})
    for g in groups:
        if g.get("human_state") == "rejected":
            continue
        if g["state"] == "contradicted":
            q.append({"kind": "contradicao", "text": f"Especialistas divergem em '{g['key']}': {g['summary']}", "keys": [g["key"]]})
        elif g["state"] == "supported_static":
            q.append({"kind": "movimento_nao_comprovado", "text": f"'{g['key']}' aparece no quadro, mas movimento/duração não foram comprovados.", "keys": [g["key"]]})
        elif g["state"] in ("claimed", "unverified") and g["kind"] in ("tool", "technique", "process"):
            q.append({"kind": "nao_verificado", "text": f"'{g['key']}' foi dito/escrito, mas não visto no vídeo.", "keys": [g["key"]]})
        elif g["human_state"] == "needs_evidence":
            q.append({"kind": "revisao_humana", "text": f"Revisor pediu mais evidência para '{g['key']}'.", "keys": [g["key"]]})
        elif g["state"] == "hypothesis" and g["kind"] in ("hypothesis",) and g["human_state"] is None and g["key"].startswith(("producao:", "visual:")):
            q.append({"kind": "hipotese_aberta", "text": f"Hipótese sem decisão humana: {g['summary']}", "keys": [g["key"]]})
    for t in tasks:
        if t["state"] == "blocked_provider":
            q.append({"kind": "provedor_indisponivel", "text": f"Especialista '{t['specialist']}' sem provedor disponível; análise pendente.", "keys": []})
        elif t["state"] == "awaiting_approval":
            q.append({"kind": "aprovacao_pendente", "text": f"Especialista '{t['specialist']}' aguarda aprovação para uso de modelo pago.", "keys": []})
        elif t["state"] in ("failed", "blocked_dependency"):
            q.append({"kind": "tarefa_incompleta", "text": f"Tarefa '{t['specialist']}' não concluída ({t['state']}): {t.get('error') or 'sem detalhe'}.", "keys": []})
        elif t["state"] == "skipped":
            q.append({"kind": "tarefa_nao_executada", "text": f"Especialista '{t['specialist']}' não foi executado: {t['reason']}", "keys": []})
    for text in sorted(set(task_questions)):
        q.append({"kind": "pergunta_do_especialista", "text": text, "keys": []})
    return q

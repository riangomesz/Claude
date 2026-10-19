"""Kit criativo determinístico a partir de UMA proposta de adaptação: briefing, roteiro, storyboard textual, shot list,
timeline, assets, prompts, plano de produção e checklist. Tudo é PROPOSTA (`origin: proposta`): nenhuma cena aqui é observação
da referência. O ritmo só é tomado da referência quando há cortes medidos (`pacing_source: observed`)."""
from __future__ import annotations

import csv
import io
from typing import Any, Dict, List

DEFAULT_RATIOS = {2: [0.4, 0.6], 3: [0.2, 0.55, 0.25], 4: [0.15, 0.45, 0.25, 0.15], 5: [0.12, 0.2, 0.33, 0.22, 0.13]}
BEAT_GUIDE = {"gancho": "abrir com a promessa em uma frase e um elemento visual forte", "gancho visual": "abrir com o plano mais impactante do resultado",
              "processo": "mostrar as etapas, uma por vez, legíveis em tela de celular", "resultado": "mostrar o resultado final sem texto sobreposto",
              "chamada": "chamada única e específica", "problema": "mostrar a tarefa repetitiva ou a dor", "fluxo": "mostrar o fluxo automatizado funcionando",
              "desenvolvimento": "desenvolver a ideia com variação de plano", "clímax": "ponto de maior impacto visual", "assinatura": "assinatura discreta da marca",
              "detalhe de material": "close na textura e no acabamento", "contexto de uso": "mostrar a peça no ambiente", "projeto": "mostrar o desenho/projeto",
              "fabricação": "mostrar etapas reais de fabricação"}


def _durations(structure: List[str], total: float, segs: List[Dict[str, Any]]):
    durs = [s["duration"] for s in segs if s.get("duration")]
    k = len(structure)
    if len(durs) >= 3:  # ritmo observado: reamostra as durações medidas nos k blocos
        chunk = [sum(durs[i * len(durs) // k:(i + 1) * len(durs) // k] or [durs[-1]]) for i in range(k)]
        tot = sum(chunk) or 1.0
        return [round(total * c / tot, 1) for c in chunk], "observed"
    r = DEFAULT_RATIOS.get(k) or [1 / k] * k
    return [round(total * x, 1) for x in r], "default"


def build_kit(proposal: Dict[str, Any], bundle: Dict[str, Any], segs: List[Dict[str, Any]], profile: Dict[str, Any]) -> Dict[str, Any]:
    total = float(min(60.0, max(15.0, bundle.get("duration_s") or 30.0)))
    structure = proposal["estrutura_narrativa"]
    durs, source = _durations(structure, total, segs)
    pid = proposal["proposal_id"]
    t, beats, shots, story, timeline = 0.0, [], [], [], []
    for i, (beat, d) in enumerate(zip(structure, durs), 1):
        guide = BEAT_GUIDE.get(beat, "bloco definido pelo roteirista")
        beats.append({"beat": beat, "duration_s": d, "intent": guide, "texto": "[a definir pelo roteirista com a mensagem central]", "message_seed": proposal["mensagem_central"] if i in (1, len(structure)) else None})
        shots.append({"shot_id": f"S{i:02d}", "beat": beat, "start_s": round(t, 1), "duration_s": d, "framing": "a definir conforme a direção de arte", "camera": proposal["linguagem_de_camera"],
                      "action": guide, "on_screen_text": "[a definir]" if proposal["principios_aplicados"] and any(p["principle"] == "texto_na_tela" for p in proposal["principios_aplicados"]) else "", "audio": "[voz/música a definir]",
                      "asset_ref": f"asset_{i:02d}", "origin": "proposta"})
        story.append(f"Quadro {i} ({beat}, {d}s): {guide}. Câmera: {proposal['linguagem_de_camera']} [PROPOSTA]")
        timeline.append({"track": "V1", "in_s": round(t, 1), "out_s": round(t + d, 1), "clip": f"asset_{i:02d}", "edit": proposal["estrategia_de_edicao"]})
        t += d
    vis = profile.get("visual_language", [])
    prompts = [{"shot_id": s["shot_id"], "type": "imagem", "prompt": f"{', '.join(vis)}; {s['action']}; vertical 9:16; sem texto embutido",
                "note": "sugestão a testar; não é o prompt do autor da referência"} for s in shots]
    prompts += [{"shot_id": s["shot_id"], "type": "vídeo", "prompt": f"{s['camera']}; {', '.join(vis)}; {s['action']}; {s['duration_s']}s", "note": "sugestão a testar"} for s in shots]
    return {
        "origin": "proposta", "proposal_id": pid, "pacing_source": source, "total_duration_s": round(sum(durs), 1),
        "briefing": {"objetivo": proposal["objetivo_comercial"], "publico": proposal["publico_alvo"], "conceito": proposal["conceito_criativo"], "mensagem": proposal["mensagem_central"],
                     "direcao_de_arte": proposal["direcao_de_arte"], "restricoes": proposal["riscos_e_restricoes"], "medicao": proposal["medicao_de_qualidade"]},
        "roteiro": beats, "storyboard_textual": story, "shot_list": shots, "timeline_edicao": timeline,
        "assets": [{"asset_ref": s["asset_ref"], "needed_for": s["shot_id"], "kind": "plano de vídeo ou imagem", "status": "a produzir"} for s in shots] +
                  [{"asset_ref": "trilha", "needed_for": "todos", "kind": "música/voz", "status": "a definir (licença)"}],
        "prompts_sugeridos": prompts,
        "plano_de_producao": [{"fase": "Pré-produção", "tarefas": ["fechar roteiro e mensagem", "aprovar direção de arte", "listar assets"]},
                              {"fase": "Produção", "tarefas": ["produzir os planos da shot list", "gravar/gerar áudio"]},
                              {"fase": "Pós-produção", "tarefas": ["montar a timeline", "aplicar texto e ênfases", "etalonagem e mixagem", "exportar 9:16"]},
                              {"fase": "Entrega", "tarefas": ["revisão humana", "checklist final"]}],
        "checklist_entrega": ["mensagem central clara nos primeiros segundos", "texto legível em celular", "sem cópia de plano, texto ou identidade da referência",
                              "conteúdo gerado por IA identificado quando exigido", "restrições do perfil respeitadas: " + "; ".join(profile.get("constraints", [])), "aprovação humana registrada"],
    }


def shot_list_csv(shots: List[Dict[str, Any]]) -> str:
    cols = ["shot_id", "beat", "start_s", "duration_s", "framing", "camera", "action", "on_screen_text", "audio", "asset_ref", "origin"]
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(cols)
    for s in shots:  # neutraliza fórmulas de planilha (=, +, -, @)
        w.writerow([("'" + str(s[c])) if str(s[c])[:1] in ("=", "+", "-", "@") else s[c] for c in cols])
    return buf.getvalue()

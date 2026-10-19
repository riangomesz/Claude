"""Gera `ii_creative_engine_investigacao.workflow.json` (determinístico). Rode: python -X utf8 n8n/build_workflow.py

Fluxo: referência aprovada → abrir investigação → (sem evidência? para) → executar tarefas permitidas → status →
(pendências retomáveis? espera e repete até 3x) → gerar dossiê → aguardar curadoria humana. A LÓGICA DE DOMÍNIO FICA NO BACKEND:
os nós só chamam `POST /v1/<operação>` da API local `ii.ce.api.v1` (idempotente). Sem credenciais, sem chamadas externas, workflow inativo."""
import hashlib
import json
from pathlib import Path

OUT = Path(__file__).with_name("ii_creative_engine_investigacao.workflow.json")
nodes, conns = [], {}


def nid(name):
    return hashlib.sha1(name.encode()).hexdigest()[:8] + "-0000-4000-8000-" + hashlib.sha1(name[::-1].encode()).hexdigest()[:12]


def add(name, type_, version, params, x, y, **extra):
    nodes.append({"parameters": params, "id": nid(name), "name": name, "type": type_, "typeVersion": version, "position": [x, y], **extra})


def link(a, b, out=0):
    conns.setdefault(a, {"main": []})
    while len(conns[a]["main"]) <= out:
        conns[a]["main"].append([])
    conns[a]["main"][out].append({"node": b, "type": "main", "index": 0})


def http(name, op, body, x, y, **extra):
    add(name, "n8n-nodes-base.httpRequest", 4.2,
        {"method": "POST", "url": "={{ $('Configuração').first().json.base_url }}/v1/" + op, "sendBody": True, "specifyBody": "json", "jsonBody": "={{ " + body + " }}",
         "sendHeaders": True, "headerParameters": {"parameters": [{"name": "Content-Type", "value": "application/json"}]}, "options": {"timeout": 60000}},
        x, y, retryOnFail=True, maxTries=3, waitBetweenTries=2000, **extra)


add("Nota", "n8n-nodes-base.stickyNote", 1, {"width": 620, "height": 300, "content":
    "## Instagram Intelligence — investigação criativa (MS06)\n**INATIVO e SEM credenciais.** Chama só a API local do backend (`ii.ce.api.v1`, 127.0.0.1).\n"
    "A lógica fica no backend; este fluxo orquestra e é idempotente (repetir não duplica).\n\n"
    "**Humano decide:** aprovação de modelos pagos, revisão de hipóteses e aprovação do dossiê são feitas no painel/API por uma PESSOA. "
    "O backend recusa atores `n8n:`.\n\nNós desabilitados = ativação progressiva (Obsidian, eventos)."}, -220, -260)
add("Webhook: referência aprovada", "n8n-nodes-base.webhook", 2, {"httpMethod": "POST", "path": "ii-ce/referencia-aprovada", "responseMode": "responseNode", "options": {}}, 0, 0,
    webhookId=nid("webhook")[:36])
add("Teste manual", "n8n-nodes-base.manualTrigger", 1, {}, 0, 200)
add("Configuração", "n8n-nodes-base.set", 3.4, {"assignments": {"assignments": [
    {"id": "a1", "name": "base_url", "value": "http://127.0.0.1:8777", "type": "string"},
    {"id": "a2", "name": "max_rodadas", "value": 3, "type": "number"}]}, "options": {}}, 240, 100)
add("Normalizar entrada", "n8n-nodes-base.set", 3.4, {"assignments": {"assignments": [
    {"id": "b1", "name": "reference_id", "value": "={{ $json.body?.reference_id ?? $json.reference_id ?? 'ref_00000000000000000000' }}", "type": "string"},
    {"id": "b2", "name": "depth", "value": "={{ $json.body?.depth ?? 'standard' }}", "type": "string"}]}, "options": {}}, 480, 100)
http("Abrir investigação", "open_investigation", "{ reference_id: $json.reference_id, depth: $json.depth, limits: { max_calls: 4, max_usd: 0 }, requested_by: 'n8n:fluxo-investigacao' }", 720, 100)
add("Sem evidências?", "n8n-nodes-base.if", 2, {"conditions": {"options": {"caseSensitive": True, "typeValidation": "strict"}, "combinator": "and", "conditions": [
    {"id": "c1", "leftValue": "={{ $json.data.state }}", "rightValue": "blocked_no_evidence", "operator": {"type": "string", "operation": "equals"}}]}}, 960, 100)
http("Executar tarefas permitidas", "run_investigation", "{ investigation_id: $('Abrir investigação').item.json.data.investigation_id, max_tasks: 10, retry_blocked: $runIndex > 0 }", 1200, 200, onError="continueErrorOutput")
http("Consultar status", "get_status", "{ investigation_id: $('Abrir investigação').item.json.data.investigation_id }", 1440, 200)
add("Pendências retomáveis?", "n8n-nodes-base.if", 2, {"conditions": {"options": {"caseSensitive": True, "typeValidation": "loose"}, "combinator": "and", "conditions": [
    {"id": "d1", "leftValue": "={{ ['running','partial'].includes($json.data.state) && $runIndex < $('Configuração').first().json.max_rodadas }}", "rightValue": True, "operator": {"type": "boolean", "operation": "equals"}}]}}, 1680, 200)
add("Esperar antes de retomar", "n8n-nodes-base.wait", 1.1, {"amount": 60, "unit": "seconds"}, 1680, 420)
http("Gerar dossiê", "generate_dossier", "{ investigation_id: $('Abrir investigação').item.json.data.investigation_id }", 1920, 200, onError="continueErrorOutput")
http("Exportar para staging do Obsidian", "export_obsidian", "{ investigation_id: $('Abrir investigação').item.json.data.investigation_id }", 2160, 200, disabled=True)
add("Aguardando curadoria humana", "n8n-nodes-base.noOp", 1, {}, 2400, 200)
add("Responder status", "n8n-nodes-base.respondToWebhook", 1.1, {"respondWith": "json", "responseBody": "={{ { ok: true, investigation_id: $('Abrir investigação').item.json.data.investigation_id, awaiting_human: true } }}", "options": {}}, 2640, 200)
add("Responder: sem evidências", "n8n-nodes-base.respondToWebhook", 1.1, {"respondWith": "json", "responseBody": "={{ { ok: false, reason: 'blocked_no_evidence', investigation_id: $json.data.investigation_id } }}", "options": {}}, 1200, -40)
add("Registrar erro", "n8n-nodes-base.set", 3.4, {"assignments": {"assignments": [{"id": "e1", "name": "erro", "value": "={{ $json.error ?? 'falha na API local' }}", "type": "string"}]}, "options": {}}, 1680, 620)
add("Responder erro", "n8n-nodes-base.respondToWebhook", 1.1, {"respondWith": "json", "responseCode": 502, "responseBody": "={{ { ok: false, erro: $json.erro } }}", "options": {}}, 1920, 620)
# --- ramo opcional (desabilitado): consumir eventos do outbox
add("Agenda: eventos (desabilitado)", "n8n-nodes-base.scheduleTrigger", 1.2, {"rule": {"interval": [{"field": "minutes", "minutesInterval": 15}]}}, 0, 760, disabled=True)
http("Ler eventos", "poll_events", "{ consumer: 'n8n-ce', limit: 50 }", 480, 760, disabled=True)
http("Confirmar eventos", "ack_events", "{ consumer: 'n8n-ce', event_ids: $json.data.events.map(e => e.event_id) }", 720, 760, disabled=True)

for a, b in [("Webhook: referência aprovada", "Configuração"), ("Teste manual", "Configuração"), ("Configuração", "Normalizar entrada"), ("Normalizar entrada", "Abrir investigação"),
             ("Abrir investigação", "Sem evidências?"), ("Executar tarefas permitidas", "Consultar status"), ("Consultar status", "Pendências retomáveis?"),
             ("Esperar antes de retomar", "Executar tarefas permitidas"), ("Gerar dossiê", "Exportar para staging do Obsidian"), ("Exportar para staging do Obsidian", "Aguardando curadoria humana"),
             ("Aguardando curadoria humana", "Responder status"), ("Registrar erro", "Responder erro"), ("Agenda: eventos (desabilitado)", "Ler eventos"), ("Ler eventos", "Confirmar eventos")]:
    link(a, b)
link("Sem evidências?", "Responder: sem evidências", 0)
link("Sem evidências?", "Executar tarefas permitidas", 1)
link("Pendências retomáveis?", "Esperar antes de retomar", 0)
link("Pendências retomáveis?", "Gerar dossiê", 1)
link("Executar tarefas permitidas", "Registrar erro", 1)
link("Gerar dossiê", "Registrar erro", 1)
# o nó de Obsidian está desabilitado: o n8n o atravessa sem executar e passa o item adiante

wf = {"name": "II · Investigação criativa (MS06) — INATIVO", "nodes": nodes, "connections": conns, "active": False, "settings": {"executionOrder": "v1", "saveManualExecutions": True},
      "pinData": {}, "meta": {"templateCredsSetupCompleted": False, "ii_target": "n8n 1.x com nós: webhook v2, httpRequest 4.2, if 2, set 3.4, wait 1.1, respondToWebhook 1.1. NÃO validado numa instalação real."},
      "tags": []}
OUT.write_text(json.dumps(wf, ensure_ascii=False, indent=2, sort_keys=False) + "\n", encoding="utf-8")
print(f"{len(nodes)} nós → {OUT.name}")

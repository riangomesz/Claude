# Workflow n8n — Investigação criativa (MS06)

Arquivo: `ii_creative_engine_investigacao.workflow.json` (gerado por `build_workflow.py`). **Inativo** (`active: false`), **sem credenciais**, **sem chamadas externas**: só `POST http://127.0.0.1:8777/v1/<operação>` da API local `ii.ce.api.v1`. A lógica de domínio fica no backend; não há nó Code.

**Versão-alvo:** n8n 1.x com `webhook` v2, `httpRequest` 4.2, `if` 2, `set` 3.4, `wait` 1.1, `respondToWebhook` 1.1, `scheduleTrigger` 1.2. **Não foi importado numa instalação real de n8n**: a validação feita foi estrutural (testes em `tests/test_api_n8n.py`) mais a execução da mesma sequência de chamadas contra a API real. Na primeira importação, confira se algum nó pede upgrade de versão.

## Fluxo

`Webhook/Teste manual → Configuração → Normalizar entrada → Abrir investigação → [sem evidências? responde e para] → Executar tarefas permitidas → Consultar status → [running/partial e < 3 rodadas? espera 60 s e repete com retry_blocked] → Gerar dossiê → (Obsidian, desabilitado) → Aguardando curadoria humana → Responder`.

Erros de `run`/`gerar dossiê` seguem pela saída de erro para "Registrar erro → Responder erro (502)". Os nós HTTP repetem até 3 vezes.

## Endpoints que precisam existir

`POST /v1/{open_investigation, run_investigation, get_status, generate_dossier}`; opcionais: `export_obsidian`, `poll_events`, `ack_events`. Todos em `ii_ce/api.py`. Para subir a API local (exemplo, num script seu):

```python
from ii_ce.api import CreativeAPI, serve
api = CreativeAPI(factory, out_dir, staging_dir)   # factory() devolve um CreativeEngine com conexão própria
server, thread = serve(api, "127.0.0.1", 8777)
```

## Credenciais futuras

Nenhuma é exigida agora. Quando houver provedores reais de IA, as chaves ficam **no backend** (adaptador do provedor), nunca no n8n. O n8n continuará sem credencial de IA.

## Decisões humanas

O backend recusa `approve` e `register_review` de atores `n8n:`. Por isso esses passos **não existem** no workflow: aprovação de modelo pago, revisão de hipóteses e aprovação do dossiê são feitas por uma pessoa (painel/API). O fluxo termina em "Aguardando curadoria humana".

## Testar sem custo

1. Importar o JSON em um n8n de teste (nunca o de produção) e **não ativar**.
2. Subir a API com o demo sintético (`python -X utf8 -m ii_ce.demo` mostra o fluxo; ou use a fábrica dos testes).
3. Rodar "Teste manual" com um `reference_id` real do banco de teste. `max_usd: 0` impede qualquer modelo pago.
4. Repetir a execução: nada deve duplicar (a investigação, as tarefas e o dossiê são idempotentes).

## Ativação progressiva

1) Só até "Gerar dossiê" com o webhook em teste; 2) habilitar "Exportar para staging do Obsidian" (continua staging, nunca o cofre real); 3) habilitar a agenda de eventos (`poll_events`/`ack_events`); 4) só depois, com provedores reais aprovados por você, ajustar `max_usd` no backend/perfil de execução.

## Reverter

Desativar e excluir o workflow. O estado vive no backend: nada se perde e reimportar retoma pelos ids determinísticos. Para descartar uma investigação, basta não usá-la (versões antigas ficam `superseded`).

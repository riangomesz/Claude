# Arquitetura do Creative Intelligence Engine

## Fluxo

```
ii_be (ingestão → pipeline → análise ii_mm corrente)
   │  build_bundle: evidências + classificação + metadados + mídia  (congelado na investigação)
   ▼
open_investigation ──► plano (planner) ──► ce_tasks (1 por especialista, com dependências)
   ▼
run: claim atômico + lease ─► gateway ─► especialista (MOCK) ─► validação do contrato ─► ce_claims
   ▼
reconcile: ce_claims + ce_reviews ─► ce_groups (estado de verificação por chave)
   ▼
dossier: análise determinística (decompose/reverse/repro/adapt/kit) ─► arquivos + manifest + ce_dossiers (versão)
   ▼
eventos (ce_events) ─► n8n / painel          obsidian staging ─► notas com links entre vídeos
```

## Contratos

| Contrato | Onde | Observação |
|---|---|---|
| `ii.ce.investigation.v1` | `investigation_object()` | ids, hashes, versões de processadores e perfis, evidências por status, etapas, análises, revisões, versões do dossiê |
| `ii.ce.specialist_request.v1` / `…result.v1` | `contracts.py`, `providers.py` | esquema fechado; evidência fora do pacote enviado invalida o resultado; campos extras (`actions`) são descartados |
| `ii.ce.business_profile.v1` | `profiles/*.json` | validado: campos obrigatórios e princípios conhecidos |
| `ii.ce.dossier_manifest.v1` | `manifest.json` | hash por arquivo, índice de evidências citadas, seções sem dados, revisões humanas |
| `ii.ce.status.v1`, `ii.ce.api.v1` | `orchestrator.status`, `api.py` | para o painel e o n8n |

## Taxonomia (4 domínios, sempre ligada a evidência)

`conteudo`, `linguagem_audiovisual`, `engenharia_reversa`, `aplicacao_comercial`. Toda afirmação tem `key` canônica (`tecnica:punch_in`, `ferramenta:capcut`, `cena:7.9`, `narrativa:gancho`, `passo:01`, `producao:…`), `kind` e `evidence_ids`. Afirmação **factual sem evidência é rebaixada a hipótese** (registrada em `notes`).

## Estado de verificação (reconciliação)

| Estado | Regra |
|---|---|
| `contradicted` | valores divergentes para a mesma chave; fica aberto |
| `hypothesis` | só hipótese/recomendação/pergunta, ou só evidência de inferência |
| `supported` | há evidência visual ou medida |
| `supported_static` | técnica de **movimento** (punch-in, transição, texto cinético…) com evidência só de quadros: aparece, movimento/duração não comprovados |
| `claimed` | só fala ou legenda |
| `unverified` | nenhuma evidência |

Concordância entre especialistas é registrada (`agents`) e **não muda o estado**. A decisão humana (`confirm/reject/needs_evidence/correct`) fica em `ce_reviews`, por `(referência, chave)`: sobrevive a novas investigações, aparece no dossiê e **nunca altera o estado de máquina** (confirmar uma hipótese não a torna "sustentada"). Rejeitar remove a afirmação das adaptações e dos planos.

## Planejamento

`classify_reference` usa as categorias do classificador **com suporte** (não as `insufficient`): `tutorial_tecnico`, `workflow_automacao`, `edit_cinematografico`, `marketing`, `complexo` (≥3 grupos e ≥3 categorias fortes), `simples`, `sem_evidencia`. Ordem de prioridade por tipo; `implementacao` sempre depende de `reproducao`. Profundidade (`light`=1, `standard`=2 (3 em complexo), `deep`=4 especialistas) e limites (`max_calls`, `max_usd`, `deadline_s`, `require_start_approval`) cortam com o motivo registrado. Provedor ausente ou indisponível **não derruba a investigação**: a tarefa fica `blocked_provider` e as independentes continuam (`partial`).

## Idempotência, concorrência, retomada

- `investigation_id = hash(referência, input_hash)`; `input_hash` = evidências + mídia + versões de processadores + perfis (versão e hash) + profundidade + limites. Mesma entrada = mesma investigação. Entrada nova = próxima versão (`seq`), a anterior vira `superseded` e permanece intacta.
- Tarefa: `UPDATE … WHERE state IN ('pending','awaiting_approval')` condicional (um vencedor entre threads/processos), `lease_until`, tentativas. Resultado só é gravado por quem ainda detém o lease. Afirmação com id determinístico + `INSERT OR IGNORE`.
- Queda: a tarefa fica `running` até o lease vencer; `run` a recoloca na fila; após `max_attempts` vira `failed`.
- Estado da investigação e reconciliação são recalculados **dentro da transação** (sem regressão de estado entre workers).

## Controle de custo e aprovação

Custo estimado > 0 exige `approve(…, 'paid_models', …)` por **humano**; sem isso a tarefa fica `awaiting_approval` e o provedor não é chamado. `max_usd` é aplicado no planejamento e na execução. Atores automáticos (`n8n:`, `agent:`, `auto:`, `worker:`, `model:`, `system:`, `bot:`) são recusados em `approve` e `review` (mesma regra da curadoria do `ii_be`).

## Dados × instruções

Instruções vêm de `PROMPTS` versionados. Legenda, transcrição e metadados vão no campo `data` com `untrusted: true`, nunca concatenados às instruções (testado). Cada especialista recebe só o subconjunto necessário (≤ 80 evidências); `implementacao` recebe apenas as afirmações do `reproducao`.

## Dossiê

Determinístico (sem horário no corpo): mesmo estado = mesmos bytes = mesma versão. Mudança (por ex. uma revisão humana) = versão nova; a anterior vai para `_versoes/inv<seq>_v<n>/`. Texto externo é neutralizado (`<`, `|`, crases, títulos). CSV neutraliza `= + - @`. Seções sem dados dizem "Sem dados" e entram em `sections_without_data`.

## O que reaproveita do backend (sem copiar nem alterar)

`Engine`/conexão SQLite, `tx`, relógio injetável, `current_metadata`, `ClassificationService`, `RefScopedRepository`, `ArtifactStore` (hash da mídia), `AUTOMATED_PREFIXES`, `event_id_for`, servidor HTTP loopback e `ApiError`; do `ii_mm`: trava de cofre do Obsidian, escrita atômica e marcadores do bloco de curadoria.

**Diferença consciente:** o `AnalysisGateway` do `ii_be` é específico de análise visual (`ii.be.analysis_request/result.v1`). O gateway de especialistas é novo e segue as mesmas regras (rede recusada, aprovação, prazo, esquema fechado), mas guarda o estado em `ce_tasks`, não em `be_gateway_*`.

# Arquitetura do backend `ii_be` (Missão Suprema 04)

Camada operacional do Instagram Intelligence sobre o núcleo `ii_mm` (RC1, `d0e1916`). O `ii_mm` é usado como dependência por caminho (`ii_be/_ii_mm.py`), sem cópia e sem alteração.

Tudo roda com biblioteca padrão, SQLite e processos locais. Não há Redis, broker, microsserviço nem modelo externo.

## 1. Matriz de reutilização (Tarefa 01)

| Capacidade | O que já existe no `ii_mm` | Decisão | Como o backend usa |
|---|---|---|---|
| Persistência de análises | `db/migrations.py` (M001–M008), `db/repository.py` (`save_analysis` idempotente, versões `superseded`) | **REUTILIZAR** | A etapa `classify` grava SÓ por `Repository.save_analysis`; migrações do ii_mm aplicadas antes das do backend |
| Migrações do backend | — | **IMPLEMENTAR** | Trilha própria `be_schema_migrations` (BE001–BE004), mesmas garantias (checksum, sequência, transação) |
| Identidade da referência | `dedup.canonical_reference_key`, `refs`/`ref_aliases` | **REUTILIZAR + ESTENDER** | `identity.register_reference` grava `refs` com as mesmas regras; acrescenta `reference_id` determinístico, limpeza de URL (rastreio e credenciais) e histórico de metadados |
| Identidade de mídia | `videos.content_sha256` | **REUTILIZAR + ESTENDER** | `be_artifacts` dá identidade ao arquivo ANTES da análise (parcial, corrompido, versões) |
| Identidade da análise | `analysis_input_hash` | **REUTILIZAR** | Usada como `output_digest` da etapa `classify` (corte antecipado) |
| Normalização e adaptadores | `normalize.Normalizer`, `adapters.*` (SRT, segmentos, ffprobe, cenas, quadros, métricas, observações) | **REUTILIZAR** | Etapas `probe/transcribe/scenes/frames/metrics/visual_analysis/assemble` só leem e validam saídas já produzidas |
| Classificação | `classifier.Classifier`, `narrative.suggest_blocks`, `techniques.build_techniques` | **REUTILIZAR** | Etapa `classify`; `ClassificationService` é camada de aplicação (pedir, acompanhar, consultar, facetas) |
| Pipeline de estados | `pipeline.Pipeline` (linear, `processing_state`, lease) | **ESTENDER (sem gravar a mesma tabela)** | Fila + grafo próprio; mesma semântica de lease e a mesma exceção `LeaseLost`; estado da referência DERIVADO com os nomes do `ii_mm.pipeline.STAGES` |
| Revisão humana | `review.ReviewService` (categorias, ferramenta, rebaixar evidência; etag por `expected_seq`) | **REUTILIZAR + ESTENDER** | `CurationService` delega ao ii_mm e acrescenta triagem, nota, confirmação de evidência e rejeição de hipótese |
| Catálogo e paginação | `catalog.build_sql` (keyset, análise corrente) | **REUTILIZAR + ESTENDER** | `search.build` injeta filtros do backend no MESMO SQL (texto de metadados, tipo/completude de evidência, curadoria, data) |
| Biblioteca de técnicas | `technique_library` | **REUTILIZAR (indireto)** | O índice `be_knowledge` responde as perguntas da Tarefa 13 com proveniência |
| Gateway n8n | `n8n_contract.MissionGateway` (HMAC, missão idempotente) | **REUTILIZAR (mantido)** | Continua sendo a porta de entrada de missões; o backend acrescenta fila e eventos atrás dela. A regra de caminho `_bad_uri` é reutilizada pelos artefatos |
| Exportação Obsidian | `obsidian_export.export_reference` (staging, escape) | **REUTILIZAR** | Etapa `export` (só staging; o ii_mm recusa pasta de Vault) |
| Modo sombra e avaliação | `shadow`, `evaluation` | **ADIAR (sem mudança)** | Continuam válidos para o Estágio 2 com o catálogo real |
| Fila persistente, scheduler, retry, dead-letter | — | **IMPLEMENTAR** | `queue.py`, `scheduler.py`, `errors.py` |
| Processamento incremental | Pipeline refaz o que vem depois de uma mudança | **IMPLEMENTAR** | `incremental.py`: impressão digital de entrada + corte antecipado |
| Eventos | — | **IMPLEMENTAR** | Outbox transacional em SQLite + consumidores idempotentes |
| Gateway de modelos | — | **IMPLEMENTAR (somente mock)** | `gateway.py`; provedor com rede é recusado |
| API e observabilidade | — | **IMPLEMENTAR** | `api.py` (+ `http_local.py` opcional, loopback), `observability.py` |
| Busca vetorial | — | **ADIAR** | `search.SemanticIndex` é só interface; não operacional |

## 2. Arquitetura operacional (Tarefa 02)

```
 FONTES (dados já obtidos, sem coleta ativa)             BACKEND ii_be (Python, SQLite, um arquivo de banco)
 ─────────────────────────────────────────               ──────────────────────────────────────────────────────────────
 URL Instagram/YouTube, exportação da Meta,  ──▶ ingest ──▶ identity (refs do ii_mm) ──┐
 manifestos, arquivo local, entrada manual            │      be_sources, be_reference_meta │  outbox (mesma transação)
                                                      └──▶ artifacts (SHA-256, versões) ─┤──────────────▶ be_outbox
 ferramentas locais (ffprobe, ffmpeg, whisper,  ──▶ register_artifact ───────────────────┘                  │
 observador humano/agente) produzem ARQUIVOS                                                                  ▼
                                                    consumidor "planner" (idempotente) ──▶ job `plan` ──▶ Planner
                                                                                                              │ grafo
                                                    be_jobs + be_job_deps + be_job_attempts ◀────────────────┘
                                                         │ claim/lease/heartbeat/retry/dead-letter
                                                    workers (threads ou processos, cada um com sua conexão)
                                                         │ StageContext (prazo, cancelamento, integridade)
           acquire → probe ┐                              ▼
                   → audio → transcribe ┐        stages.py (adaptadores do ii_mm) ──▶ be_stage_results (cache)
                   → scenes → frames → metrics ┐                │
                                    → visual_analysis ┐          ▼
                                 assemble ◀───────────┘  Normalizer (ii_mm) ─▶ classify: Classifier + Repository (ii_mm)
                                    ↓                                                   │
                                 classify ─▶ index (be_knowledge, com curadoria) ─▶ export (staging Obsidian, ii_mm)
                                                                                        │
 painel futuro ◀── api.py (ii.be.api.v1) ◀── search / knowledge / classification / curation / diagnostics
 n8n futuro    ◀── eventos (JSONL em staging; nenhum webhook real nesta missão)
```

| Camada | Módulo | Responsabilidade |
|---|---|---|
| Ingestão | `ingest.py` | Contrato `ii.be.ingest.v1`, adaptadores offline, validação fechada, idempotência por origem + conteúdo |
| Identidade | `identity.py` | Chave canônica (ii_mm), `reference_id` determinístico, aliases, histórico de metadados |
| Aquisição de evidências | `artifacts.py`, `Engine.register_artifact` | Registro de arquivos com caminho seguro, hash, versão, estado e limpeza controlada |
| Fila persistente | `queue.py` | Estados, prioridade, tentativas, lease, cancelamento, reagendamento, dedup de pedidos, limites |
| Política de erros | `errors.py` | Classes de erro, backoff exponencial com jitter e teto, orçamentos separados, dead-letter |
| Planejamento | `scheduler.py` | Grafo acíclico, planejamento por referência, reprocessamento seletivo, visão de estado |
| Incremental | `incremental.py` | Impressão digital de entrada, reuso, corte antecipado, invalidação sem apagar |
| Motor de processamento | `worker.py` | Executa jobs com prazo e conclusão atômica |
| Adaptadores audiovisuais | `stages.py` | Etapas sobre os adaptadores e o classificador do ii_mm |
| Classificação | `classification.py` | Pedir, acompanhar e consultar; 10 facetas |
| Curadoria | `curation.py` | Decisões humanas soberanas, etag, histórico |
| Conhecimento e consulta | `knowledge.py`, `search.py` | Índice com proveniência; busca combinada sobre o catálogo do ii_mm |
| Exportação | etapa `export` | Nota em staging (ii_mm) |
| Eventos | `events.py` | Outbox transacional, consumidores idempotentes, reconciliação das revisões do ii_mm |
| Gateway de modelos | `gateway.py` | Contratos e controles; somente mock |
| API / observabilidade | `api.py`, `http_local.py`, `observability.py` | Serviços validados; logs com redação; diagnóstico |

### Python × n8n

| Fica no backend Python (domínio) | Fica no n8n (orquestração) |
|---|---|
| Identidade, deduplicação, versões | Gatilhos (pasta nova, horário, webhook local) |
| Regras de evidência, classificação, curadoria | Chamar as ferramentas locais (ffmpeg, whisper) e depois `register_artifact` |
| Fila, dependências, retry, dead-letter | Enviar missão `ii.mission.v1` (assinada) ou ingestão pela API |
| Índice de conhecimento e consultas | Ler eventos (JSONL ou, no futuro, webhook) e notificar pessoas |
| Exportação para staging | Copiar do staging para o Vault só com ação humana |

O n8n nunca decide categoria, nunca grava no banco diretamente e nunca aprova curadoria nem chamada paga.

## 3. Contratos de comunicação

| Contrato | Onde | Direção |
|---|---|---|
| `ii.be.ingest.v1` | `ingest.validate_record` | fonte → backend |
| registro de artefato (`reference_id`, `kind`, `relpath`, `origin`, hash e tamanho esperados) | `Engine.register_artifact`, API `register_artifact` | ferramenta → backend |
| `ii.be.api.v1` (envelope, códigos de erro, idempotência) | `api.py` | painel/n8n → backend |
| eventos `ii.be.event.v1` (`event_id`, `type`, `aggregate_id`, `payload`) | `events.py` | backend → consumidores |
| `ii.be.analysis_request.v1` / `ii.be.analysis_result.v1` | `gateway.py` | backend → agente/modelo (mock) |
| `ii.reference_analysis.v2`, `ii.mission.v1`, `ii.mission_result.v1` | `ii_mm` (inalterados) | núcleo |

Exemplos gerados pelo código ficam em `contratos/` (`tools/contracts.py`, conferidos por `tests/test_contracts.py`).

### Estados de job × estado de processamento

| Job (`be_jobs.state`) | Significado | Visão da referência (`processing_view`) |
|---|---|---|
| `queued`, `waiting_dependency`, `retry_scheduled` | aguardando | etapa pendente |
| `claimed`, `running` | em execução (com lease) | etapa em andamento |
| `completed` | resultado gravado (ou reaproveitado) | etapa `done` → equivalente no ii_mm (`media_available`, `metadata_extracted`, `audio_processed`, `visual_processed`, `evidence_normalized`, `classified`, `completed`) |
| `failed`, `dead_letter`, `cancelled` | terminal, inspecionável | etapa parada; dependentes aparecem como bloqueados no diagnóstico |

`awaiting_review` é derivado: há análise corrente e nenhuma decisão humana registrada.

## 4. Decisões e limitações

- **Uma autoridade por dado.** Ver o cabeçalho de `ii_be/db.py`. O backend não grava `processing_state`.
- **SQLite basta para o estágio atual.** Concorrência por `BEGIN IMMEDIATE` + WAL; a vazão medida está em `BENCHMARK_BACKEND.md`. Vários *processos* na mesma máquina funcionam como várias threads com conexões próprias. Várias *máquinas* no mesmo arquivo não são suportadas: o lease depende do relógio local e SQLite em rede não é confiável.
- **I1 (ii_mm):** análise corrente por vídeo. Mitigada por `RefScopedRepository`. Os filtros SQL do catálogo continuam por vídeo.
- **Timeout de etapa:** com banco em arquivo, o handler roda em thread e é abandonado ao passar do prazo; o Python não interrompe thread à força, então o handler para no próximo `ctx.check()`. Para isolamento total (ex.: ffmpeg travado), a ferramenta externa deve rodar em processo próprio, com timeout no n8n ou no executor.

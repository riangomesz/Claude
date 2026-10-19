# Relatório: Missão Suprema 04 (Backend Intelligence Engine)

Data: 2026-10-19.

- **Branch:** `claude/instagram-intelligence-backend-supreme-04`, criada a partir de `3ec455c`.
- **Isolamento:** a branch da RC1 continua intocada; `main` continua em `34ee777`; o clone do Projeto-MVP continua em `c6845a4`, sem alterações. Nenhum merge, PR ou tag.
- **RC1** (`ii_mm-1.0.0-rc1`, `d0e1916`): nenhum arquivo de `proposals/multimodal_v2/` foi alterado. O validador de recebimento continua OK com o manifesto `10f0e9d8…`.

Legenda de status: **IMPLEMENTADO** (código existe) · **TESTADO** (coberto por teste que passa) · **PROPOSTO** (desenho/documento, sem código operacional) · **NÃO VERIFICADO** (depende de ambiente indisponível) · **BLOQUEADO** (depende de dado ausente).

## 1. Resumo

Foi construído o pacote `proposals/backend_engine_v1/ii_be`: cerca de 4.700 linhas, só biblioteca padrão. É uma camada operacional concreta acima do `ii_mm`, que é usado como dependência (sem cópia).

O motor coordena este ciclo:

```
referência → aquisição autorizada → artefatos → etapas audiovisuais → normalização → classificação (ii_mm)
           → curadoria humana → conhecimento estruturado → consulta → exportação/eventos
```

Cada etapa tem contrato, persistência, tratamento de erro e retomada. A demonstração ponta a ponta roda com dados sintéticos, simula uma queda, retoma e prova que não há duplicação nem perda de histórico. É reproduzível: duas execuções produzem o mesmo resumo. São 94 testes, OK em Python 3.11.17, 3.12.3 e 3.13.16.

**Não está pronto para produção.** Nada foi executado no Windows, com mídia real ou com o catálogo real.

## 2. Arquitetura produzida

Detalhes em `ARQUITETURA_BACKEND.md`.

- Um arquivo SQLite (WAL) guarda as tabelas do `ii_mm` (M001–M008) e as do backend (`be_*`, migrações BE001–BE005 em trilha própria).
- **Uma autoridade por dado.** O `ii_mm` é dono de referências, vídeos, análises e revisões de categoria/ferramenta/evidência. O backend é dono de origens, metadados históricos, artefatos, jobs, resultados de etapa, curadoria de triagem/nota, eventos e índice de conhecimento.
- **A fila é a autoridade sobre a execução.** O estado de processamento da referência é DERIVADO, com os nomes do `ii_mm.pipeline`. O backend não grava `processing_state`.
- **Fluxo orientado a eventos dentro do banco:** outbox transacional → consumidor "planner" → job `plan` → jobs de etapa com dependências → workers.
- **Sem Redis, broker, microsserviço ou modelo externo.** A justificativa e os limites estão na seção 4 da arquitetura e no benchmark.

## 3. Código reutilizado do `ii_mm` (REUTILIZAR, sem cópia)

| Componente | Uso no backend |
|---|---|
| `db.migrations` (`connect`, `migrate`, `Migration`) | Banco do motor; recusa `catalog.sqlite` |
| `db.repository.Repository.save_analysis` | Única via de persistência de análises |
| `dedup.canonical_reference_key`, `parse_reference`, `analysis_input_hash` | Identidade da referência e da análise |
| `normalize.Normalizer`, `adapters.*` | Etapas audiovisuais e `assemble` |
| `classifier.Classifier`, `narrative.suggest_blocks`, `techniques.build_techniques` | Etapa `classify` |
| `review.ReviewService` | Decisões de categoria, ferramenta e evidência (via `RefScopedRepository`) |
| `catalog.build_sql` e o atalho de existência | Busca combinada |
| `obsidian_export.export_reference` | Etapa `export` (staging) |
| `pipeline.LeaseLost` | Mesma exceção e semântica de posse da fila |
| `n8n_contract._bad_uri` | Regra de caminho dos artefatos |
| `_matcher.normalize`, `contract.canonical_json`, `vocabulary`, `evidence_rules`, `techniques.LEVEL_PROVES` | Termos, hashes, taxonomia |

## 4. Novos módulos

| Módulo | Função | Status |
|---|---|---|
| `db.py` | Migrações BE001–BE005 e transação `BEGIN IMMEDIATE` com nova tentativa | IMPLEMENTADO, TESTADO |
| `ingest.py` | Contrato `ii.be.ingest.v1`; adaptadores URL / exportação da Meta / manifesto / arquivo local / manual | IMPLEMENTADO, TESTADO |
| `identity.py` | Chave canônica, `reference_id` determinístico, aliases, limpeza de URL, histórico de metadados | IMPLEMENTADO, TESTADO |
| `artifacts.py` | Registro de artefatos: caminho seguro, hash, versão, estado, limpeza controlada | IMPLEMENTADO, TESTADO |
| `queue.py` | Fila: 9 estados, lease, prioridade, dedup, dependências, limites, cancelamento, requeue, reagendamento | IMPLEMENTADO, TESTADO |
| `errors.py` | Classes de erro, backoff com jitter e teto, orçamentos separados | IMPLEMENTADO, TESTADO |
| `scheduler.py` | Grafo acíclico, planejamento, reprocessamento seletivo, visão de estado | IMPLEMENTADO, TESTADO |
| `incremental.py` | Impressão digital de entrada, reuso, corte antecipado, invalidação sem apagar | IMPLEMENTADO, TESTADO |
| `stages.py`, `worker.py` | Etapas audiovisuais sobre o ii_mm; execução com prazo e conclusão atômica | IMPLEMENTADO, TESTADO |
| `classification.py` | Pedir, acompanhar, consultar; 10 facetas | IMPLEMENTADO, TESTADO |
| `curation.py` | Curadoria humana soberana, etag, histórico | IMPLEMENTADO, TESTADO |
| `knowledge.py`, `search.py` | Índice com proveniência, perguntas da Tarefa 13, busca combinada, listagem | IMPLEMENTADO, TESTADO |
| `events.py` | Outbox transacional, consumidores idempotentes, reconciliação, sink JSONL | IMPLEMENTADO, TESTADO |
| `gateway.py` | Gateway de agentes e modelos, somente mock | IMPLEMENTADO, TESTADO |
| `api.py`, `http_local.py` | API `ii.be.api.v1`; HTTP só em loopback | IMPLEMENTADO, TESTADO |
| `observability.py` | Logs JSON com redação; diagnóstico | IMPLEMENTADO, TESTADO |
| `refscope.py` | Análise corrente por referência (mitiga I1) | IMPLEMENTADO, TESTADO |
| `engine.py`, `demo.py`, `synthetic.py` | Fachada, demonstração, fixtures sintéticas | IMPLEMENTADO, TESTADO |
| `search.SemanticIndex` | Busca vetorial opcional | PROPOSTO (só interface) |

## 5. Contratos implementados

| Contrato | Status |
|---|---|
| `ii.be.ingest.v1` | IMPLEMENTADO, TESTADO |
| `ii.be.api.v1` (envelope, erros estruturados, paginação, limites, idempotência) | IMPLEMENTADO, TESTADO |
| `ii.be.event.v1` | IMPLEMENTADO, TESTADO |
| `ii.be.analysis_request.v1` / `ii.be.analysis_result.v1` | IMPLEMENTADO, TESTADO |
| Registro de artefato | IMPLEMENTADO, TESTADO |

Os exemplos de cada contrato são gerados pelo código em `contratos/` (`tools/contracts.py`); `tests/test_contracts.py` confere que os arquivos publicados batem com o código. Os contratos do `ii_mm` não mudaram.

## 6. Testes executados

| Suíte | Resultado |
|---|---|
| Backend (`run_tests.py`, 94 testes, `-W error::ResourceWarning`) | OK em 3.11.17, 3.12.3, 3.13.16 |
| RC1 (`proposals/multimodal_v2/run_tests.py`) sem clone | 384 testes: 371 OK + 13 pulados |
| RC1 com cópia do clone `c6845a4` | 384 OK |
| Demonstração (`python3 -X utf8 -m ii_be.demo`) | `18_verification` limpo; reproduzível |

Distribuição dos 94 testes:
- fila: 15;
- ingestão e identidade: 11;
- scheduler e incremental: 11;
- serviços (facetas, conhecimento, curadoria, busca): 11;
- concorrência com threads e WAL: 9;
- gateway: 8;
- artefatos: 7;
- API, HTTP e observabilidade: 7;
- portabilidade: 4;
- segurança: 4;
- mídia compartilhada: 3;
- contratos e higiene do pacote: 3;
- demonstração: 1.

A concorrência (Tarefa 19) foi testada com:
- vários workers disputando o mesmo job;
- lease perdido;
- worker interrompido antes de gravar;
- etapa lenta com prazo;
- banco ocupado (espera e falha limpa);
- cancelamento durante a execução;
- evento entregue a dois despachantes;
- dedup sob corrida de produtores;
- `integrity_check` ao final.

## 7. Defeitos encontrados e corrigidos (cada um com teste)

| # | Onde | Defeito | Correção |
|---|---|---|---|
| D-BE1 | backend (grafo) | `assemble` não dependia de `acquire`: o documento ia ao ii_mm sem `content_sha256` e a deduplicação por conteúdo não acontecia | Dependência direta; `test_shared_media` |
| D-BE2 | backend (fila) | Escala: `claim` com varredura e ordenação a cada chamada; dedup sem o índice parcial (vazão de 501 → 93 jobs/s de 82 para 1.000 referências) | BE005 (`blocked_deps` e índice parcial de claim); `QueryPlanTest` |
| D-BE3 | backend (identidade) | `?igsh=` (identifica quem compartilhou) e credenciais `usuario:senha@` seriam gravadas | `clean_url` (só hostname; só `v`/`t` no YouTube) |
| D-BE4 | backend (ingestão) | Caracteres de controle (NUL, escape ANSI) aceitos em autor, hashtags e legenda | Validação por campo |
| D-BE5 | backend (artefatos) | `media//x` e `./x` aceitos (o `PurePosixPath` colapsava os componentes) | Validação por componente cru |
| D-BE6 | backend (API) | Motor por thread vazaria conexões no servidor HTTP com várias threads | Motor por chamada, fechado ao final |
| D-BE7 | backend (benchmark) | Leitura de `/proc/meminfo` sem `encoding` e com caminho POSIX literal (acusado pela varredura de portabilidade da RC1) | `Path(os.sep, …)` + `encoding`; `test_portability` |
| — | backend (adaptador) | `record_from_url` vazava `IdentityError` em vez de `InvalidInput` | Conversão |

## 8. Demonstração ponta a ponta

`python3 -X utf8 -m ii_be.demo` cobre os passos 1 a 18 com quatro referências sintéticas:
- um reel com mídia;
- o mesmo vídeo republicado no YouTube;
- um item de exportação da Meta (outro item da exportação caiu na referência já existente);
- uma referência manual só com metadados.

Resultados:
- 28 jobs de etapa planejados, 25 aguardando dependências;
- artefato corrompido detectado (o v1 continua corrente);
- classificação pelo ii_mm: CapCut `visually_identified`, `tutorial` `mentioned_speech`;
- revisão humana refez só `index` e `export`;
- 2 notas em staging;
- 32 eventos em JSONL para o n8n futuro, sem rede.

A classificação do repost caiu antes de gravar (`running`, lease do worker A). Depois do vencimento do lease, o worker C concluiu, com tentativas `lease_lost` e `completed`. Verificação final:

| Item | Valor |
|---|---|
| Referências | 4 |
| Resultados de etapa duplicados | 0 |
| Jobs concluídos duas vezes | 0 |
| Vídeos | 2 |
| Análises | 3 |
| Histórico humano preservado | 4 decisões |
| Eventos consumidos uma vez | sim |
| `integrity_check` | `ok` |
| Jobs pendentes | 0 |

## 9. Benchmarks

Ver `BENCHMARK_BACKEND.md`. Dados sintéticos; não é desempenho de produção.

- Com 10.000 referências: ingestão de cerca de 2,1 ms/registro; reingestão 0,14 ms sem criar nada.
- Planejamento: 2,0 ms por referência.
- Fila: cerca de 340 jobs/s, estável entre 1.000 e 10.000 referências (40.000 jobs). Quatro workers não aumentam a vazão do controle.
- Pipeline real com o ii_mm: cerca de 25 ms por referência (4 etapas).
- Taxonomia nova: `index` 100% reaproveitado; o reprocessamento custou cerca de 60% do completo.
- Busca sem resultado: 0,011 ms.
- Retomada de 1.000 jobs presos: 76 ms.

## 10. Limitações

1. **NÃO VERIFICADO:** Windows. Inclui threads e WAL no NTFS, antivírus e o timeout por thread.
2. Dados sintéticos apenas. **Nenhuma métrica de qualidade de classificação.**
3. Etapas audiovisuais só consomem saídas já produzidas: o backend não executa ffmpeg nem Whisper. Ferramenta travada precisa de timeout no processo externo.
4. Timeout de etapa em thread é cooperativo: o Python não mata thread. O lease cobre handler travado.
5. Vários processos na mesma máquina funcionam. Várias máquinas no mesmo arquivo: não suportado.
6. Gateway somente mock. Nenhum provedor real foi implementado ou conectado.
7. Eventos para o n8n só como JSONL. Entrega "pelo menos uma vez" para destinos externos.
8. Busca de metadados por termos exatos normalizados. Busca semântica: PROPOSTA.
9. Ingestão de datas de publicação: guardada no histórico, mas sem filtro por data de publicação (o filtro é a data de ingestão).

## 11. Incompatibilidades conhecidas

- **I1 (ii_mm, RC1):** a análise corrente é por vídeo. Com mídia compartilhada entre referências, `current_analysis_id` de uma referência devolve a análise da outra. Mitigado no backend (`RefScopedRepository`). **Permanece:** os filtros SQL do catálogo do ii_mm (`search` por categoria, ferramenta, técnica) avaliam a análise corrente do vídeo. Para facetas por referência, use as perguntas de conhecimento. Correção definitiva: rc2 do núcleo (corrente por vídeo e referência), fora do escopo desta missão.
- O backend não lê o `catalog.sqlite` legado. O adaptador de `instagram_items` para ingestão é PROPOSTO (Estágio 3 do plano).

## 12. Dependências do Windows

- Python 3.11 ou superior e SQLite 3.24 ou superior (índice parcial e UPSERT), as mesmas da RC1.
- Banco e raiz de artefatos fora de pasta sincronizada.
- Exceção do antivírus para a pasta de trabalho, se o desempenho exigir.
- Caminhos curtos (artefatos com até 240 caracteres relativos).
- Validação: `HANDOFF_ANTIGRAVITY_BACKEND.md`, seção 10.

## 13. Integração com o Antigravity

`HANDOFF_ANTIGRAVITY_BACKEND.md` (PROPOSTO, nada integrado) cobre:
- relação com o ii_mm;
- conexão futura com o catálogo;
- adaptadores necessários;
- preservação da curadoria;
- aproveitamento de FFmpeg e Whisper;
- n8n;
- painel;
- Obsidian;
- o que falta na nuvem;
- a validação no Windows.

O plano em cinco estágios com critérios verificáveis está em `PLANO_ADOCAO_BACKEND.md`.

## 14. Integração futura com o n8n

- O n8n orquestra: gatilhos, ferramentas e notificação. O backend decide o domínio.
- **Entrada:** API `ingest_reference` e `register_artifact` (idempotentes), ou a missão `ii.mission.v1` do ii_mm.
- **Saída:** eventos do outbox (contrato `ii.be.event.v1`).
- Nenhum workflow real foi tocado.
- Consumidor HTTP para o n8n: PROPOSTO.

## 15. Integração futura com o Obsidian

A etapa `export` usa o `obsidian_export` do ii_mm, só em staging. O ii_mm recusa a pasta do Vault, e a cópia para o Vault continua manual. Notas de referências curadas refletem as decisões humanas (visão revisada). Testado em staging; Vault real: NÃO VERIFICADO e não autorizado.

## 16. Pendências da segunda análise audiovisual

O vídeo-piloto `DQV5dm6gCvH` continua **BLOQUEADO** (`blocked_missing_evidence`): o pacote com 12 quadros, transcrição, cortes e ficha v2 não está disponível na nuvem. O backend está pronto para recebê-lo:
- ingestão `manifest` ou `local_file`;
- `register_artifact` para quadros, segmentos e cortes;
- etapa `visual_analysis` com as observações registradas.

Nada foi inventado ou substituído.

## 17. Próximas prioridades

1. Validar a RC1 e, em seguida, este backend no Windows (Estágio 1 dos dois planos).
2. Escrever e revisar o adaptador do snapshot de `instagram_items` para `ii.be.ingest.v1` e a importação explícita das decisões humanas legadas.
3. Medir no Windows o custo real por referência, com transcrições longas e quadros reais.
4. Rc2 do núcleo para resolver I1 na origem, se o caso de mídia compartilhada for frequente no catálogo real.
5. Consumidor de eventos para um workflow n8n NOVO, com autorização.
6. Avaliação humana de 30 a 50 vídeos antes de expor facetas no painel.

## 18. Branch e commits

| Commit | Conteúdo |
|---|---|
| `1bc3a3d` | C1: ingestão, identidade, fila, scheduler, incremental, artefatos, etapas, worker (51 testes) |
| `aa80524` | C2: facetas, curadoria, busca, gateway mock, API/HTTP, observabilidade, segurança (80 testes) |
| `3bed024` | C3: demonstração reproduzível; D-BE1; mitigação I1 (84 testes) |
| (este commit) | C4: D-BE2 (BE005), benchmark 82/1.000/10.000, contratos gerados, portabilidade, documentação, handoff, plano de adoção e este relatório (94 testes) |

Progresso detalhado e próximos passos executáveis: `PROGRESSO_MISSAO_SUPREMA_04.md`.

# Relatório: Missão Suprema 01 (Instagram Intelligence)

Branch: `claude/instagram-intelligence-audit-4ezsd1` (repositório `riangomesz/Claude`). Período: 2026-10-18.
Nenhuma alteração em `main`, no Projeto-MVP (o clone segue limpo), em bancos reais, no n8n, no Windows ou na `ii-bridge`. Nenhum modelo externo ou API paga foi chamado. Nenhum PR foi aberto.

## 1. Resumo executivo

As 18 frentes foram executadas. O resultado é um núcleo isolado (`ii_mm/`, cerca de 3.400 linhas, só stdlib) que leva uma referência audiovisual de artefatos brutos a uma nota de Obsidian revisada, sempre com a natureza de cada afirmação explícita: visto no frame, medido, dito na fala, nos metadados, inferido ou não verificado.

A suíte tem **220 testes**: 216 passam e 4 são pulados por padrão; com `PROJETO_MVP_DIR`, os 220 passam. O benchmark rodou com 82, 1.000 e 10.000 registros.

O trabalho encontrou e corrigiu **10 defeitos reais**: 4 no código isolado anterior (B1 a B4), 1 no `text_matcher`, 1 no gerador sintético frente à deduplicação, 1 na sobreposição de revisão, 2 de desempenho no catálogo (ordenação completa por página e O(N²)) e 1 falso positivo narrativo. Também registrou 3 achados sobre o Projeto-MVP (L1 a L3).

A análise visual do vídeo `DQV5dm6gCvH` continua **BLOQUEADA**: o pacote de evidências não está disponível na nuvem.

## 2. Funcionalidades

| # | Frente | Estado | Onde |
|---|---|---|---|
| 01 | Auditoria e baseline | IMPLEMENTADO / TESTADO | `BASELINE_ATUAL.md`, `run_tests.py`, `tools/stdlib_coverage.py` |
| 02 | Contrato `ii.reference_analysis.v2` (6 estados, IDs por conteúdo, validador estrito) | IMPLEMENTADO / TESTADO | `ii_mm/contract.py`, `evidence_rules.py` |
| 03 | Normalização com proveniência, deduplicação e rebaixamentos | IMPLEMENTADO / TESTADO | `ii_mm/normalize.py` |
| 04 | Classificador textual v2 (forte/fraco, exclusões, hashtags, PT/EN) | IMPLEMENTADO / TESTADO | `ii_mm/text_classifier.py` |
| 05 | Classificador multimodal multi-rótulo com contradições | IMPLEMENTADO / TESTADO | `ii_mm/classifier.py`, `vocabulary.py` |
| 06 | Migrações SQLite (7 versões, checksum, rollback, recusa de produção) | IMPLEMENTADO / TESTADO | `ii_mm/db/migrations.py` |
| 07 | Repositório de persistência | IMPLEMENTADO / TESTADO | `ii_mm/db/repository.py` |
| 08 | Deduplicação (URL canônica, SHA-256, versões, conflitos) | IMPLEMENTADO / TESTADO | `ii_mm/dedup.py` + repositório |
| 09 | Máquina de estados idempotente com retomada | IMPLEMENTADO / TESTADO | `ii_mm/pipeline.py` |
| 10 | Adaptadores de áudio e vídeo (formatos reais do Projeto-MVP) | IMPLEMENTADO / TESTADO | `ii_mm/adapters.py` |
| 11 | Estrutura narrativa | IMPLEMENTADO / TESTADO | `ii_mm/narrative.py` |
| 12 | Engenharia reversa (5 níveis de prova) | IMPLEMENTADO / TESTADO | `ii_mm/techniques.py` |
| 13 | Catálogo pesquisável com cursor | IMPLEMENTADO / TESTADO | `ii_mm/catalog.py` |
| 14 | Revisão humana com histórico imutável | IMPLEMENTADO / TESTADO | `ii_mm/review.py` |
| 15 | Exportação Obsidian em staging | IMPLEMENTADO / TESTADO | `ii_mm/obsidian_export.py` |
| 16 | Contrato e gateway n8n | IMPLEMENTADO / TESTADO | `ii_mm/n8n_contract.py`, `fixtures/n8n_*` |
| 17 | Benchmark sintético | IMPLEMENTADO / EXECUTADO / smoke TESTADO | `tools/benchmark.py`, `BENCHMARK.md` |
| 18 | Demonstração de ponta a ponta | IMPLEMENTADO / TESTADO | `ii_mm/demo.py` |
| — | Integração ao Projeto-MVP | PROPOSTO | `INTEGRACAO_ANTIGRAVITY.md` |
| — | Segunda análise visual do DQV5dm6gCvH | BLOQUEADO | `INVENTARIO_EVIDENCIAS_FALTANTES.md` |

## 3. Arquivos

**Criados** (em `proposals/multimodal_v2/`):
- Pacote `ii_mm/`: `__init__`, `_matcher`, `adapters`, `catalog`, `classifier`, `contract`, `dedup`, `demo`, `evidence_rules`, `n8n_contract`, `narrative`, `normalize`, `obsidian_export`, `pipeline`, `review`, `synthetic`, `techniques`, `text_classifier`, `vocabulary`.
- Pacote `ii_mm/db/`: `migrations`, `repository`, `legacy_fixture`.
- `tests/`: 15 módulos de teste.
- `tools/`: `stdlib_coverage.py`, `benchmark.py`; executor `run_tests.py`.
- `fixtures/`: `synthetic_reference_v2.json`, `n8n_mission_example.json`, `n8n_result_example.json`.
- `benchmarks/resultados_benchmark.json`.
- Documentos: `BASELINE_ATUAL.md`, `PROGRESSO_MISSAO_SUPREMA.md`, `BENCHMARK.md`, `INTEGRACAO_ANTIGRAVITY.md` e este relatório.

**Modificados:**
- `multimodal_classifier.py` (B3, B4) e `verify_package.py` (B1, B2), com testes novos em `test_multimodal_classifier.py` e `test_verify_package.py`.
- `classification/text_matcher.py`: `normalize` colava palavras separadas por pontuação fora do ASCII. Teste novo em `test_text_matcher.py`.
- `CLASSIFICACAO_MULTIMODAL.md`: nota de atualização.

Total da missão: 56 arquivos, cerca de 6.400 linhas inseridas.

## 4. Testes

Comando: `cd proposals/multimodal_v2 && python3 run_tests.py`. Resultado final: **220 executados, 216 OK, 4 pulados, 0 falhas.** Com `PROJETO_MVP_DIR=<clone c6845a4>`: 220 OK.

| Grupo | Testes |
|---|---|
| Legado preservado (matcher, v1, regressão, verificador) | 44 |
| Contrato, adaptadores, normalização | 41 |
| Classificador textual e multimodal | 37 |
| Migrações, repositório, deduplicação, pipeline | 45 |
| Narrativa, técnicas, catálogo, revisão | 32 |
| Obsidian, n8n, demonstração e smoke do benchmark | 21 |

Os 4 testes pulados exigem o clone do Projeto-MVP: a regressão contra `curation.py` e a reprodução do `no such table`.

Os 27 testes anteriores continuam passando. Hoje são 37 nesses mesmos arquivos, por causa dos testes acrescentados para B1 a B4.

Cobertura de linhas (stdlib `trace`, indicativa): de 88% a 100% por módulo de `ii_mm`. As menores são `contract.py` (88%) e `adapters.py` (89%), cujas lacunas são ramos de mensagens de erro.

Para garantir que os testes de defeito testam algo, cada correção foi conferida contra o código antigo. Por exemplo, 8 dos 10 testes de B1 a B4 falham na versão anterior, e o teste de plano do catálogo falha no plano O(N²).

## 5. Benchmarks

Detalhes em `BENCHMARK.md`. Ambiente: container Linux, 4 vCPU, 16 GB, Python 3.13.16, SQLite 3.45.1. Números com 10.000 registros sintéticos, **sem valor de garantia em produção**:

- Inserção: 3,7 ms por análise. Classificação: 0,9 ms por documento.
- Página do meio por cursor: 0,58 ms, contra 3,71 ms com OFFSET.
- Varredura paginada: 0,3 MB de pico, contra 159 MB carregando tudo.
- Zero duplicatas nos reenvios.
- Retomada após queda: só 1 execução repetida (a etapa interrompida).

## 6. Decisões arquiteturais

1. **A natureza da evidência é tipo, não pontuação.** Seis estados com fontes permitidas por estado: a fala não pode, por construção, virar fato visual. O apoio de uma categoria é o estado da melhor evidência, sem números de confiança.
2. **Medição não decide sozinha.** Uma `MeasuredRule` explícita fica desligada por padrão e é marcada como "não calibrada" quando usada.
3. **A base visual vem dos frames citados.** Uma alegação de base mais forte é rebaixada, e movimento com menos de 3 quadros vira inferência.
4. **IDs por conteúdo.** As mesmas evidências geram os mesmos IDs, e a análise é versionada por hash de entrada. Nada é sobrescrito: versões antigas ficam `superseded` e conflitos viram issue bloqueante.
5. **A revisão é sobreposição.** O registro automático nunca muda; as decisões têm histórico imutável e estado corrente materializado.
6. **O n8n orquestra e o `ii_mm` decide.** O contrato é fechado, as URIs são só relativas, há HMAC, e o gateway é idempotente.
7. **Portabilidade.** Só stdlib, sem FTS5 (busca por tabela de termos) e SQLite ≥ 3.24.
8. **Planos travados em teste.** Os dois defeitos de desempenho do catálogo foram encontrados pelo `EXPLAIN` e pelo benchmark, e agora há testes que impedem a regressão.

## 7. Limitações

- Todos os testes e benchmarks usam dados sintéticos. Nada foi medido sobre o catálogo real nem sobre o Windows.
- Os vocabulários (pistas textuais, tags, léxico de ferramentas) são escolhas iniciais, sem calibração. A concordância com o legado foi medida só nos 17 casos do golden (11 de 11 casos sem defeito concordam).
- Um filtro seletivo ou sem resultado percorre o índice de referências (24 ms com 10.000). Catálogos muito maiores pedem um planejamento por seletividade.
- `review_state` considera uma decisão corrente por alvo. Não há workflow de aprovação em várias etapas.
- A tag visual depende do observador (humano ou agente). O `ii_mm` não olha imagens; ele só garante que cada observação tenha base e proveniência coerentes.

## 8. Dependências de mídia

A segunda análise do `DQV5dm6gCvH` continua bloqueada: `/mnt/user-data/uploads` e `/mnt/attach` estão vazios, e não há frames nos remotos. Faltam os 12 JPEG, `manifesto_pacote.json`, `perguntas_de_verificacao.json`, `segmentos_transcricao.json` e `cortes_detectados.json`; a `ficha_inteligencia_v2.json` é opcional. `analise_multimodal_v2.json` segue `blocked_missing_evidence`.

Quando o pacote chegar, o caminho já está pronto e testado com dados equivalentes:
1. `verify_package.py`.
2. `adapters.frames_from_manifest`, `scenes_from_candidates_json`, `transcript_from_segments`.
3. Observações em `ii.visual_observation.v1`.
4. `Normalizer`, `Classifier`, `narrative`, `techniques`.
5. Relatório.

## 9. Integração recomendada com o Antigravity

Ver `INTEGRACAO_ANTIGRAVITY.md`. Resumo, em ordem crescente de risco:
1. Fixture legada nos testes.
2. Fechar as 25 conexões SQLite.
3. Classificador textual em modo sombra.
4. Banco v2 ao lado do antigo.
5. Ingestão dos pacotes do `ii_coverage`.
6. Painel com catálogo paginado e revisão.
7. Nó HTTP do n8n para o gateway.
8. Exportação Obsidian via staging.

## 10. Commits

| Commit | Conteúdo |
|---|---|
| `e45dd26` | T01 baseline, executor, cobertura e correções B1 a B4 |
| `b08c147` | T02, T03 e T10: contrato, adaptadores e normalização |
| `68d6531` | T04 classificador textual v2 e correção do `normalize` |
| `977423c` | T05 classificador multimodal e vocabulário |
| `8df0e82` | T06 a T09: migrações, repositório, deduplicação e pipeline |
| `12b19e5` | T11 a T14: narrativa, técnicas, catálogo e revisão |
| `5d9a56b` | T15 e T16: Obsidian e n8n |
| `f74f634` | T17 e T18: benchmark, correção O(N²) e demonstração |
| (este) | Documentação de integração e relatório final |

Todos os commits estão na branch `claude/instagram-intelligence-audit-4ezsd1`, com push feito.

## 11. Próximas tarefas prioritárias

1. **Fornecer o pacote do `DQV5dm6gCvH`** para destravar a análise visual (inventário exato no documento citado).
2. **Calibrar com dados reais:** rodar `compare_with_legacy` e o classificador em modo sombra sobre os itens já curados, no Windows, e medir a concordância por categoria antes de qualquer troca.
3. **Aplicar os passos 1 e 2 da integração** (fixture e fechamento de conexões): baixo risco, ganho imediato nos testes legados.
4. **Planejamento por seletividade no catálogo,** para filtros raros em catálogos grandes.
5. **Gravar o formato `ii.visual_observation.v1`** na saída do `ii_coverage`/`fase51.js`, para que observações de agentes entrem sem conversão manual.

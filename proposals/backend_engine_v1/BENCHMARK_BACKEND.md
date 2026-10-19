# Benchmark sintético do backend `ii_be` (Tarefa 21)

**Não é medição de produção.** Dados sintéticos num contêiner Linux, sem antivírus, sem disco do Windows e sem mídia real. Os números servem para comparar versões do próprio backend e para achar gargalos de algoritmo, não para prometer desempenho.

- Ambiente: Python 3.13.16, SQLite 3.45.1, Linux x86_64, 4 vCPU, 16 GB.
- Comando: `python3 -X utf8 tools/bench_backend.py --sizes 82,1000,10000 --out benchmarks/resultados_backend_ms04.json`
- Resultado bruto: `benchmarks/resultados_backend_ms04.json`

## Metodologia

| Fase | O que mede |
|---|---|
| Ingestão | N registros com URL, legenda, hashtags, autor e duração; uma transação por registro (com o evento no outbox) |
| Reingestão | Os mesmos N registros de novo; nada pode ser criado |
| Planejamento | `Planner.plan` de todas as referências (grafo de metadados: 4 etapas por referência) |
| Fila 1w/4w | Vazão com handlers triviais: custo da fila, das dependências, do resultado de etapa e do outbox, sem o ii_mm. Metade dos jobs com 1 worker e a outra metade com 4 workers em threads, cada um com sua conexão |
| Pipeline real | Etapas reais (`assemble` → `classify` do ii_mm → `index`; exportação desligada), 1 worker, até 1.000 referências |
| Incremental | Nova versão de taxonomia: replanejar e reprocessar tudo; mede o reuso de `index` (corte antecipado) |
| Consultas | Mediana de 15 execuções. Busca e perguntas de conhecimento rodam no banco do pipeline (até 1.000 referências analisadas); a listagem roda no banco com N referências |
| Retomada | Até 1.000 jobs presos em lease vencido: tempo do `recover_expired` |
| Eventos | Despacho de todo o outbox para um consumidor sem efeito |
| Memória | Pico do `tracemalloc` numa passada separada de ingestão. Mede só alocações Python; o cache de páginas do SQLite (memória C) fica de fora |

## Resultados

| Métrica | 82 | 1.000 | 10.000 |
|---|---|---|---|
| Ingestão (ms/registro) | 2,198 | 2,002 | 2,107 |
| Reingestão idêntica (ms/registro) | 0,219 | 0,117 | 0,135 |
| Novos na reingestão | 0 | 0 | 0 |
| Planejamento (ms/referência) | 1,432 | 1,793 | 2,045 |
| Jobs criados | 328 | 4.000 | 40.000 |
| Fila, 1 worker (jobs/s) | 393,2 | 344,6 | 338,0 |
| Fila, 4 workers (jobs/s) | 302,0 | 324,6 | 346,5 |
| Jobs concluídos duas vezes | 0 | 0 | 0 |
| Pipeline real: referências processadas | 82 | 1.000 | 1.000 |
| Pipeline real (ms/referência, 4 etapas) | 25,6 | 24,5 | 26,6 |
| Taxonomia nova: replanejar (s) | 0,106 | 1,69 | 1,889 |
| Taxonomia nova: reprocessar (s) | 1,226 | 15,564 | 15,628 |
| Pipeline completo, para comparar (s) | 2,099 | 24,474 | 26,617 |
| `index` reaproveitado após a taxonomia nova | 82 | 1.000 | 1.000 |
| Busca categoria + texto (ms) | 0,38 | 1,819 | 1,504 |
| Busca sem resultado (ms) | 0,011 | 0,011 | 0,011 |
| Busca por tipo de evidência (ms) | 0,653 | 0,773 | 0,696 |
| Conhecimento: processos de automação (ms) | 0,076 | 0,237 | 0,235 |
| Conhecimento: ferramentas mencionadas e não demonstradas (ms) | 0,216 | 0,562 | 0,326 |
| Listagem, 1ª página (ms) | 0,201 | 0,346 | 0,232 |
| Listagem com texto (ms) | 0,103 | 0,587 | 0,466 |
| Listagem completa (páginas / ms) | 1 / 0,408 | 10 / 6,82 | 100 / 51,192 |
| Retomada: jobs presos / ms | 82 / 7,558 | 1.000 / 54,119 | 1.000 / 75,762 |
| Eventos despachados / ms por evento | 82 / 0,313 | 1.000 / 0,364 | 10.000 / 0,329 |
| Tamanho do banco (MB) | 1,03 | 7,57 | 72,4 |
| Pico Python na ingestão (MB, `tracemalloc`) | 0,03 | 0,09 | 0,09 |

## Defeito de escala encontrado por este benchmark (D-BE2, corrigido)

A primeira rodada, com 82 e 1.000 referências, mostrou degradação com o tamanho:

| Métrica | 82 | 1.000 (antes) | 1.000 (depois da BE005) | 10.000 (depois) |
|---|---|---|---|---|
| Fila, 1 worker (jobs/s) | 501 | **93** | 345 | 338 |
| Planejamento (ms/referência) | 1,6 | **4,6** | 1,8 | 2,0 |
| Pipeline real (ms/referência) | 21,6 | **45,0** | 24,5 | 26,6 |

Havia duas causas, confirmadas por `EXPLAIN QUERY PLAN`:
1. O `claim` avaliava TODOS os jobs elegíveis com `NOT EXISTS` sobre as dependências e ordenava numa árvore temporária a cada chamada: 6,9 ms com 4.000 jobs.
2. A deduplicação usava `state IN (...)`, que não casa com o predicado do índice parcial de `dedup_key`, e varria os jobs ativos.

Correção: migração BE005 com a coluna `blocked_deps` (dependências pendentes, mantida pela fila) e o índice parcial `idx_be_jobs_claim`, na ordem do claim; deduplicação reescrita com o mesmo predicado do índice. O `claim` passou a 0,012 ms. A regressão é coberta por `tests/test_queue.py::QueryPlanTest`.

## Leitura e limitações

- **A vazão da fila ficou plana entre 1.000 e 10.000 referências** (cerca de 340 jobs/s). Cada job custa três transações (`claim`, `mark_running`, `complete`, esta com resultado e evento).
- **Quatro workers não aumentam a vazão da fila em si.** SQLite tem um escritor por vez, e as threads disputam a GIL. Paralelismo compensa quando a etapa espera E/S ou ferramenta externa (ffmpeg, whisper), não para o custo de controle.
- **O custo real por referência vem do núcleo** (normalizar, classificar e salvar no ii_mm): cerca de 25 ms para 4 etapas com dados sintéticos pequenos. Com transcrições longas e muitas observações, será maior. Medir no Windows.
- **Corte antecipado comprovado:** com taxonomia nova, `classify` refaz e `index` é reaproveitado em 100% dos casos (classificação idêntica); o reprocessamento custou cerca de 60% do pipeline completo.
- **Ingestão em lote:** cerca de 2 ms por registro, dominados pelo commit por registro (uma transação cada, de propósito). Uma ingestão em lote numa transação seria mais rápida, mas perderia o isolamento de falha por registro. Não foi feita.
- **Consultas nos tamanhos 1.000 e 10.000** foram medidas sobre 1.000 referências analisadas (pipeline limitado a 1.000). A busca do catálogo com 10.000 análises já foi medida no núcleo (`proposals/multimodal_v2/BENCHMARK.md`).
- **Memória:** o `tracemalloc` mostra que a ingestão não acumula objetos Python (pico abaixo de 0,1 MB). O uso de memória do processo, incluindo o cache do SQLite, não foi medido.

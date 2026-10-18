# Benchmark com dados sintéticos (Tarefa 17)

**Aviso:** 82, 1.000 e 10.000 são cargas de teste, não o tamanho real do catálogo. Os números valem só para o ambiente abaixo e não garantem desempenho em produção (o Windows tem outro sistema de arquivos, outro antivírus e outra versão do SQLite).

- Dados brutos: `benchmarks/resultados_benchmark.json`
- Reproduzir: `python3 tools/benchmark.py --sizes 82,1000,10000 --seed 7`

## Ambiente

| Item | Valor |
|---|---|
| SO | Linux 6.18 x86_64 (container de nuvem) |
| CPU / RAM | 4 vCPU / 16 GB |
| Python / SQLite | 3.13.16 / 3.45.1 |
| Banco | arquivo temporário em disco, WAL, `foreign_keys=ON` |
| Pico de RSS do processo | 521,6 MB (dominado pelos 10.000 documentos mantidos em memória pelo próprio benchmark) |

## Metodologia

1. Gerar N documentos com `synthetic.make_reference(i, seed=7)` e classificá-los com `Classifier`.
2. Inserir um por um com `Repository.save_analysis`, uma transação por análise (o caso realista de chegada incremental).
3. Reenviar 10% idênticos (precisa dar no-op) e 5% com variante de URL (precisa colapsar na mesma chave).
4. Consultas com mediana de 5 execuções e página de 50: primeira página, página do meio por cursor e o mesmo ponto com OFFSET, e filtros.
5. Varredura do catálogo inteiro: paginada (100 por página) versus `fetchall` dos documentos, com `tracemalloc`.
6. Retomada: pipeline de 9 etapas em até 1.000 vídeos, queda simulada (`KeyboardInterrupt`) na metade, nova execução, e uma terceira execução que não deve fazer nada.

## Resultados

| Métrica | 82 | 1.000 | 10.000 |
|---|---|---|---|
| Classificação (ms/doc) | 0,71 | 0,66 | 0,88 |
| Inserção (ms/doc) | 2,99 | 3,22 | 3,73 |
| Tamanho do banco (MB) | 0,8 | 8,2 | 81,5 |
| Evidências gravadas | 203 | 2.481 | 24.994 |
| Análises duplicadas após reenvios | 0 | 0 | 0 |
| Primeira página (ms) | 0,38 | 0,36 | 0,43 |
| Página do meio: cursor (ms) | 0,33 | 0,41 | **0,58** |
| Página do meio: OFFSET (ms) | 0,13 | 0,40 | **3,71** |
| Filtro por categoria + apoio mínimo (ms) | 0,30 | 0,59 | 0,70 |
| Filtro por assunto (termos) (ms) | 0,26 | 0,56 | 0,72 |
| Filtro sem resultado: varredura completa (ms) | 0,07 | 2,0 | 24,1 |
| Varredura paginada: tempo / pico de memória | 2 ms / 0,1 MB | 29 ms / 0,3 MB | **318 ms / 0,3 MB** |
| `fetchall` de documentos: tempo / pico | 13 ms / 1,3 MB | 170 ms / 15,9 MB | **4.463 ms / 159 MB** |
| Retomada: execuções repetidas após a queda | 1 | 1 | 1 |
| Reexecução com tudo concluído: etapas executadas | 0 | 0 | 0 |

## Leitura

- **A paginação por cursor tem custo quase constante.** Com 10.000 registros, o cursor fica em 0,58 ms contra 3,71 ms do OFFSET no meio do catálogo, e a diferença cresce com a posição. Com cargas pequenas, o OFFSET é igual ou até mais rápido; a vantagem só aparece com volume.
- **Memória:** percorrer o catálogo página a página mantém cerca de 0,3 MB de pico em qualquer carga. Carregar tudo de uma vez (o padrão de `list_studio_catalog` no legado) chegou a 159 MB e 4,5 s com 10.000 registros.
- **Deduplicação e retomada:** nenhuma duplicata nos reenvios. Na retomada, só a etapa interrompida roda de novo, e uma reexecução sobre tudo concluído não executa nada.
- **Limite conhecido:** um filtro muito seletivo ou sem resultados percorre o índice de referências até preencher a página (24 ms com 10.000 registros neste ambiente). Para catálogos muito maiores, o próximo passo é escolher a ordem de varredura pelo filtro mais seletivo (por exemplo, partir de `tools(name)`).
- **Inserção:** cerca de 3,7 ms por análise com uma transação cada, o que dá uns 37 s para 10.000. Importações em lote podem agrupar transações se precisarem de mais velocidade.

## Defeito encontrado pelo benchmark (corrigido)

A primeira execução com 10.000 registros não terminou em 10 minutos. O `EXPLAIN` mostrou que a subconsulta que localiza a análise corrente fazia `SEARCH a USING INDEX idx_analyses_current (status=?)`: percorria **todas** as análises correntes para cada referência visitada, um custo O(N²).

A correção força a ordem `ref_videos → analyses` com `CROSS JOIN`, e o plano passa a usar `(status=? AND video_pk=?)`. Com 3.000 registros, a página 2 por cursor caiu de 30,9 ms para 0,74 ms e a busca por assunto de 383,6 ms para 5,2 ms. O teste `test_current_analysis_lookup_is_per_reference_not_global` trava o plano correto.

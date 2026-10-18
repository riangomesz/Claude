# Relatório: Missão Suprema 02 (validação adversarial, compatibilidade e handoff)

Branch: `claude/instagram-intelligence-audit-4ezsd1` (`riangomesz/Claude`). Ponto de partida: `6005134`.
`main` intocada (`34ee777`). Nenhum merge, nenhum PR. O clone do Projeto-MVP (`c6845a4`) termina sem nenhum arquivo ou diretório novo. Nenhum modelo externo, serviço pago, banco real, workflow n8n ou Vault foi usado.

## 1. Resumo executivo

O núcleo `ii_mm/` foi auditado de forma adversarial. Resultado: **18 defeitos reproduzidos e corrigidos**, cada um com teste que falhava antes da correção. Também ficou pronta uma camada de compatibilidade com o Projeto-MVP real (adaptadores legados, modo sombra somente leitura e matriz de compatibilidade) e um pacote de integração verificável por hash, com plano em três estágios.

- O terceiro estágio (adoção) **não** está autorizado: depende de avaliação humana.
- A segunda análise visual do `DQV5dm6gCvH` segue **BLOQUEADA**: verificação única, anexos vazios.

| Indicador | Missão 01 | Missão 02 |
|---|---|---|
| Testes (com clone) | 220 | **307** (todos OK) |
| Testes (sem clone) | 216 OK + 4 pulados | 297 OK + 10 pulados |
| Defeitos corrigidos | 10 | **+18** |
| Achados no legado (documentados, sem alteração) | 3 | 6 (L1 a L6) |
| Hipóteses de defeito refutadas por experimento | — | 2 (S6, deadlock por conexão aninhada) |

## 2. Correções implementadas (todas com teste que falhava antes)

| # | Etapa | Defeito | Correção |
|---|---|---|---|
| A1 | A | NFC/NFD geravam evidências diferentes | `contract.nfc` no ID e no texto; adaptadores em NFC |
| A2 | A/T03 | 3 quadros amostrados "provavam" mecanismo de movimento e sustentavam categoria visual | `temporal_variation` observada + mecanismo como `inference`; `temporal_sequence` só com `video_clip`; o contrato recusa tag de movimento observada sem trecho contínuo |
| A3 | A | Revisão humana herdada por categoria com outras evidências | `stale_review_ref`, estado volta a `pending` |
| A4 | A | Alias de URL podia apontar para chave de outra referência | Alias recusado e issue de conflito |
| A5 | A | Documento salvo com `reference_id` diferente do registro | ID registrado + `original_reference_id` |
| A6 | A/T02 | Markdown/HTML da transcrição ativo na nota (imagem remota, `<img>`, wikilink) | `_esc` neutraliza `< > [ ] \` * _ \| &` |
| A7 | A/T02 | Nome reservado do Windows (`CON`, `AUX.x`) | Prefixo e hash |
| A8 | A/T02 | IDs que diferem só na caixa colidiam em NTFS | Sufixo de hash |
| A9 | A/T02 | Exceção do executor derrubava o gateway (risco de vazar caminho local) | `TRANSIENT` só com o nome da classe |
| A10 | A/T02 | Corpo de missão sem limite | 256 KB antes da assinatura |
| A11 | A/T02 | Adaptadores sem limite de registros ou texto | `MAX_RECORDS`, `MAX_TEXT_CHARS` |
| A12 | A/T02 | Chave de primeiro nível digitada errado era aceita | Lista de chaves + prefixo `x_` |
| A13 | T03 | Interface reconhecida pela aparência contava como identificação da ferramenta | Só nome/logotipo legível identifica; fonte `external_knowledge` |
| C1 | T09 | Dois executores rodavam a mesma etapa (6 etapas duplicadas reproduzidas) | Posse e lease (M008), estado `busy` |
| T08 | T08 | Filtro sem valor existente varria o catálogo | Checagem de existência por índice |
| F1 | T07 | Fixture legada criava `storage/imports/*` dentro do clone | Redirecionamento + teste de isolamento numa cópia (as pastas vazias que ela criou foram removidas com `rmdir`) |
| M1 | T04 | Mapeamento de `instagram_items` assumia 49 colunas; o DDL real tem 65 | Mapeamento completo (20 mapeadas, 45 preservadas, 0 sem destino); `media_sha256` vira identidade de conteúdo |
| W1 | T14 | Manifesto do pacote invalidado por CRLF no Windows | Hash com LF normalizado + `proposals/.gitattributes` |

Também foram ajustados de forma explícita, com comentário apontando a regra, os testes da Missão 01 que codificavam as regras revistas: A2 (movimento), A7/A8 (nomes de arquivo) e A13 (identificação de ferramenta).

**Hipóteses refutadas** (registradas para não serem refeitas):
- S6: ffprobe com `avg_frame_rate` "0/0" já era tratado.
- Deadlock em `undo_triage_decision` → `restore_item_from_trash` (conexão aninhada): o código real concluiu em 0,01 s, sem `database is locked`.

## 3. Compatibilidade com o Projeto-MVP

Detalhes em `MATRIZ_COMPATIBILIDADE.md`. Em resumo:
- Esquema real de `instagram_items` com 65 colunas, conferido em banco temporário montado pelo próprio código do clone.
- Quatro adaptadores legados (`ii_mm/legacy.py`): linha `instagram_items`/`InstagramItem`, `VisualMacroAnalysis` (simulação recusada), candidatos do `temporal_intelligence` e ficha `ii.intelligence.card.v1/v2`.
  - Nenhum reclassifica em silêncio: decisões humanas legadas vão para `human_decisions`.
  - Têm reverso parcial (`to_legacy_fields`).
- **Modo sombra** (`ii_mm/shadow.py`): leitura `mode=ro` e zero gravações, com divergências e as evidências responsáveis. Inspeção contra rótulo humano sem taxa de acerto. Com a função legada real, ele reproduz o defeito "robotics → Automação".
- **NÃO VERIFICADO:** estado local do Antigravity além de `c6845a4`, valores reais de `tipo` da Fase 5 e `review_server` em execução.

## 4. Persistência, desempenho e recuperação

- **L1 medido:** no Python 3.13, `with sqlite3.connect()` deixa a conexão viva até o GC de ciclos. As 25 ocorrências legadas precisam de correção. Patch demonstrativo em `patches/legacy_close_sqlite_connections.diff`: gerado e validado numa cópia, com 0 conexões vivas, e **não aplicado**. O próprio `ii_mm` não deixa conexão viva (teste com a demonstração completa).
- **Recuperação testada:** falha no meio da migração (rollback total), `KeyboardInterrupt` durante a gravação (rollback, banco utilizável), exportação interrompida (sem temporários, recupera), reenvio de missão (replay), mesma publicação com outra URL (mesma missão), revisões sucessivas (histórico completo), concorrência (lease; 4 threads gravando, `integrity_check` ok).
- **Ponta a ponta final** (`tests/test_ms02_e2e.py`): queda no meio da classificação → reenvio retoma na etapa interrompida → URL alternativa reaproveitada → revisão humana → segunda missão conclui e exporta → reenvio não reexecuta e a nota não muda. Fecha com 1 referência, 1 análise, 1 revisão, 2 missões e integridade ok.

## 5. Inteligência audiovisual

- **T10:** 10 cenários combinados passaram sem mudança de código (sem legenda com visual; ferramenta citada sem interface; interface sem nome; cinematográfico sem fala; tutorial sem ferramenta; publicidade com cara de tutorial; motion só sugerido; corte sem técnica; várias categorias; contradição).
- **T11:** `ii_mm/quality.py` aponta lacunas de amostragem (reproduz o padrão 19 a 49 s com tempos sintéticos), duplicatas, sobreposições, ausência de transcrição, VFR, dessincronia A/V e grade de quadros. Sem porcentagens.
- **T12:** `ii_mm/technique_library.py` responde às 5 consultas pedidas, preservando origem e limites. As ideias de reprodução saem rotuladas como `proposta_criativa`.

## 6. Testes

| Execução | Resultado |
|---|---|
| `python3 run_tests.py` | 307 executados: **297 OK, 10 pulados, 0 falhas** |
| `PROJETO_MVP_DIR=<clone> python3 run_tests.py` | **307 OK** |
| `python3 -W error::ResourceWarning run_tests.py` (sem clone) | OK (nenhuma conexão vazada pelo `ii_mm`) |
| Novos na Missão 02 | 87 testes em 10 módulos novos; 2 módulos existentes ajustados (`test_n8n_contract`, `test_migrations`) e testes da Missão 01 revistos para as regras A2, A7, A8 e A13 |
| Cobertura de linhas (stdlib `trace`, sem clone) | 89% a 100% por módulo do `ii_mm` (menores: `adapters` 89,1%, `contract` 89,2%) |

Os 10 testes pulados sem clone são os opt-in que exigem `PROJETO_MVP_DIR`: regressão, DDL real, sombra com a função real, vazamento de conexões legadas, isolamento da fixture e reprodução do `no such table`.

## 7. Benchmark

`python3 tools/benchmark.py --sizes 82,1000,10000` → `benchmarks/resultados_benchmark_ms02.json`. Comparação com a Missão 01 por `tools/compare_benchmarks.py`.

Mesmo tipo de ambiente (container Linux, 4 vCPU, 16 GB, Python 3.13.16, SQLite 3.45.1), mas **execuções diferentes**: diferenças menores que ~20% estão dentro do ruído observado. Números sintéticos, sem garantia de desempenho no Windows ou em produção.

| Métrica (10.000 registros) | Missão 01 | Missão 02 | Leitura |
|---|---|---|---|
| Classificação (ms/doc) | 0,88 | 0,90 | ruído (A1/A2/A13 acrescentam pouco) |
| Inserção (ms/doc) | 3,73 | 3,85 | ruído (+3%; checagem de alias e NFC) |
| Primeira página (ms) | 0,43 | 0,35 | ruído |
| Página do meio: cursor / OFFSET (ms) | 0,58 / 3,71 | 0,34 / 2,92 | cursor segue ~8× mais rápido no meio do catálogo |
| Filtro sem resultado (ms) | 24,07 | **0,006** | correção T08 (checagem de existência por índice) |
| Varredura paginada: tempo / pico | 318 ms / 0,30 MB | 310 ms / 0,30 MB | igual |
| Duplicatas após reenvios | 0 | 0 | igual |
| Retomada: execuções repetidas | 1 | 1 | igual (só a etapa interrompida) |

Nenhuma regressão de desempenho foi registrada. Os planos de consulta continuam travados em teste (sem `TEMP B-TREE`; busca da análise corrente por `(status, video_pk)`).

## 8. Vulnerabilidades e riscos

Tabela completa em `RISCO_E_ROLLBACK.md`. As mais relevantes, todas corrigidas no `ii_mm`:
- injeção de Markdown/HTML com imagem remota, que vazaria privacidade ao abrir a nota;
- colisão de nomes no NTFS;
- gateway sem limite de corpo e vazando exceções;
- execução duplicada sem lease;
- poluição do projeto pela fixture.

No legado (só documentado): L1 a L6.

## 9. Evidências que continuam faltando

Pacote `pacote_analise_2` do `DQV5dm6gCvH`: 12 JPEG, `manifesto_pacote.json`, `perguntas_de_verificacao.json`, `segmentos_transcricao.json` e `cortes_detectados.json`; `ficha_inteligencia_v2.json` é opcional. A verificação foi única nesta missão. `analise_multimodal_v2.json` permanece `blocked_missing_evidence`.

Quando o pacote chegar, o caminho já existe: `verify_package.py` → `adapters` → `legacy.from_intelligence_card` (ficha v2) → `Normalizer` → `Classifier` → `quality.temporal_quality` → relatório.

## 10. Passos exatos para o Antigravity

1. `git fetch origin claude/instagram-intelligence-audit-4ezsd1` e copiar `proposals/` para fora do projeto.
2. `cd proposals/multimodal_v2 && python3 tools/build_handoff.py --check`: deve dizer `pacote ok`.
3. `python3 run_tests.py`: 297 OK e 10 pulados.
4. `PROJETO_MVP_DIR=<clone local> python3 run_tests.py`: 307 OK. Registrar qualquer falha (indica diferença do estado local).
5. Conferir `FICHA_TIPO_TO_TAG` e `HUMAN_EDITORIAL_SOURCES` em `ii_mm/legacy.py` com os dados reais.
6. Estágio 2: `python3 handoff/exemplo_uso.py --legacy-db <catalog.sqlite> --out <pasta fora do Vault> --limit 200` e revisar `relatorio_sombra.md` com o curador.
7. Decidir, separadamente, sobre o patch L1 (`patches/legacy_close_sqlite_connections.diff`, ou gerar no Windows com `tools/make_legacy_close_patch.py`).
8. Não avançar ao Estágio 3 sem o registro da revisão humana e decisão explícita (`PLANO_INTEGRACAO_SEGURA.md`).

## 11. Commits

| Commit | Conteúdo |
|---|---|
| `7996db2` | Etapa A: 13 defeitos (A1 a A13) |
| `aef819c` | Etapa B: matriz, adaptadores legados, modo sombra |
| `1b14434` | Etapa C: SQLite (L1 medido, patch), lease, recuperação, filtros sem resultado, isolamento da fixture |
| `509ca80` | Etapa D: cenários, qualidade temporal, biblioteca de técnicas |
| `37bafbd` | Etapa E/G: ponta a ponta, pacote `handoff/`, plano, riscos, benchmark e este relatório |

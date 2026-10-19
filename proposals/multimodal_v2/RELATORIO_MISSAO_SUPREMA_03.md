# Relatório: Missão Suprema 03 (Release Candidate e integração supervisionada com o Antigravity)

Data: 2026-10-19. Branch: `claude/instagram-intelligence-audit-4ezsd1` (isolada).
- `main` intocada: `34ee777`.
- Clone do Projeto-MVP intocado: `c6845a4`, `git status` vazio, nenhuma pasta criada.
- Nenhum merge, PR ou tag.

## 1. Resultado

| Item | Estado |
|---|---|
| Release Candidate | **`ii_mm-1.0.0-rc1` pronta para o Estágio 1 no Windows** (`ii_mm.__version__ = "1.0.0rc1"`, sem tag pública) |
| Commit do código da RC | `d0e1916099bc945a7e8478a4d14b55c919ce4c40` |
| SHA-256 do manifesto (LF) | `10f0e9d88afaa435f5ad1e4899bcb6b942fff812f9831554c34671898e75e209` (119 arquivos) |
| Zip determinístico | `355a0c2568251d902c20651b3c323fc18b9172fa47759e0a2b9cae7c3f0f6678` (zlib 1.3; o hash do manifesto é o que vale entre ambientes) |
| Testes | 384: 371 OK + 13 pulados sem o clone; 384 OK com cópia do clone, em 3.11.17, 3.12.3 e 3.13.16 |
| Windows | **Não testado em Windows real.** Conferido estaticamente; script PowerShell executado com pwsh 7.4.6 no Linux |
| Piloto `DQV5dm6gCvH` | `blocked_missing_evidence` (anexos ausentes na verificação única do início; nenhum substituto buscado) |
| Integração ao Projeto-MVP | **Não feita e não autorizada.** Estágio 3 exige decisão humana escrita |

Entregáveis:
- `HANDOFF_ANTIGRAVITY_RELEASE_CANDIDATE.md`;
- `PROMPT_ANTIGRAVITY_VALIDACAO_ISOLADA.md`;
- este relatório.

## 2. Etapas

| Etapa | O que foi feito | Evidência |
|---|---|---|
| 01 Inventário | Gerado por AST (`tools/inventory.py`); `build_handoff.py` o mantém atualizado; teste falha se um módulo ficar sem descrição | `INVENTARIO_COMPONENTES.md`, `test_ms03_docs` |
| 02 Baseline independente | No início: 307/307 em 3.11, 3.12 e 3.13 contra uma **cópia** do clone. Nenhuma alteração involuntária, nenhum arquivo não rastreado, manifesto da Missão 02 coerente. Achado: o pacote da Missão 02 não era autossuficiente (D-RC1) | Seção 4 |
| 03 Dependências Windows | Requisitos, 7 problemas corrigidos com teste, conferência estática, lista explícita do que não foi verificado | `DEPENDENCIAS_WINDOWS.md` |
| 04 Pacote | Manifesto `ii.handoff_manifest.v2` (rc_id, requisitos, pastas gerenciadas, hash LF por arquivo), JSON Schemas gerados do código, zip determinístico. O zip extraído roda a própria suíte | `tools/build_handoff.py`, `test_ms03_receiver`, `test_ms03_schemas` |
| 05 Validador do receptor | Só stdlib; não importa o `ii_mm` e não grava. Detecta arquivo ausente, modificado ou extra, manifesto ilegível, de versão desconhecida ou diferente do hash publicado, rc_id inválido, Python, SQLite ou módulo insuficiente, caminhos perigosos no Windows e `managed_dirs` fora do pacote | `handoff/verificar_recebimento.py`, 10 testes adversariais |
| 06 Guia PowerShell | Seções A a F e `ii_rc.ps1` com marcador de pasta e recusas. Executado etapa por etapa e com `-Etapa Tudo` | `GUIA_WINDOWS_POWERSHELL.md` |
| 07 Adaptadores legados | Revalidados contra a cópia do clone: 65 colunas, 13 módulos, valores literais reais. Origem editorial revalidada (D-RC2). Baseline de contratos para o Windows | `tools/compat_report.py`, `handoff/baseline_contratos_c6845a4.json` |
| 08 Modo sombra | Origem `mode=ro`, snapshot pela API de backup (em blocos, com prazo; D-RC5), relatório com origem de cada classificação, CSV de revisão com fórmulas neutralizadas, Markdown escapado (D-RC3), decisões humanas preservadas | `test_ms03_shadow` (8 testes) |
| 09 Critérios de adoção | C1 a C10 com verificação, evidência e bloqueio; nada automático | `CRITERIOS_ADOCAO.md` |
| 10 Generalização | 12 formatos (apresentador sem b-roll, cinematográfico sem fala, tutorial de tela, legendas com cortes rápidos, demo de software, portfólio, anúncio físico, motion abstrato, educativo, referência estética, sem metadados, evidência contraditória). Nenhuma constante do piloto no núcleo | `test_ms03_generalization` |
| 11 Distinções | Assunto × ferramenta citada × ferramenta identificada visualmente × técnica observada × técnica inferida × processo demonstrado × promessa comercial × conhecimento transferível × referência estética. Sem porcentagens | `CategorizationDistinctionsTest` |
| 12 Avaliação humana | Amostra estratificada de 30 a 50, planilha cega, validação dos rótulos, concordância em contagens (taxa só com n ≥ 30); CLI `tools/avaliacao.py`. **Nenhum resultado fabricado** | `AVALIACAO_HUMANA.md`, `test_evaluation` |
| 13 Concorrência | Lease, expiração, retomada, reenvio, idempotência, execução simultânea, falha transacional, preservação de análise anterior e do histórico de curadoria, em bancos temporários. D-RC4 corrigido | `test_ms03_lease`, `test_ms02_recovery`, `test_ms02_e2e` |
| 14 Consultas | Plano de **todas** as 66 consultas de um fluxo real (gravar, reprocessar, revisar, histórico): nenhuma varredura de tabela que cresce; ordenação em memória só sobre uma referência. Benchmark só onde se justificava: snapshot (D-RC5) e comparação geral (seção 5) | `test_ms03_queries` |
| 15 Exportação | O núcleo não importa `subprocess`/`pickle` nem chama `eval`/`exec`/`os.system` (verificação por AST). Metadados hostis não escapam do staging, não injetam frontmatter, HTML, wikilink nem fecham o bloco do curador. URIs de missão com `..`, unidade, ADS, dispositivo, ponto final ou UNC são recusadas | `test_ms03_export_security` |
| 16 Piloto | Verificação única no início: anexos vazios. Segue `blocked_missing_evidence` | `INVENTARIO_EVIDENCIAS_FALTANTES.md` |
| 17–19 Entrega | Handoff (12 pontos), prompt do Antigravity, checklist por estágio | Arquivos na raiz de `multimodal_v2/` |
| 20–22 Final | Validação final, RC identificada, commits pequenos, este relatório | Seções 4 e 9 |

## 3. Defeitos reais corrigidos (cada um com teste que falhava antes)

| # | Defeito | Correção |
|---|---|---|
| D-RC1 | Pacote da Missão 02 sem os testes v1, o golden e o marcador do piloto; depois, sem a baseline de contratos (achado pelo próprio validador) | Lista do pacote; autoteste do zip extraído |
| D-RC2 | `editorial_category` com origem nula ou desconhecida tratada como rótulo automático | Só `AUTOMATIC_EDITORIAL_SOURCES` é automático |
| D-RC3 | Injeção de HTML/Markdown no relatório do modo sombra | `_esc` e CSV com fórmulas neutralizadas |
| D-RC4 | Lease vencia durante etapa longa e o executor antigo sobrescrevia o novo dono | `heartbeat()`, `LeaseLost`, conferência de posse |
| D-RC5 | Snapshot em passo único bloqueava escritores do legado durante a cópia inteira (1,7 s para 139 MB) | Cópia em blocos e prazo de 120 s. Com escritor a cada 0,2 s, a maior espera caiu para 0,18 s |
| W2–W6 | `resource` no benchmark, caminho POSIX, symlink sem privilégio, encoding implícito (5 casos), URIs com ADS, dispositivo ou ponto final | `DEPENDENCIAS_WINDOWS.md`, seção 2 |
| PS1 | `.ps1` em UTF-8 sem BOM: o Windows PowerShell 5.1 leria o travessão como aspa | Script em ASCII; teste |
| PS2 | `Invoke-Py` misturava a saída do Python ao código de saída; um único executável virava string (`$py[0]` = `p`); stderr interromperia o 5.1 | `@()`, `Write-Host`, `ErrorActionPreference` local |
| V1 | Validador importava `sqlite3` no topo (quebra sem a DLL) e varreria qualquer `managed_dirs` do manifesto | Importação protegida; `managed_dirs` validadas |
| Doc | Versões testadas registradas erradas (3.11.15/3.12) e contagens antigas (307, "6 testes opt-in") nos documentos do pacote | 3.11.17/3.12.3/3.13.16 e contagens atuais |

## 4. Testes e comparação com a baseline

| Execução | Missão 02 (baseline) | Missão 03 (RC) |
|---|---|---|
| Sem o clone | 307 testes: 297 OK e 10 pulados | 384 testes: 371 OK e 13 pulados (3 versões) |
| Com cópia do clone `c6845a4` | 307 OK | 384 OK (3 versões) |
| Python | 3.13 (relatório); 3.11 a 3.13 na baseline independente | 3.11.17, 3.12.3, 3.13.16 |
| `-W error::ResourceWarning` sem o clone | não medido | OK |
| Pacote extraído rodando a própria suíte | não existia | OK |
| `ii_rc.ps1 -Etapa Tudo` (pwsh 7.4.6, Linux) | não existia | OK (Conferir com hash, Testes com e sem projeto, Compatibilidade, Sombra sobre catálogo sintético com hash da origem inalterado, Limpar) |

Os 77 testes novos estão em `test_ms03_*` (portabilidade, sombra, lease, generalização, receptor, schemas, consultas, exportação, documentos), `test_evaluation` e `test_compat_report`. Nenhum teste existente foi removido, pulado ou enfraquecido. Os 13 pulados sem o clone são os opt-in, que precisam de `PROJETO_MVP_DIR`.

## 5. Desempenho

Comparação **intercalada no mesmo momento** entre o código da Missão 02 (`53aa749`, worktree temporária) e a RC, com 10 000 registros sintéticos e duas rodadas:

| Métrica | M02 rodada 1 | RC rodada 1 | M02 rodada 2 | RC rodada 2 |
|---|---|---|---|---|
| Classificação (ms/doc) | 1,25 | 1,41 | 1,27 | 1,30 |
| Inserção (ms/doc) | 5,58 | 5,14 | 5,28 | 5,45 |
| Página do meio, cursor (ms) | 0,56 | 0,58 | 0,63 | 0,70 |
| Filtro categoria (ms) | 1,12 | 1,03 | 1,12 | 1,20 |
| Filtro sem resultado (ms) | 0,011 | 0,010 | 0,010 | 0,015 |
| Varredura paginada (ms) | 565 | 554 | 536 | 570 |
| Duplicatas após reenvios / execuções repetidas na retomada | 0 / 1 | 0 / 1 | 0 / 1 | 0 / 1 |

As diferenças são pequenas e mudam de direção entre as rodadas: é ruído, **não há regressão**. Uma comparação ingênua com `benchmarks/resultados_benchmark_ms02.json` mostrava a RC de 40% a 80% mais lenta em **todas** as métricas, inclusive em código não alterado. Era a máquina mais lenta neste momento, e por isso a medição intercalada é a que vale. Snapshot (D-RC5): 139 MB em cerca de 1,8 s; espera máxima de um escritor concorrente de 0,18 s. Os resultados não foram gravados em `benchmarks/` (o arquivo da Missão 02 continua como referência).

## 6. Compatibilidade conhecida

- **Com `c6845a4`:** `compat_report` dá compatível; 65 colunas de `instagram_items` mapeadas ou preservadas (nenhuma sem destino); assinaturas de 13 módulos iguais à baseline. Tabela completa em `MATRIZ_COMPATIBILIDADE.md`.
- **Com o estado local do Antigravity:** desconhecida até o Estágio 1. O relatório de compatibilidade foi feito para medir exatamente isso.
- **Windows:** ver `DEPENDENCIAS_WINDOWS.md`, seção 4, para o que não foi verificado.

## 7. Limitações

1. Nenhuma execução em Windows nem em Windows PowerShell 5.1.
2. Dados sintéticos apenas. Nenhuma métrica de acerto foi calculada, de propósito; a primeira medição real é a avaliação humana do Estágio 2.
3. WAL em pasta somente leitura ou sincronizada não verificado (o contêiner roda como root).
4. Valores reais de `tipo` da Fase 5 e de `editorial_category_source` no catálogo local não verificados.
5. O hash do zip depende da versão do zlib; o do manifesto não.
6. A suíte opt-in roda sobre `core/`, `config/` e `temporal_intelligence/` copiados. Módulos legados fora dessas pastas não são exercitados.

## 8. Riscos de integração

| Risco | Mitigação na RC | O que ainda depende do Antigravity |
|---|---|---|
| Estado local diferente de `c6845a4` | `compat_report` com baseline | Analisar cada diferença antes da sombra |
| Snapshot competindo com escrita do legado | Blocos e prazo; origem `mode=ro` | Rodar fora de importação em massa |
| L1 (conexões do legado não fechadas) travando arquivos no Windows | Patch demonstrativo, não aplicado | Decidir sobre o patch como mudança do legado |
| Pistas textuais amplas gerando falso positivo | Modo sombra + avaliação humana | Revisão do curador (C7) |
| Pacote alterado no caminho | Manifesto + hash publicado fora do pacote | Conferir antes de executar |
| Agente local integrando sem decisão | Prompt e checklist proíbem; Estágio 3 só com C10 | Responsável humano |

## 9. Commits desta missão

| Commit | Conteúdo |
|---|---|
| `e2a3cd2` | Portabilidade Windows, cópia descartável do clone, validador de recebimento, schemas, sombra endurecido |
| `9c9f3d7` | Heartbeat de lease, generalização, avaliação humana, relatório de compatibilidade |
| `58253ab` | Pacote autossuficiente, guia PowerShell, critérios, checklist, testes do receptor, consultas e exportação |
| `78f42cd` | Primeiro congelamento (versões de Python corrigidas) |
| `d0e1916` | **Código da RC**: documentos do pacote atualizados (contagens, comandos, D-RC2, riscos da Missão 03) |
| (seguinte) | Handoff, prompt, este relatório e o progresso (fora do manifesto) |

## 10. Próximos passos exatos para o Antigravity

1. Ler `HANDOFF_ANTIGRAVITY_RELEASE_CANDIDATE.md` e colar `PROMPT_ANTIGRAVITY_VALIDACAO_ISOLADA.md` no agente, ajustando as três linhas marcadas.
2. Estágio 1: `-Etapa Conferir` com o hash `10f0e9d8…`, depois `Preparar`, `Testes` (com e sem `-ProjetoMvp`) e `Compatibilidade`.
3. Registrar as diferenças de contrato e conferir `FICHA_TIPO_TO_TAG` e `AUTOMATIC_EDITORIAL_SOURCES` com os dados reais (somente leitura e snapshot).
4. Estágio 2: `-Etapa Sombra` fora de importação em massa; entregar `revisao_divergencias.csv` ao curador; avaliação de 30 a 50 vídeos (`AVALIACAO_HUMANA.md`).
5. Marcar `CHECKLIST_ACEITE_RC.md` e devolver os resultados ao Claude Cloud (HANDOFF, ponto 12). Defeitos do pacote voltam como `rc2`.
6. Estágio 3 só com a decisão escrita do responsável (C10). Nenhum agente pode marcá-lo.

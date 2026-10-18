# Progresso: Missão Suprema 01

Checkpoint persistido. Para retomar, leia este arquivo e rode `python3 run_tests.py` em `proposals/multimodal_v2/`.
Não repita a auditoria inicial: ela está em `BASELINE_ATUAL.md`.

## Estado das frentes

| # | Frente | Estado | Arquivos |
|---|---|---|---|
| 01 | Auditoria e baseline | IMPLEMENTADO / TESTADO | `BASELINE_ATUAL.md`, `run_tests.py`, `tools/stdlib_coverage.py` |
| 02 | Contrato multimodal versionado | IMPLEMENTADO / TESTADO | `ii_mm/contract.py`, `ii_mm/evidence_rules.py`, `ii_mm/synthetic.py`, `fixtures/synthetic_reference_v2.json`, `tests/test_contract.py` |
| 03 | Normalização de evidências | IMPLEMENTADO / TESTADO | `ii_mm/normalize.py`, `tests/test_normalize.py` |
| 04 | Classificador textual v2 | IMPLEMENTADO / TESTADO | `ii_mm/text_classifier.py`, `ii_mm/_matcher.py`, `tests/test_text_classifier.py`; correção em `classification/text_matcher.py` |
| 05 | Classificador multimodal v2 | IMPLEMENTADO / TESTADO | `ii_mm/classifier.py`, `ii_mm/vocabulary.py`, `tests/test_classifier.py` |
| 06 | Migrações SQLite versionadas | IMPLEMENTADO / TESTADO | `ii_mm/db/migrations.py`, `ii_mm/db/legacy_fixture.py`, `tests/test_migrations.py` |
| 07 | Repositório de persistência | IMPLEMENTADO / TESTADO | `ii_mm/db/repository.py`, `tests/test_repository.py` |
| 08 | Deduplicação e proveniência | IMPLEMENTADO / TESTADO | `ii_mm/dedup.py`, `tests/test_dedup.py`, política em `repository.save_analysis` |
| 09 | Processamento idempotente | IMPLEMENTADO / TESTADO | `ii_mm/pipeline.py`, `tests/test_pipeline.py` |
| 10 | Adaptadores áudio/vídeo | IMPLEMENTADO / TESTADO | `ii_mm/adapters.py`, `tests/test_adapters.py` |
| 11 | Estrutura narrativa | IMPLEMENTADO / TESTADO | `ii_mm/narrative.py`, `tests/test_narrative_techniques.py` |
| 12 | Engenharia reversa audiovisual | IMPLEMENTADO / TESTADO | `ii_mm/techniques.py`, `ii_mm/vocabulary.py`, `tests/test_narrative_techniques.py` |
| 13 | Catálogo pesquisável | IMPLEMENTADO / TESTADO | `ii_mm/catalog.py`, migração M006, `tests/test_catalog.py` |
| 14 | Revisão humana | IMPLEMENTADO / TESTADO | `ii_mm/review.py`, migração M005, `tests/test_review.py` |
| 15 | Exportação Obsidian (staging) | IMPLEMENTADO / TESTADO | `ii_mm/obsidian_export.py`, `tests/test_obsidian_export.py` |
| 16 | Contrato n8n | IMPLEMENTADO / TESTADO | `ii_mm/n8n_contract.py`, migração M007, `fixtures/n8n_*_example.json`, `tests/test_n8n_contract.py` |
| 17 | Benchmark sintético | IMPLEMENTADO / TESTADO (smoke) / EXECUTADO | `tools/benchmark.py`, `BENCHMARK.md`, `benchmarks/resultados_benchmark.json` |
| 18 | Demonstração isolada | IMPLEMENTADO / TESTADO | `ii_mm/demo.py`, `tests/test_demo_end_to_end.py` |

## Bloqueio de mídia (registrado uma vez)

Pacote `pacote_analise_2` do DQV5dm6gCvH ausente (`/mnt/user-data/uploads` e `/mnt/attach` vazios, nenhum frame no disco nem nos remotos). `analise_multimodal_v2.json` continua `blocked_missing_evidence`. Não vou buscar de novo nesta missão.

## Log de checkpoints

### C1: Tarefa 01
- Baseline: 33 testes (32 OK, 1 pulado). A divergência com o "27+1" anterior está explicada em `BASELINE_ATUAL.md`.
- Defeitos B1 a B4 reproduzidos (8 de 10 testes novos falham no código antigo) e corrigidos.
- Suíte após a correção: 43 testes, 42 OK e 1 pulado.
- Próxima: Tarefa 02 (contrato v2).

### C2: Tarefas 02, 03, 10 (commit `b08c147`) e 04
- Contrato `ii.reference_analysis.v2` com 6 estados de evidência, fontes permitidas por estado e IDs por conteúdo (resolve B5).
- Adaptadores para os formatos reais do Projeto-MVP (SRT, faster-whisper, `core/transcription.py`, ffmpeg `metadata=print`, `ii.scene_candidates.v1`, ffprobe, manifestos `ii_coverage`, métricas de `temporal_intelligence`).
- Normalizador: proveniência preservada, duplicatas consolidadas (com `also_from`), base visual derivada do número de frames, movimento com 1 ou 2 quadros rebaixado para `inference`.
- T04: termos fortes e fracos, exclusões ("corte de cabelo", "slow motion"), hashtags compostas, faceta de tema IA separada. Os 11 casos sem defeito do golden concordam com o legado e os 6 com defeito divergem de propósito.
- Defeito novo corrigido em `text_matcher.normalize`: pontuação fora do ASCII (travessão, emoji, "…") colava palavras.
- Suíte: 103 testes, 102 OK e 1 pulado (com `PROJETO_MVP_DIR`, todos passam).
- Próxima: T05 (classificador multimodal v2).

### C3: Tarefas 05 a 09
- T05 (commit `977423c`): seis níveis de apoio, contradições, medição só por regra explícita, ferramentas mencionadas versus identificadas visualmente.
- T06: quatro migrações sequenciais, checksum, recusa de esquema mais novo, rollback total, FK e CHECK, recusa de `catalog.sqlite`. Reprodução e correção do `no such table` legado (opt-in com `PROJETO_MVP_DIR`).
- T07/T08: repositório transacional. Mesma entrada vira no-op, entrada nova cria versão (a anterior fica `superseded`), URLs alternativas viram aliases, mesmo conteúdo vira um vídeo só, mesma publicação com outro conteúdo vira conflito bloqueante.
- T09: retomada após interrupção, tentativas limitadas, propagação por hash encadeado, `force`, espera por revisão.
- Achados L1 a L3 sobre o Projeto-MVP registrados em `BASELINE_ATUAL.md`.
- Próxima: T11 (narrativa), T12 (técnicas), T13 (catálogo), T14 (revisão).

### C4: Tarefas 11 a 14
- T11: blocos sugeridos (nunca confirmados) com apoio próprio. Gancho só por posição vira `hypothesis`. Mostra lacunas, sobreposições e tipos ausentes.
- T12: cinco níveis de prova, cada um com "prova" e "não prova". Par de quadros nunca vira `temporal_sequence`.
- T13: cursor keyset. O EXPLAIN mostrou `TEMP B-TREE` (ordenação do conjunto inteiro a cada página) na primeira versão; corrigido com a migração M006 (`idx_refs_created`), percurso por índice e `MAX()` no lugar de `ORDER BY` na subconsulta. O teste trava o plano.
- T14: histórico imutável, estado corrente materializado (M005), concorrência otimista, sobreposição válida pelo contrato. O contrato pegou um caso real (ferramenta "visual" após rebaixar a observação) e o status passou a ser recalculado.
- Próxima: T15 (Obsidian), T16 (n8n), T17 (benchmark), T18 (demonstração e relatório).

### C5: Tarefas 15 e 16
- T15: nota com as 10 seções pedidas, escrita atômica, `unchanged` quando nada muda, bloco de curadoria e chaves `curador_*` preservados, recusa de cofre real (`.obsidian/`), texto de transcrição escapado (não fecha o bloco de curadoria).
- T16: missão e resultado com contrato fechado, `mission_id` ligado ao conteúdo, URIs só relativas (bloqueia `..`, unidade Windows, UNC, http/file), modelos pagos proibidos por padrão, HMAC em tempo constante, gateway idempotente (reenvio devolve o resultado salvo; falha transitória é reexecutada).
- Próxima: T17 (benchmark) e T18 (demonstração e relatório).

### C6: Tarefas 17 e 18
- Benchmark com 82, 1.000 e 10.000 registros executado. O próprio benchmark revelou um O(N²) na busca da análise corrente; corrigido com `CROSS JOIN`, plano travado em teste. Números em `BENCHMARK.md`.
- Demonstração de ponta a ponta com formatos brutos (SRT, stdout do ffmpeg, ffprobe, manifesto de pacote, observações). Revelou o falso positivo "clica no link" virando demonstração; corrigido com exclusões nas pistas narrativas.
- Próxima: documento de integração para o Antigravity e relatório final.

### C7: Encerramento
- Documentos finais: `INTEGRACAO_ANTIGRAVITY.md` e `RELATORIO_MISSAO_SUPREMA_01.md`; nota de atualização em `CLASSIFICACAO_MULTIMODAL.md`.
- Suíte final: 220 testes (216 OK e 4 pulados sem `PROJETO_MVP_DIR`; 220 OK com o clone).
- As 18 frentes estão implementadas. Bloqueado: segunda análise visual do DQV5dm6gCvH (falta o pacote de mídia).
- Para retomar: ler `RELATORIO_MISSAO_SUPREMA_01.md`, seção 11 (próximas tarefas).

---

# Missão Suprema 02: validação adversarial e handoff

Estado inicial confirmado: commit `6005134`, `main` intocada (`34ee777`), clone do Projeto-MVP limpo (`c6845a4`), 220 testes verdes.
T16 (verificação única): `/mnt/user-data/uploads` e `/mnt/attach` vazios, sem frames no disco. O piloto segue `blocked_missing_evidence` e não será verificado de novo nesta missão.

### M2-C1: Etapa A (T01 a T03), 13 defeitos reproduzidos e corrigidos

Método: script de sondagem → teste que falha no código atual → correção localizada → suíte verde. O registro de antes/depois fica no relatório final.

| # | Defeito | Correção |
|---|---|---|
| A1 | Mesmo texto em NFC e NFD gerava evidências diferentes (dedup falhava entre Windows e macOS) | `contract.nfc()` no ID e no texto; adaptadores normalizam em NFC |
| A2 | 3 quadros amostrados "provavam" mecanismo (transição/animação → `temporal_sequence`, categoria `supported_visual`) | Quadros amostrados registram `temporal_variation` observada e o mecanismo como `inference`; `temporal_sequence` exige `video_clip`; o contrato recusa tag de movimento observada sem trecho contínuo |
| A3 | Revisão humana herdada por categoria cujas evidências mudaram | Só herda com o mesmo conjunto de evidências; senão `pending` + `stale_review_ref` |
| A4 | Alias de URL podia apontar para a chave de OUTRA referência (resolução ambígua) | Alias recusado, issue de conflito registrada |
| A5 | Documento salvo com `reference_id` diferente do registro | Grava com o ID registrado e preserva `original_reference_id` |
| A6 | Markdown/HTML da transcrição ativo na nota (imagem remota, `<img>`, wikilink, código) | `_esc` neutraliza `< > [ ] ` * _ | &` |
| A7 | Nome reservado do Windows (`CON`, `AUX.x`) gerava arquivo inválido | Prefixo e hash |
| A8 | IDs que só diferem por maiúsculas colidiam em NTFS | Sufixo de hash do ID exato quando há maiúscula ou alteração |
| A9 | Exceção do executor derrubava o gateway (e poderia vazar caminho local) | Vira `TRANSIENT` só com o nome da classe |
| A10 | Corpo de qualquer tamanho era lido e parseado | Limite de 256 KB antes da assinatura |
| A11 | Adaptadores sem limite de registros e de texto | `MAX_RECORDS=50.000` e `MAX_TEXT_CHARS=10.000`, com erro registrado |
| A12 | Chave de primeiro nível com erro de digitação era aceita (dados somem em silêncio) | Lista de chaves conhecidas; extensões com `x_` |
| A13 | Reconhecer interface pela aparência contava como identificação visual da ferramenta | Só `tool_name_visible`/`logo_visible` identificam; `external_knowledge` vira tipo de fonte (só `inference`) |

Testes antigos que codificavam as regras revistas (A2, A7, A8, A13) foram ajustados explicitamente, com comentário apontando a regra.
Guardas sem defeito (já protegidos, agora travados em teste): escrita através de symlink, staging-symlink para cofre, SQL malicioso nos filtros, hosts sósias (IDN, homóglifo, subdomínio), instrução embutida em transcrição.
Suíte: 244 testes (240 OK, 4 pulados).

### M2-C2: Etapa B (T04 a T06), compatibilidade, adaptadores legados e modo sombra
- T04: `MATRIZ_COMPATIBILIDADE.md` com assinaturas extraídas por AST do clone `c6845a4`. O DDL real de `instagram_items` tem **65 colunas** (a estimativa por regex da Missão 01, de 49, estava errada), descoberto pelo teste opt-in contra o esquema real.
- T05: `ii_mm/legacy.py` com 4 adaptadores (linha `instagram_items`/`InstagramItem`, `VisualMacroAnalysis`, candidatos do `temporal_intelligence`, ficha `ii.intelligence.card.v1/v2`). Aceitam entrada parcial, preservam IDs, listam campos sem destino, não reclassificam (decisões humanas vão para `human_decisions`), têm reverso parcial (`to_legacy_fields`). Simulação do `vision_client` é recusada. `media_sha256` vira identidade de conteúdo.
- T06: `ii_mm/shadow.py`. Leitura `mode=ro` (escrita falha no próprio SQLite), zero gravações, divergências com evidências responsáveis, inspeção de possíveis falsos positivos e negativos contra rótulo humano, sem taxa de acerto. Opt-in com a função legada real reproduz o defeito "robotics → Automação".
- Fixtures: `fixtures/legacy/*.json` (estrutura real, valores sintéticos).
- Suíte: 266 testes (260 OK, 6 pulados sem `PROJETO_MVP_DIR`; 266 OK com o clone).

### M2-C3: Etapa C (T07 a T09), commit `1b14434`
- **L1 confirmado com medição** (`tests/test_ms02_sqlite.py`): no Python 3.13, `with sqlite3.connect() as c` deixa a conexão viva após o retorno até o GC de ciclos (até o caso mais simples). Funções legadas medidas deixam 1 ou 2 conexões vivas; `closing()` zera. As 25 ocorrências precisam de correção (risco: arquivo travado no Windows por tempo indeterminado). Hipótese de deadlock por conexão aninhada (`undo_triage_decision` → `restore_item_from_trash`) **refutada** com o código real (0,01 s).
- Patch demonstrativo `patches/legacy_close_sqlite_connections.diff` (25 trocas + 6 imports), gerado por `tools/make_legacy_close_patch.py` numa cópia temporária e validado (0 conexões vivas). O teste garante que o patch versionado corresponde ao clone.
- **Defeito meu corrigido:** a fixture legada criava `storage/imports/{processed,failed}` dentro do clone (efeito colateral de `ensure_connection_schema`). Pastas vazias removidas com `rmdir`; fixture redireciona para o diretório temporário; teste de isolamento roda sobre uma cópia, em subprocesso.
- C1: dois executores rodavam a mesma etapa (6 etapas duplicadas reproduzidas). Correção: posse e lease em `processing_state` (M008); estado `busy`; lease vencido libera; o mesmo dono retoma. Contrato n8n aceita `busy` → `retry_later`.
- T08: filtro sem valor existente fazia varredura completa. Correção: checagem de existência por índice antes da consulta (não decide inclusão de itens, só existência global).
- Guardas (já corretas): `KeyboardInterrupt` durante a gravação faz rollback, exportação interrompida não deixa temporários e se recupera, 4 threads gravando no mesmo arquivo (160 análises, `integrity_check` ok).

### M2-C4: Etapa D (T10 a T12)
- T10: `tests/test_ms02_scenarios.py` com 10 cenários combinados (sem legenda com visual; ferramenta citada sem interface; interface sem nome legível; cinematográfico sem fala; tutorial sem ferramenta; publicidade com cara de tutorial; motion só sugerido; corte sem técnica; várias categorias; contradição). Todos passaram sem mudança de código: comportamento consistente com as regras.
- T11: `ii_mm/quality.py`, relatório de integridade temporal com código, severidade e intervalo, sem porcentagens: lacuna de amostragem (reproduz o padrão 19–49 s do piloto com tempos sintéticos), duplicatas, sobreposição, ausência de transcrição, VFR, dessincronia A/V, grade de quadros. Adaptador do ffprobe passou a expor `r_frame_rate` e as durações por stream.
- T12: `ii_mm/technique_library.py` com as 5 consultas pedidas. Atributos estruturados de observação com lista fechada (`size`, `position`, `case`, `words_per_caption`, `color`), indexados em `search_terms`. `AI_TOOLS` no vocabulário. O guia de reprodução sai rotulado como `proposta_criativa`.

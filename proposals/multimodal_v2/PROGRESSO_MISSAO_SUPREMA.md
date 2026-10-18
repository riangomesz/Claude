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
| 17–18 | (fila) | PENDENTE | |

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

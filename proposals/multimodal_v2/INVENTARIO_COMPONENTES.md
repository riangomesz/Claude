# Inventário de componentes: `ii_mm-1.0.0-rc1`

Etapa 01 da Missão Suprema 03. A tabela da seção 1 é **gerada** por `python -X utf8 tools/inventory.py` (AST, sem importar nada) e pode ser regenerada a qualquer momento. As seções 2 a 4 descrevem propósito, contratos, compatibilidade e limitações de cada componente. O teste `tests/test_ms03_docs.py` falha se um módulo do `ii_mm` ficar fora deste documento.

**Legenda de status de compatibilidade:**
- **L** = testado no Linux com Python 3.11.15, 3.12 e 3.13.16;
- **W-est** = conferido estaticamente para Windows (sintaxe 3.10, encoding explícito, nenhum módulo POSIX, nomes de arquivo válidos);
- **W** = executado no Windows. **Nenhum componente tem W:** é exatamente o que o Estágio 1 do Antigravity confere.

Dependências externas: **nenhuma**. Todo o `ii_mm` usa só a biblioteca padrão. O único arquivo fora de `multimodal_v2/` é `proposals/classification/text_matcher.py`, carregado por caminho (`ii_mm/_matcher.py`).

## 1. Tabela gerada

| Módulo | Linhas | Depende de (interno) | stdlib | API pública | Testes que o exercitam |
|---|---|---|---|---|---|
| `ii_mm.__init__` | 7 | — | — | — | indireto |
| `ii_mm._matcher` | 12 | — | importlib, pathlib | — | 1 |
| `ii_mm.adapters` | 376 | — | dataclasses, json, math, re, typing, unicodedata | `AdapterResult`, `parse_timestamp`, `transcript_from_segments`, `transcript_from_srt`, `scenes_from_ffmpeg_metadata`, `scenes_from_candidates_json`, `probe_from_ffprobe_json`, `metrics_from_frame_pairs`, `frames_from_manifest`, `observations_from_json` | 13 |
| `ii_mm.catalog` | 190 | _matcher, evidence_rules | base64, dataclasses, json, sqlite3, typing | `QueryError`, `Query`, `Page`, `build_sql`, `search`, `iterate`, `explain` | 4 |
| `ii_mm.classifier` | 182 | __init__, _matcher, evidence_rules, text_classifier, vocabulary | copy, dataclasses, typing | `MeasuredRule`, `ClassifierConfig`, `Classifier` | 12 |
| `ii_mm.contract` | 348 | __init__, evidence_rules, narrative, vocabulary | hashlib, json, math, typing, unicodedata | `ContractError`, `canonical_json`, `nfc`, `evidence_id`, `make_evidence`, `empty_document`, `validate_document`, `assert_valid` | 10 |
| `ii_mm.db.__init__` | 1 | — | — | — | indireto |
| `ii_mm.db.legacy_fixture` | 72 | — | ast, contextlib, importlib, pathlib, sqlite3, sys, typing | `extract_base_ddl`, `build_legacy_catalog` | 3 |
| `ii_mm.db.migrations` | 301 | — | dataclasses, datetime, hashlib, pathlib, sqlite3, typing | `MigrationError`, `IncompatibleSchemaError`, `Migration`, `connect`, `current_version`, `applied`, `migrate`, `open_database` | 12 |
| `ii_mm.db.repository` | 220 | _matcher, contract, dedup | contextlib, copy, dataclasses, datetime, json, sqlite3, typing | `SaveResult`, `Repository` | 8 |
| `ii_mm.dedup` | 106 | contract | hashlib, re, typing, urllib | `IdentityError`, `parse_reference`, `canonical_reference_key`, `file_sha256`, `analysis_input_hash` | 3 |
| `ii_mm.demo` | 150 | adapters, catalog, classifier, contract, db.migrations, db.repository, n8n_contract, narrative, normalize, obsidian_export, review, synthetic, techniques | argparse, json, pathlib, tempfile, typing | `run_demo`, `main` | 3 |
| `ii_mm.evaluation` | 132 | evidence_rules, shadow | csv, pathlib, random, typing | `LabelError`, `select_sample`, `export_labeling_sheet`, `load_labels`, `agreement_report`, `predictions_from_shadow` | 1 |
| `ii_mm.evidence_rules` | 54 | — | typing | `category_support`, `stronger` | 3 |
| `ii_mm.legacy` | 306 | adapters, contract, normalize | dataclasses, json, typing | `LegacyReport`, `from_instagram_item`, `to_legacy_fields`, `from_vision_macro`, `from_transition_candidates`, `from_intelligence_card` | 1 |
| `ii_mm.n8n_contract` | 228 | contract, dedup, pipeline | datetime, hashlib, hmac, json, re, sqlite3, typing | `compute_mission_id`, `validate_mission`, `build_result`, `validate_result`, `sign`, `verify_signature`, `MissionGateway` | 6 |
| `ii_mm.narrative` | 142 | _matcher, contract | typing | `suggest_blocks`, `validate_blocks`, `coverage` | 4 |
| `ii_mm.normalize` | 230 | adapters, contract, vocabulary | typing | `is_motion_tag`, `Normalizer` | 13 |
| `ii_mm.obsidian_export` | 209 | contract, dedup, narrative, techniques | hashlib, json, os, pathlib, re, tempfile, typing | `ExportError`, `assert_staging`, `safe_name`, `render`, `export_reference` | 5 |
| `ii_mm.pipeline` | 197 | — | dataclasses, datetime, hashlib, sqlite3, time, typing, uuid | `LeaseLost`, `StageContext`, `RunReport`, `Pipeline` | 4 |
| `ii_mm.quality` | 91 | — | typing | `temporal_quality` | 1 |
| `ii_mm.review` | 190 | contract, db.repository, evidence_rules | copy, datetime, json, typing | `ReviewError`, `ReviewConflict`, `ReviewService` | 4 |
| `ii_mm.shadow` | 223 | classifier, legacy, obsidian_export, text_classifier | contextlib, csv, json, pathlib, sqlite3, time, typing | `read_legacy_rows_readonly`, `snapshot_readonly`, `export_review_csv`, `compare_row`, `run_shadow`, `render_markdown` | 4 |
| `ii_mm.synthetic` | 83 | contract, evidence_rules | hashlib, random, typing | `sha`, `synthetic_url`, `make_reference` | 21 |
| `ii_mm.technique_library` | 122 | techniques, vocabulary | json, sqlite3, typing | `references_with_technique`, `references_with_caption_style`, `references_with_ai_tool_interface`, `technique_overview`, `reproduction_guide` | 2 |
| `ii_mm.techniques` | 83 | vocabulary | typing | `level_for`, `build_techniques`, `open_questions` | 7 |
| `ii_mm.text_classifier` | 227 | _matcher, evidence_rules | dataclasses, re, typing | `Hit`, `CategoryMatch`, `TextResult`, `detect_language`, `TextClassifier`, `compare_with_legacy` | 1 |
| `ii_mm.vocabulary` | 110 | — | typing | `TagSpec` | indireto |

"Testes que o exercitam" conta os arquivos de teste que importam o módulo diretamente; "indireto" significa que ele é exercitado através de outro módulo (por exemplo, `vocabulary` via `normalize` e `classifier`).

## 2. Núcleo de dados e regras

| Componente | Propósito | Entrada → saída | Status | Limitações conhecidas |
|---|---|---|---|---|
| `contract` | Define e valida `ii.reference_analysis.v2`: 6 estados de evidência, fontes permitidas por estado, IDs de evidência por conteúdo (NFC), chaves de primeiro nível conhecidas mais extensões `x_` | `dict` → lista de erros (`validate_document`) ou `ContractError` (`assert_valid`) | L, W-est | Valida coerência entre estado, base e fonte; **não** verifica se a observação é verdadeira |
| `evidence_rules` | Nível de apoio ordinal de cada categoria (supported_visual > supported_measured > mentioned_speech > suggested_metadata > hypothesis > insufficient) | evidências → nível; sem números de confiança | L, W-est | Ordem é decisão de projeto, não calibrada |
| `vocabulary` | Tags visuais, técnicas e léxico de ferramentas (`TOOL_LEXICON`, `AI_TOOLS`) | constantes | L, W-est | Léxico inicial; ampliar com o curador |
| `adapters` | Converte artefatos **já produzidos** (SRT, segmentos, ffprobe, cenas do ffmpeg, `cortes_detectados.json`, métricas entre quadros, manifestos de quadros, observações `ii.visual_observation.v1`) | JSON/texto → `AdapterResult` (registros + erros) | L, W-est | Limites de 50 000 registros e 10 000 caracteres por texto (excedente truncado e sinalizado). Não executa ffmpeg nem whisper |
| `normalize` | Monta o documento v2 a partir dos adaptadores; aplica a regra de movimento (quadros amostrados geram `temporal_variation` observada e mecanismo como inferência; `temporal_sequence` exige `video_clip`) | `AdapterResult`s → documento v2 | L, W-est | Sem duração da mídia o documento não é montado (bloqueio explícito) |
| `text_classifier` | Classificação textual por pistas (legenda, fala, hashtags) | texto → `TextResult` com hits citáveis | L, W-est | Pistas não calibradas; idioma por heurística |
| `classifier` | Classificação multimodal por evidências: categorias com nível de apoio, ferramentas citadas × identificadas (só nome ou logotipo legível identificam), técnicas | documento v2 → documento v2 classificado | L, W-est | `MeasuredRule` desligada por padrão (limiares não calibrados) |
| `techniques` / `narrative` | Técnicas audiovisuais com nível (observada, inferida, sequência temporal) e blocos narrativos | documento → listas estruturadas | L, W-est | Narrativa por pistas textuais; sem análise de áudio não verbal |
| `quality` | Relatório de integridade temporal (lacunas, duplicatas, sobreposição, VFR, dessincronia A/V) | documento + metadados → `ii.temporal_quality.v1` | L, W-est | Códigos e severidade; sem porcentagens |
| `dedup` | Identidade de referência (URL canônica, shortcode, hash de conteúdo) e hash de entrada de análise | URL/arquivos → chaves | L, W-est | Não reconcilia republicações com mídia reeditada (hash diferente) |

## 3. Persistência, operação e integração

| Componente | Propósito | Entrada → saída | Status | Limitações conhecidas |
|---|---|---|---|---|
| `db.migrations` | Migrações versionadas M001–M008 (M008: posse e lease); WAL; `connect()` recusa `catalog.sqlite` | caminho → conexão migrada | L, W-est | WAL em pasta sincronizada (OneDrive) e permissão somente leitura **não verificados** (contêiner roda como root) |
| `db.repository` | Grava análises de forma idempotente (`BEGIN IMMEDIATE`), preserva análises anteriores, aponta a corrente | documento → `SaveResult` | L, W-est | Banco próprio (`ii_v2.sqlite`), nunca o catálogo legado |
| `db.legacy_fixture` | Monta o esquema legado num banco **temporário** a partir do DDL do Projeto-MVP (por AST) | pasta do projeto (cópia) → banco temporário | L | Só para testes; depende da estrutura de `core/` |
| `catalog` / `technique_library` | Busca paginada por cursor (keyset) por assunto, categoria, ferramenta, técnica, revisão e intervalo de tempo; consultas da biblioteca de técnicas | `Query` → `Page` | L, W-est | Benchmark só com 10 mil registros sintéticos (`BENCHMARK.md`) |
| `review` | Revisão humana com histórico imutável, controle de concorrência otimista (`expected_seq`) e detecção de revisão obsoleta | ação do revisor → histórico | L, W-est | Não decide nada sozinho |
| `pipeline` | Máquina de estados idempotente por etapa, com posse, lease, `heartbeat()` e `LeaseLost` | etapas registradas → `RunReport` | L, W-est | Lease depende do relógio local (várias máquinas exigem relógios sincronizados) |
| `n8n_contract` | Contrato de missão/resultado com HMAC, validação de URIs (inclusive ADS `:`, nomes de dispositivo e ponto final do Windows) e `MissionGateway` | JSON assinado → resultado | L, W-est | Nenhum workflow real foi editado nem executado |
| `obsidian_export` | Exporta notas só para staging (`assert_staging`), com escape de Markdown/HTML e nomes seguros | documento + pasta → nota | L, W-est | Copiar do staging para o Vault continua manual |
| `legacy` | Converte linhas de `instagram_items` (65 colunas), `VisualMacroAnalysis`, candidatos de transição e fichas v1/v2; separa decisões humanas | linha legada → documento v2 + `LegacyReport` | L (com cópia do clone `c6845a4`), W-est | Valores reais de `tipo` da Fase 5 não verificados (`FICHA_TIPO_TO_TAG`) |
| `shadow` | Compara classificação atual × nova sem gravar nada: leitura `mode=ro`, snapshot pela API de backup, relatório JSON/Markdown e CSV para revisão | catálogo (ro) → relatório | L, W-est | Concordância só em contagens; nada é adotado automaticamente |
| `evaluation` | Fluxo de avaliação humana de 30 a 50 vídeos: amostra estratificada, planilha cega, validação de rótulos e concordância | relatório de sombra + rótulos humanos → contagens | L, W-est | Sem rótulos humanos não produz resultado (por desenho) |
| `synthetic` / `demo` | Gerador determinístico de referências sintéticas e demonstração de ponta a ponta num diretório temporário | semente → documentos | L, W-est | **Dados sintéticos não são análise real** |

## 4. Ferramentas, pacote e legado v1

| Componente | Propósito | Status |
|---|---|---|
| `run_tests.py` | Executor único (descobre `tests/`, testes v1 e o matcher) | L, W-est |
| `tools/build_handoff.py` | Gera contratos de exemplo, schemas e o manifesto `ii.handoff_manifest.v2`; `--check` confere; `--zip` monta o pacote determinístico | L |
| `tools/schemas.py` | JSON Schemas gerados das constantes do código e um validador mínimo só com stdlib | L, W-est |
| `tools/compat_report.py` | Compara assinaturas, valores literais e colunas reais do Projeto-MVP com `handoff/baseline_contratos_c6845a4.json` (somente leitura; recusa `--out` dentro do projeto) | L |
| `tools/inventory.py` | Gera a tabela da seção 1 | L |
| `tools/benchmark.py`, `compare_benchmarks.py` | Benchmark sintético; RSS opcional (sem `resource` no Windows) | L, W-est |
| `tools/stdlib_coverage.py`, `make_legacy_close_patch.py` | Cobertura com `trace`; geração do patch L1 numa cópia | L |
| `handoff/verificar_recebimento.py` | Validador de recebimento só com stdlib, sem importar o `ii_mm` e sem escrever | L, W-est |
| `handoff/exemplo_uso.py` | Modo sombra (snapshot por padrão) ou `--demo` | L, W-est |
| `handoff/windows/ii_rc.ps1` | Execução guiada no Windows (Conferir, Preparar, Testes, Compatibilidade, Sombra, Limpar) | Executado com PowerShell 7.4.6 no **Linux**; Windows PowerShell 5.1 **não testado** |
| `patches/legacy_close_sqlite_connections.diff` | Correção demonstrativa de L1 (25 trocas em 6 arquivos do legado) | Validado numa cópia; **não aplicado** |
| `multimodal_classifier.py`, `verify_package.py` e testes v1 | Classificador v1 (Missão Cloud 02) e verificador do pacote do piloto, preservados por compatibilidade | L, W-est |

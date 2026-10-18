# Guia de integração: `ii_mm` → Projeto-MVP (para o Antigravity)

> **Atualização (Missão Suprema 02):** a ordem de adoção foi substituída por `PLANO_INTEGRACAO_SEGURA.md` (três estágios; o terceiro exige decisão humana). Compatibilidade detalhada em `MATRIZ_COMPATIBILIDADE.md`, riscos em `RISCO_E_ROLLBACK.md`. Pacote verificável: `handoff/` (`python3 tools/build_handoff.py --check`). Os números de testes abaixo são da Missão 01.

Status: **proposta isolada, testada com dados sintéticos**. Nada foi aplicado ao Projeto-MVP, ao banco de produção, ao n8n ou ao ambiente Windows. Cada passo abaixo é um patch revisável e reversível.

## 1. O que existe

Pacote `proposals/multimodal_v2/ii_mm/`, só com a biblioteca padrão (testado em Python 3.13; exige SQLite ≥ 3.24 por causa de UPSERT e comparação de tuplas):

| Módulo | Papel | Entrada → Saída |
|---|---|---|
| `adapters.py` | Lê saídas já produzidas (SRT, faster-whisper, `core/transcription.py`, ffmpeg `metadata=print`, `ii.scene_candidates.v1`, ffprobe, manifestos `ii_coverage`, métricas `temporal_intelligence`, observações) | texto/JSON → `AdapterResult(records, errors)` |
| `normalize.py` | Monta o documento `ii.reference_analysis.v2` com proveniência, deduplicação e rebaixamentos | `AdapterResult`s → documento |
| `text_classifier.py` | Texto v2: termos fortes/fracos, exclusões, hashtags compostas | texto → categorias + termos |
| `classifier.py` | Multimodal, multi-rótulo, 6 níveis de apoio, contradições, ferramentas | documento → documento classificado |
| `narrative.py` / `techniques.py` | Blocos narrativos; técnicas em 5 níveis de prova | documento → listas |
| `db/migrations.py` | 7 migrações versionadas, checksum, rollback | conexão → esquema |
| `db/repository.py` | Persistência, versões de análise, aliases, conflitos | documento → `SaveResult` |
| `pipeline.py` | Estados idempotentes com retomada | handlers por etapa → `RunReport` |
| `catalog.py` | Busca com cursor | `Query` → `Page` |
| `review.py` | Decisões humanas com histórico imutável | ações → visão revisada |
| `obsidian_export.py` | Notas em staging, curadoria preservada | documento → `.md` + `.json` |
| `n8n_contract.py` | Missão e resultado, HMAC, gateway idempotente | corpo assinado → resultado |
| `demo.py` | Fluxo completo de exemplo | `python3 -m ii_mm.demo` |

Validação: `python3 run_tests.py` (220 testes) e `PROJETO_MVP_DIR=<clone> python3 run_tests.py` (inclui a regressão contra o código real).

## 2. Ordem de integração recomendada

Cada passo deixa o sistema funcionando e não depende dos seguintes.

1. **Testes primeiro (risco nulo).** Copiar `ii_mm/db/legacy_fixture.py` para os testes do Projeto-MVP e trocar o uso de `catalog.sqlite` real por um banco temporário montado na ordem de `SCHEMA_ORDER`. Isso resolve os testes com `no such table` (L2) sem mexer em código de produção.
2. **Fechar conexões (risco baixo).** Trocar `with sqlite3.connect(p) as conn:` por `with closing(sqlite3.connect(p)) as conn, conn:` nas 25 ocorrências (L1). Elimina travas de arquivo no Windows.
3. **Classificador textual em modo sombra (risco baixo).** Chamar `TextClassifier` ao lado de `curation.suggest_editorial_category` e só registrar as duas saídas. Usar `compare_with_legacy` sobre itens já curados (`triage_decision`, `editorial_category`) para medir a concordância **antes** de trocar qualquer coisa.
4. **Banco novo ao lado do antigo (risco baixo).** Criar `storage/ii_v2.sqlite` com `open_database()`. `connect()` recusa `catalog.sqlite` por padrão. Popular a partir do catálogo legado com um script de leitura (`studio_adapter.get_ro_sqlite_connection` já abre em modo somente leitura).
5. **Pacotes de evidência (risco baixo).** `ii_coverage/fase5.js` já gera `manifesto_pacote.json` e `cortes_detectados.json`. Basta passá-los a `frames_from_manifest` e `scenes_from_candidates_json`. Observações de agente entram no formato `ii.visual_observation.v1` (`adapters.observations_from_json`).
6. **Painel de curadoria (risco médio).** Expor `catalog.search` (paginado) e `ReviewService` em endpoints do `review_server`, com token de sessão. Substitui o `list_studio_catalog`, que carrega tudo (no benchmark, carregar tudo custou 159 MB contra 0,3 MB paginado com 10.000 registros).
7. **n8n (risco médio).** Um nó HTTP envia `ii.mission.v1` assinado para o gateway local. O n8n só orquestra; nenhuma regra de classificação vai para o workflow. Exemplos em `fixtures/n8n_mission_example.json` e `fixtures/n8n_result_example.json`.
8. **Obsidian (risco médio).** `export_reference` grava em staging. A cópia para o cofre continua manual ou num passo separado. O exportador recusa pastas com `.obsidian/`.

## 3. Contratos que o Antigravity precisa respeitar

- **Status de evidência:** `observed_visual` só com frame registrado (SHA-256) e base `static_frame`/`frame_pair`/`frame_sequence`/`video_clip`. Fala vira `transcript_claim`, legenda vira `metadata_claim`. O validador recusa qualquer outra combinação.
- **Movimento:** tags de movimento (`kinetic_typography`, `animated_caption`, `transition`, `camera_move` etc.) com 1 ou 2 quadros são rebaixadas para `inference`. Para afirmar animação, envie `frame_sequence` (3 quadros ou mais) ou trecho de vídeo.
- **Sem números de confiança:** chaves `confidence`, `probability`, `accuracy`, `percent` são rejeitadas em qualquer nível do documento.
- **Identidade:** shortcodes preservam maiúsculas e minúsculas (L3). Use `dedup.canonical_reference_key`.
- **Medições:** cortes detectados nunca criam categoria sozinhos. Uma `MeasuredRule` só deve ser ligada depois de calibrada contra a curadoria humana.

## 4. O que fica fora (de propósito)

- Executar ffmpeg, Whisper ou modelos: o Antigravity produz os artefatos e o `ii_mm` só os lê.
- Calibração de limiares e taxas de acerto: exige vídeos rotulados por humano.
- Migração dos dados reais do `catalog.sqlite`: precisa de execução no Windows, com backup.

## 5. Pontos de atenção no Windows

- Caminhos: o contrato n8n aceita só URIs relativas com `/` ou `\`. Unidades (`C:`) e UNC são recusadas de propósito.
- WAL: o banco cria `-wal`/`-shm` ao lado do arquivo. Não coloque o banco em pasta sincronizada (OneDrive).
- FTS5 não é necessário: a busca por assunto usa a tabela `search_terms`, portátil entre versões do SQLite.

# Classificação multimodal: arquitetura proposta

Status: **proposta com protótipo testado em dados sintéticos**. Nada foi integrado ao `Projeto-MVP`, e nenhuma análise visual do vídeo piloto foi feita (ver `INVENTARIO_EVIDENCIAS_FALTANTES.md`).

## 1. Problema, a partir da auditoria anterior

`curation.py` e `content_miner.py` classificam por texto, por substring e pela ordem das regras, e ignoram os sinais audiovisuais. A meta é sair de "este vídeo fala de uma ferramenta de IA" para "este vídeo demonstra a ferramenta X, ensina o processo Y, usa as técnicas Z, com evidências por timestamp".

## 2. Modelo de classificação

Nove categorias, **multi-rótulo** (um vídeo pode ter várias):
`conhecimento`, `demonstracao_ferramenta`, `tutorial`, `motion_design`, `edicao_audiovisual`, `marketing_vendas`, `conteudo_cinematografico`, `referencia_estetica`, `automacao_ia`.

Cada categoria presente carrega:

```json
{
  "category": "demonstracao_ferramenta",
  "support": "verified_visual",
  "evidence": [
    {"id": "demonstracao_ferramenta:1", "modality": "transcript", "status": "claimed_transcript",
     "t_start_s": 21.4, "t_end_s": 24.0, "ref": "segmento:9", "quote": "…", "matched": ["ferramenta"],
     "provenance": {"source": "transcription", "untrusted_text": true}},
    {"id": "demonstracao_ferramenta:2", "modality": "visual_review", "status": "verified_visual",
     "t_start_s": 23.9, "t_end_s": 23.9, "ref": "P05", "tag": "ui_screen_visible",
     "evidence_basis": "static_frame", "quote": "…",
     "provenance": {"artifact": "manifesto_pacote.json", "frame_sha256": "…", "observer": "…"}}
  ],
  "review": {"state": "pending", "reviewer": null, "decided_at": null, "note": null}
}
```

### Apoio (`support`) é ordinal, não probabilidade

Do mais forte ao mais fraco: `verified_visual` > `measured` > `claimed_transcript` > `claimed_metadata` > `hypothesis`. O valor da categoria é o tipo da melhor evidência. **Não há percentuais de confiança ou precisão.** Isso só poderá existir depois de uma avaliação calibrada (seção 7).

### Regras que o código já impõe (testadas)

1. Texto (legenda, hashtags, transcrição) **nunca** verifica uma categoria; no máximo gera `claimed_*`.
2. Transcrição é dado não confiável e nunca é tratada como instrução.
3. Tags de movimento (`motion_*`) exigem `evidence_basis=video_clip`. Quadro estático ou par de quadros só pode registrar **hipótese**.
4. Métricas objetivas (cortes por minuto etc.) são anexadas como `measured`, mas **não disparam categoria sozinhas**, porque os limiares não foram calibrados.
5. Toda observação visual exige proveniência (`pacote_id` e SHA-256 do frame) e `t_s` dentro da duração.
6. A saída não depende da ordem das regras (ordem canônica das categorias).
7. Status `concluida` sem nenhuma observação visual é rejeitado pelo validador.
8. Toda categoria nasce com revisão humana `pending`; a decisão humana fica em `review`, sem sobrescrever a evidência.

### Reuso do `text_matcher.py`

`RankedMatcher` faz o casamento por fronteira de palavra e sem acento nas três fontes de texto. Evita os falsos positivos já reproduzidos (`bot` em "robotics", `make`, `dev`). O protótipo roda em modo sombra, ao lado de `curation.py`.

## 3. Esquema de dados versionado (SQLite, proposta)

Migrações numeradas, aplicadas por um único módulo. Substituem os `ALTER TABLE` espalhados e viabilizam fixtures de teste.

```sql
schema_migrations(version INTEGER PRIMARY KEY, applied_at TEXT, checksum TEXT)

media_asset(                         -- deduplicação por conteúdo
  sha256 TEXT PRIMARY KEY, duration_s REAL, width INT, height INT, fps REAL,
  first_seen_item_id TEXT, created_at TEXT)

item_asset(item_id TEXT, sha256 TEXT, role TEXT, PRIMARY KEY(item_id, sha256, role))

analysis_run(                        -- uma execução de uma etapa sobre um asset
  run_id TEXT PRIMARY KEY, sha256 TEXT, stage TEXT, extractor TEXT, extractor_version TEXT,
  params_hash TEXT, status TEXT CHECK(status IN ('pending','running','done','failed','blocked')),
  artifact_path TEXT, artifact_sha256 TEXT, started_at TEXT, finished_at TEXT, error TEXT,
  UNIQUE(sha256, stage, extractor_version, params_hash))

evidence(
  evidence_id TEXT PRIMARY KEY, sha256 TEXT, category TEXT, modality TEXT, status TEXT,
  t_start_s REAL, t_end_s REAL, ref TEXT, tag TEXT, evidence_basis TEXT, quote TEXT,
  provenance_json TEXT, run_id TEXT REFERENCES analysis_run(run_id))

classification(
  sha256 TEXT, category TEXT, support TEXT, schema_version TEXT, classifier_version TEXT,
  review_state TEXT CHECK(review_state IN ('pending','accepted','rejected','edited')),
  reviewer TEXT, reviewed_at TEXT, review_note TEXT, PRIMARY KEY(sha256, category))

tool_mention(sha256 TEXT, tool_name TEXT, verified_visual INT, first_t_s REAL, evidence_id TEXT)
technique_tag(sha256 TEXT, technique TEXT, evidence_id TEXT)
```

Índices: `evidence(sha256, category)`, `evidence(tag)`, `classification(category, review_state)`, `tool_mention(tool_name)`, `technique_tag(technique)`.

Chave de idempotência: `(sha256, stage, extractor_version, params_hash)`. Ao mudar o extrator, só as etapas afetadas rodam de novo.

## 4. Escala e operação

- **Deduplicação**: pelo SHA-256 do arquivo (`media_asset`), não pelo shortcode. O mesmo vídeo salvo duas vezes é analisado uma vez.
- **Retomada**: cada etapa (`probe`, `scenes`, `frames`, `audio`, `transcript`, `visual_review`, `classify`) é uma linha em `analysis_run`. Reinício retoma as etapas em `pending` ou `failed`. `blocked` marca falta de evidência, como o caso atual.
- **Custo**: etapas locais e baratas primeiro (cenas, frames, métricas). A etapa visual com modelo só roda sob orçamento explícito e com cache por `(frame_sha256, prompt_version, modelo)`.
- **Evidência por timestamp**: toda linha de `evidence` tem `t_start_s`/`t_end_s` e `ref` para o frame ou segmento.
- **Paginação do catálogo**: cursor `(created_at, id)`, sem `stat` por linha.
- **n8n (futuro)**: o n8n só chama um endpoint local que enfileira `analysis_run` e lê o status. Ele não escreve em `evidence` nem em `classification`. Webhook com token efêmero e a fila em tabela, não em arquivo.
- **Obsidian**: exportador somente leitura gera uma nota por vídeo a partir de `classification` e `evidence`, em staging fora do cofre (como o projeto já faz), com links para os timestamps. Notas não voltam para o banco.

## 5. Consultas previstas

```sql
-- vídeos que DEMONSTRAM (visualmente) uma ferramenta
SELECT sha256, tool_name FROM tool_mention WHERE tool_name = :t AND verified_visual = 1;
-- vídeos que só MENCIONAM a ferramenta na fala
SELECT sha256 FROM tool_mention WHERE tool_name = :t AND verified_visual = 0;
-- por técnica audiovisual, com o timestamp
SELECT e.sha256, e.t_start_s, e.ref FROM technique_tag t JOIN evidence e USING(evidence_id) WHERE t.technique = :tec;
-- fila de revisão humana
SELECT sha256, category FROM classification WHERE review_state = 'pending' ORDER BY category;
```

## 6. Plano de adoção (modo sombra)

1. Aplicar as migrações num **banco de teste**, nunca no `catalog.sqlite` de produção.
2. Rodar `classify()` em paralelo à classificação atual e guardar as duas saídas.
3. Comparar contra a curadoria humana existente (`triage_decision`, `quality_rating`, `editorial_category`), por categoria e por falso positivo.
4. Só depois de aprovação, ligar a nova saída ao painel como **sugestão** (a decisão humana continua soberana).
5. Os testes de regressão (`test_regression_current.py`) devem continuar passando ao longo de todo o processo.

## 7. Avaliação calibrada (pré-requisito para qualquer número)

Conjunto de 30 a 50 vídeos rotulados por humano, por categoria. Medir precisão e cobertura por categoria, separando `verified_visual` de `claimed_*`. Até lá, nenhum percentual é publicado.

## 8. Status

| Item | Estado |
|---|---|
| Taxonomia, regras de evidência e protótipo (`multimodal_classifier.py`) | Concluído, 17 testes com dados sintéticos |
| Regressão da classificação atual (golden + modo sombra) | Concluído (17 casos, reexecução contra `c6845a4` passa) |
| Verificador de pacote (`verify_package.py`) | Concluído, 6 testes |
| Esquema SQL, fila, n8n, Obsidian, consultas | **Apenas proposto** |
| Análise visual do DQV5dm6gCvH | **Não realizada, depende de acesso às mídias** |
| Avaliação calibrada | **Não realizada, depende de vídeos rotulados** |

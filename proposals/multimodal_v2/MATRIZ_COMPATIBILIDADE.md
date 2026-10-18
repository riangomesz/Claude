# Matriz de compatibilidade: `ii_mm` × Projeto-MVP

Base verificada: clone de `riangomesz/Projeto-MVP` no commit `c6845a4` (estado **publicado**). As assinaturas foram extraídas por AST, sem importar módulos pesados. O esquema foi conferido montando o catálogo legado num banco temporário com o próprio código do clone (`ii_mm/db/legacy_fixture.py`).

**Ressalva:** o estado local do Antigravity pode ter avançado além desse commit. Tudo marcado como COMPATÍVEL vale para `c6845a4` e precisa ser reconfirmado no Windows com `PROJETO_MVP_DIR=<clone local> python3 run_tests.py`.

Legenda: **COMPATÍVEL** (usa direto) · **ADAPTADOR NECESSÁRIO** (adaptador existe e está testado) · **INCOMPATÍVEL** (não deve ser ligado como está) · **NÃO VERIFICADO** (sem acesso ao formato real).

## Dados e persistência

| Interface legada | Caminho / assinatura | Status | Como é tratado | Teste |
|---|---|---|---|---|
| Tabela `instagram_items` | DDL real com **65 colunas** (a estimativa por regex da Missão 01, de 49, estava incompleta) | ADAPTADOR NECESSÁRIO | `legacy.from_instagram_item`: 20 colunas mapeadas, 45 preservadas em `x_legacy`, nenhuma sem destino | `RealSchemaCompatibilityTest` (opt-in) |
| `media_sha256`, `media_duration_sec`, `media_width/height/fps` | colunas criadas por `media_acquisition.ensure_media_schema` | COMPATÍVEL | Viram `video.content_sha256` e dimensões; habilitam deduplicação por conteúdo | `test_full_row_maps_preserves_and_reports` |
| `InstagramItem` (pydantic) | `core/instagram_importer.py` | ADAPTADOR NECESSÁRIO | `hashtags` (lista) é aceito no lugar de `hashtags_json` | `test_instagram_item_model_dump_shape` |
| `audio_transcript_segments_json` | gravado por `curation.update_audio_transcript(db_path, item_id, transcript_text, source, segments, …)` | ADAPTADOR NECESSÁRIO | Segmentos `{index,start_time,end_time,text}` ou `{start,end,text}` → `transcript_claim` | `test_full_row…` |
| `audio_transcript` sem segmentos | idem | ADAPTADOR NECESSÁRIO | Vira `transcript_claim` para o vídeo inteiro com `untimed=true`, sem inventar tempos | `test_untimed_transcript_and_bad_json` |
| Criação de esquema legado | `init_instagram_db` (importa `cv2`) + `ensure_*` em 5 módulos | INCOMPATÍVEL para testes isolados | Fixture extrai o DDL por AST e aplica na ordem de dependência | `LegacyNoSuchTableReproductionTest` |
| Conexões `with sqlite3.connect(...)` | 25 ocorrências em `core/` | INCOMPATÍVEL no Windows (trava arquivo) | Ver `RISCO_E_ROLLBACK.md` e o patch demonstrativo da T07 | `test_legacy_connection_leak` |
| `catalog.sqlite` de produção | `storage/catalog.sqlite` | INCOMPATÍVEL como destino | `ii_mm` recusa esse nome; o modo sombra só lê em `mode=ro` | `test_production_name_refused`, `ReadOnlyTest` |
| Outras tabelas (`opportunities`, `triage_history`, `editorial_categories`, `post_media_items`, `trash_items`, …) | 13 tabelas além de `instagram_items` | NÃO VERIFICADO (sem uso pelo `ii_mm`) | Fora do escopo do núcleo | — |

## Classificação

| Interface legada | Assinatura | Status | Tratamento |
|---|---|---|---|
| `curation.evaluate_item_curation` | `(caption, hashtags, owner_username, owner_name) -> (categoria, regra)` | COMPATÍVEL (golden) | Comportamento fixado por `test_regression_current` (17 casos) |
| `curation.suggest_editorial_category` | `(caption, hashtags, owner_username, post_type) -> dict ou None` | COMPATÍVEL (modo sombra) | Injetada em `shadow.run_shadow(legacy_suggest=…)` |
| `curation_category` / `curation_rule` armazenados | colunas | ADAPTADOR NECESSÁRIO | Viram `inference` (rótulo legado), nunca categoria v2 |
| `editorial_category` + `editorial_category_source` | colunas | ADAPTADOR NECESSÁRIO | Origem manual vai para `human_decisions` (importação explícita pela revisão); automática vira `inference` |
| `triage_decision`, `quality_rating`, `curator_note` | colunas | COMPATÍVEL (preservadas) | Ficam em `x_legacy`; não são categoria de conteúdo |
| `content_miner.classify_content_for_rian` | `(title_or_caption, author, hashtags, …, real_views, real_likes) -> dict` | INCOMPATÍVEL como fonte de evidência | Produz score numérico (0 a 100) e "tier"; não importar como confiança. Só pode ser comparado em modo sombra |
| Pilares do `content_miner` (6) × categorias v2 (9) | `PILLARS_METADATA` | ADAPTADOR NECESSÁRIO (não implementado) | Mapeamento é editorial: decidir com o curador |

## Análise visual, temporal e de áudio

| Interface legada | Formato | Status | Tratamento |
|---|---|---|---|
| `vision_client.VisualMacroAnalysis` | `status`, `verifiable_observations: List[str]`, `inferred_hypotheses`, `limitations_or_ambiguities`, … | ADAPTADOR NECESSÁRIO | `legacy.from_vision_macro`. `status != 'observado'` (simulação ou erro) é recusado. As observações do modelo não citam frame, então entram como `unverified` |
| `vision_client.VisualMicroAnalysis` | `kinetic_behavior`, `inferred_easing_curves`, `reproduction_hypotheses`, … | NÃO VERIFICADO (adaptador não implementado) | Curvas de easing inferidas de spritesheet nunca são `temporal_sequence` |
| `scene_analyzer.SceneInterval` | campos + bug B9 (`mean_visual_change` inexistente) | ADAPTADOR NECESSÁRIO | Usar a saída do ffmpeg (`adapters.scenes_from_*`), não o `SceneInterval` |
| `temporal_intelligence.detect_transitions_in_window` | `{timestamp_evento_s, tipo_candidato, classificacao_evento, nivel_evidencia, limiares_utilizados}` | ADAPTADOR NECESSÁRIO | `legacy.from_transition_candidates`: medição + tipo como hipótese (limiares de um vídeo só) |
| `temporal_intelligence.compute_pairwise_metrics` | `diff_absoluta_*`, `ssim_*`, `timestamp_anterior_s/atual_s` | COMPATÍVEL | `adapters.metrics_from_frame_pairs` |
| `audio_processor.parse_srt_file` / SRT | `SubtitleEntry` | COMPATÍVEL | `adapters.transcript_from_srt` |
| `transcription.transcribe_video_speech` | `segments: [{index,start_time,end_time,text}]` | COMPATÍVEL | `adapters.transcript_from_segments` |
| ffprobe JSON | padrão | COMPATÍVEL | `adapters.probe_from_ffprobe_json` (`avg_frame_rate` "0/0" tratado) |

## Pacotes `ii_coverage` (Fases 4, 5 e 5.1)

| Artefato | Schema | Status | Tratamento |
|---|---|---|---|
| `manifesto_cobertura.json` | `ii.coverage.manifest.v1` (`frame_id`, `t_actual_s`, `sha256`) | COMPATÍVEL | `adapters.frames_from_manifest` |
| `manifesto_pacote.json` | `ii.evidence_package.v1` (`pacote_id`, `t_s`, `papel`, `par_com`) | COMPATÍVEL | idem + `verify_package.py` |
| `cortes_detectados.json` | `ii.scene_candidates.v1` | COMPATÍVEL | `adapters.scenes_from_candidates_json` |
| `segmentos_transcricao.json` | `{segmentos: [{id,inicio_s,fim_s,texto}]}` | COMPATÍVEL | `adapters.transcript_from_segments` |
| `ficha_inteligencia.json` / `_v2.json` | `ii.intelligence.card.v1/v2` | ADAPTADOR NECESSÁRIO | `legacy.from_intelligence_card`: preserva fala / visível / movimento / hipóteses / conhecimento externo. `tipo` sem tag conhecida é reportado |
| Valores reais de `tipo` das observações da Fase 5 | `revisao_visual_fase5.json` | NÃO VERIFICADO | Arquivo ausente na nuvem; a tabela `FICHA_TIPO_TO_TAG` precisa ser conferida com o arquivo real |
| `perguntas_de_verificacao.json` | `ii.verification_questions.v1` | NÃO VERIFICADO (sem consumo pelo `ii_mm`) | Usado pelo agente, não pelo núcleo |

## APIs e interfaces de saída

| Interface legada | Status | Observação |
|---|---|---|
| `review_server` (33 rotas `/api/*`, incluindo `/api/studio/catalog` e `/api/items`) | NÃO VERIFICADO em execução | O servidor não foi iniciado. O catálogo paginado do `ii_mm` pode substituir `/api/studio/catalog` (hoje sem paginação) numa rota nova |
| `studio_adapter.list_studio_catalog` | INCOMPATÍVEL para escala | Carrega tudo e faz `stat` por linha; ver `BENCHMARK.md` |
| `markdown_exporter.export_*` com `to_vault` | INCOMPATÍVEL como destino do `ii_mm` | O `ii_mm` só exporta para staging (`obsidian_export.assert_staging`) |
| n8n (`n8n_workflows/*.json`) | NÃO VERIFICADO em execução | Os workflows chamam Ollama em `127.0.0.1:11434`; a integração do `ii_mm` é só por contrato (`n8n_contract`) |
| Extensão `instagram_capture` (`127.0.0.1:8766`) | NÃO VERIFICADO | Fora do escopo |

## Lacunas para o Antigravity confirmar no Windows

1. Rodar `PROJETO_MVP_DIR=<clone local> python3 run_tests.py`. Os 6 testes opt-in conferem o DDL, a regressão, o modo sombra com a função real e a fixture legada.
2. Conferir os valores reais de `tipo` em `revisao_visual_fase5.json` contra `FICHA_TIPO_TO_TAG`.
3. Confirmar se `editorial_category_source` usa os valores esperados (`manual`, `manual_do_usuario`, …) para decisões humanas.

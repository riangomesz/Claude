# Auditoria 2: classificação audiovisual e escalabilidade

Repositório auditado: `riangomesz/Projeto-MVP`, commit `c6845a4` (clone raso, somente leitura).
Nada foi alterado no `Projeto-MVP`. Esta branch só recebe documentação e propostas isoladas.
Nenhum modelo externo, banco, n8n ou mídia foi usado. Os testes rodaram numa cópia temporária.

## Resumo

| # | Achado | Gravidade | Evidência |
|---|---|---|---|
| 1 | A classificação usa só texto (legenda, hashtags, autor). Os sinais audiovisuais não entram nela. | Alta | `curation.py:238`, `content_miner.py:363` |
| 2 | Falsos positivos por substring em `suggest_editorial_category`. | Alta | Reproduzido, ver abaixo |
| 3 | Tokens genéricos na lista de "relevante" (`make`, `dev`, `tech`, `edit`, `tools`, `growth`). | Média | Reproduzido |
| 4 | A heurística de transição temporal está calibrada para um único vídeo (`DQV5dm6gCvH`). | Alta | `metric_calculator.py:61`, `transition_detector.py` |
| 5 | O id do piloto está escrito no código de produção. | Média | 17 ocorrências em 7 módulos |
| 6 | O catálogo é lido inteiro a cada chamada, com `stat` por arquivo, sem paginação. | Média (escala) | `studio_adapter.py:97` |
| 7 | O pipeline é sequencial, sem fila, sem retomada por etapa e sem idempotência por hash. | Média (escala) | `audiovisual_pilot.py`, `cli.py` |
| 8 | Migrações de esquema com `ALTER TABLE` espalhadas em 5 módulos, sem versão. | Média | `account_connection.py:185`, `media_acquisition.py:191`, `curation.py:118` |
| 9 | `SceneInterval` é criado com um campo que não existe (`mean_visual_change`), então `mean_pixel_diff` nunca é preenchido. | Baixa (bug) | `scene_analyzer.py:63,84` |

## 1. Classificação só por texto

- `evaluate_item_curation` decide `relevante`, `incerto` ou `irrelevante` apenas por interseção de tokens.
- `classify_content_for_rian` usa largura, altura e fps no componente de qualidade (peso 20%). Nem cortes, nem ritmo, nem energia de movimento, nem fala entram no índice de oportunidade.
- Consequência: um Reel sem legenda vira `incerto` mesmo quando o vídeo tem sinais fortes (muitos cortes, tipografia animada, voz). Para o pilar "Engenharia Reversa Audiovisual", o sinal mais importante é ignorado.
- Os insumos já existem no repositório: `scene_analyzer` (cortes, micro-cortes, energia), `audio_processor` (silêncio e fala), `transcription` e `temporal_intelligence`. Falta ligá-los ao classificador.

**Proposta (design, sem código de produção):** guardar por vídeo um perfil de sinais com versão e proveniência, por exemplo `av_profile_v1`:

```
cuts_per_min, micro_cut_ratio, median_shot_sec,
motion_energy_mean, motion_energy_p90,
speech_ratio, silence_ratio, has_burned_captions,
aspect_ratio, fps, duration_sec,
extractor_version, computed_at, source_sha256
```

O classificador de pilares passa a combinar texto e perfil, com pesos configuráveis. Cada sinal fica nomeado em `breakdown`, como já ocorre hoje. Itens sem legenda e com perfil forte sobem para revisão em vez de ficarem em `incerto`.

## 2. Falsos positivos por substring (reproduzidos)

`suggest_editorial_category` usa `kw in texto`. Resultados em execução real da função, numa cópia isolada:

| Texto | Rótulo sugerido | Esperado |
|---|---|---|
| `robotics demo` | Automação (por `bot`) | nenhum |
| `both teams won the game` | Automação (por `bot`) | nenhum |
| `copy of my receipt` | Marketing e Conteúdo (por `copy`) | discutível (`copy` é palavra inteira) |
| `how to make a cake at home` | `relevante` (token `make`) | `incerto` |
| `pizza do dev da esquina` | `relevante` (token `dev`) | `incerto` |

Outros problemas:

- A função devolve o primeiro rótulo que casar. A ordem da lista decide o resultado, não a evidência. "Ferramentas de IA" ganha de "Design e Motion" mesmo quando o texto é quase todo de motion.
- Os padrões `"ia "`, `" ai "` e `"#ia"` dependem de espaços e de `#`. Texto no fim da frase ou com pontuação escapa.
- `RELEVANT_KEYWORDS` tem termos ambíguos em português e inglês.

**Proposta implementada, isolada:** `proposals/classification/text_matcher.py` com 6 testes em `test_text_matcher.py`. Ela casa por fronteira de palavra, ignora acentos e devolve um ranking por número de evidências, com desempate determinístico pela ordem das regras. Usa só a stdlib. Para integrar: trocar a lista de regras de `suggest_editorial_category` por `RankedMatcher(rules)`, sem mudar a assinatura pública.

Rodar: `cd proposals/classification && python3 -m unittest test_text_matcher`

## 3. Heurística temporal calibrada para um vídeo

- `split_frame_regions` usa `split_ratio=0.448`, que separa o "overlay" (topo) da "âncora humana" (base). Isso descreve o layout de um vídeo específico.
- `THRESHOLDS` (`diff_global_corte=20.0`, `ssim_top_min=0.75` etc.) são fixos. Os tipos de candidato (`CANDIDATO_INSERCAO_OVERLAY_ISOLADO`) assumem esse layout.
- Para escalar a outros Reels (tela cheia, split vertical, screen recording), é preciso:
  1. Passar o layout como parâmetro por vídeo, com `full_frame` como padrão.
  2. Calibrar limiares por distribuição do próprio vídeo (por exemplo mediana mais k·MAD) em vez de números absolutos.
  3. Medir precisão e recall em um conjunto rotulado de 20 a 30 vídeos, não em um só.
- As 17 referências a `DQV5dm6gCvH` em `studio_adapter`, `review_server`, `temporal_intelligence/*` e `comparative_intelligence/*` precisam virar parâmetro ou configuração.

## 4. Escalabilidade

- `list_studio_catalog` faz `SELECT` sem `LIMIT`, depois `Path.exists()` para cada linha. Com dezenas de milhares de itens, cada chamada do painel custa uma varredura completa mais I/O de disco. Propostas: paginação por cursor `(created_at, id)`, coluna `has_media_file` mantida na escrita (já existe) em vez de `stat` na leitura, e um índice composto para a ordenação usada.
- O catálogo roda em SQLite. Há índices por tipo, dono, status e plataforma, mas nenhum cobre `(has_media_file, created_at)`. Falta `PRAGMA journal_mode=WAL` e `busy_timeout` em todas as conexões. O painel (threads) e o pipeline escrevem no mesmo arquivo. Antigravity e este ambiente nunca devem tocar o mesmo `catalog.sqlite`.
- O pipeline audiovisual processa um vídeo por vez e grava o resultado só no final. Propostas: uma tabela de etapas por `(video_sha256, etapa, versão_do_extrator)` com status e artefato. Isso dá idempotência, retomada e reprocessamento seletivo quando só o extrator muda.
- Migrações: `ALTER TABLE` condicional em `instagram_importer`, `account_connection`, `curation`, `media_acquisition` e `content_miner`. A ordem de execução define o esquema final. Propostas: tabela `schema_migrations` com um único módulo de migração versionado. Isso também resolve os testes que falham com `no such table: instagram_items`, porque um fixture chama a migração e obtém o esquema completo.
- Custo da API Gemini: o teto de gasto é só uma estimativa por tokens (os próprios comentários admitem). Propostas: cache de resposta por `(frame_hashes, prompt_version, modelo)` e um orçamento persistido em disco por execução.

## 5. Plano sugerido (ordem de valor e risco)

1. **Migrações versionadas e fixture único de banco temporário.** Destrava os testes que hoje falham por `no such table` (4 deles em `content_miner_pipeline` e `audio_intelligence_v1`). Risco baixo.
2. **Integrar `RankedMatcher`** em `suggest_editorial_category` e revisar `RELEVANT_KEYWORDS`. Risco baixo, ganho imediato.
3. **Tirar `DQV5dm6gCvH` e o layout 0.448 do código.** Parametrizar por vídeo e por configuração.
4. **Perfil `av_profile_v1`** por vídeo e uso dele no classificador de pilares. Medir contra a curadoria humana que já existe (`triage_decision`, `quality_rating`), sem custo de API.
5. **Etapas idempotentes por hash** e paginação do catálogo.

## O que não foi verificado

- Nenhum dado real. Não vi o conteúdo de `catalog.sqlite`, da exportação Meta nem dos vídeos, então não sei o tamanho real do catálogo. Os pontos de escala acima são projeções do código, não medições.
- Não executei o Whisper, o Gemini, o Ollama, o yt-dlp nem o n8n.
- Não confirmei se o Antigravity já corrigiu algum desses pontos em branch local não publicada.

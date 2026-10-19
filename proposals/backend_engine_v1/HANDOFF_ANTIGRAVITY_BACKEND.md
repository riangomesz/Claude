# Handoff para o Antigravity: backend `ii_be` (Missão Suprema 04)

| Campo | Valor |
|---|---|
| Branch | `claude/instagram-intelligence-backend-supreme-04` (repositório `riangomesz/Claude`) |
| Pasta | `proposals/backend_engine_v1/` |
| Núcleo usado | `proposals/multimodal_v2/ii_mm` da RC1 `ii_mm-1.0.0-rc1` (`d0e1916`), **inalterado**; manifesto `10f0e9d8…` continua válido nesta branch |
| Estado | Proposta testada na nuvem com dados sintéticos. **Nenhuma integração com o Projeto-MVP foi feita ou autorizada** |

Este handoff não substitui a validação da RC1 no Windows (`HANDOFF_ANTIGRAVITY_RELEASE_CANDIDATE.md`): o backend depende do núcleo e herda as mesmas pendências de Windows.

## 1. Relação com o `ii_mm`

O backend importa o `ii_mm` por caminho e acrescenta a camada operacional. A análise continua sendo do núcleo:
- `Normalizer`, `Classifier` e `Repository.save_analysis`;
- `ReviewService`;
- `catalog.build_sql`;
- `obsidian_export`.

Tabelas próprias `be_*` vivem no MESMO arquivo de banco das tabelas do `ii_mm`, com trilha de migração separada (`be_schema_migrations`). Detalhes em `ARQUITETURA_BACKEND.md`.

Uma incompatibilidade do núcleo (**I1**) foi encontrada e mitigada sem alterar a RC1. A análise corrente do `ii_mm` é por vídeo: o mesmo arquivo em duas publicações faz uma referência "ver" o documento da outra. O backend usa `RefScopedRepository`. Uma rc2 do núcleo poderia tornar "corrente" por (vídeo, referência).

## 2. Conexão futura com o catálogo existente

- O backend **não lê nem grava** o `catalog.sqlite` legado. O nome é recusado.
- Para trazer o catálogo, há dois caminhos.
  - **Ingestão:** a partir de um SNAPSHOT do catálogo (`ii_mm.shadow.snapshot_readonly`), um adaptador converte linhas de `instagram_items` em registros `ii.be.ingest.v1` (URL, legenda, autor, duração). Esse adaptador **não foi implementado**: precisa da validação do Estágio 1 com o catálogo real.
  - **Decisões humanas legadas:** `editorial_category` manual e `triage_decision` continuam no catálogo. O caminho seguro é importá-las como decisões humanas explícitas (`CurationService`, revisor `human:importacao_legado`) numa etapa revisada, nunca como saída automática.

## 3. Adaptadores necessários (Windows)

| Insumo | Quem produz hoje | Como chega ao backend |
|---|---|---|
| Mídia | Aquisição autorizada do Projeto-MVP | arquivo na raiz gerenciada + `register_artifact(kind="video")`, ou ingestão `local_file` |
| ffprobe | ffmpeg/ffprobe locais | `ffprobe -print_format json -show_streams -show_format` → `register_artifact(kind="ffprobe")` |
| Transcrição | Whisper (Projeto-MVP) | segmentos JSON (`transcript_segments`) ou SRT (`srt`) |
| Cenas | ffmpeg `select='gt(scene,…)'` + `metadata=print` | `scenes_ffmpeg` (saída de texto) ou `scene_candidates` (JSON) |
| Quadros | `ii_coverage` / pacote de evidências | `frames_manifest` |
| Métricas temporais | `temporal_intelligence` | `frame_metrics` |
| Observações visuais | humano ou agente (formato `ii.visual_observation.v1`) | `observations`; o `origin` identifica o observador |

O backend nunca executa essas ferramentas: só confere e usa os arquivos. A conferência de integridade é feita no momento do uso: arquivo alterado vira `corrupt` e a etapa espera nova versão.

## 4. Preservar decisões de curadoria

- Decisões de categoria, ferramenta e evidência continuam no `ii_mm` (`reviews`, `review_state`).
- Triagem, nota, confirmação de evidência e rejeição de hipótese ficam em `be_curation*`.
- Reclassificar nunca substitui uma decisão humana. O evento `classification.updated` traz `human_overrides` quando a nova saída automática diverge do que o humano decidiu.
- Atores automáticos (`agent:`, `auto:`, `n8n:`, `worker:`, `model:`) não conseguem registrar curadoria.

## 5. Aproveitar FFmpeg e Whisper existentes sem duplicar processamento

- Cada artefato tem SHA-256. Se a mesma saída for registrada de novo, o registro é idempotente e nenhuma etapa refaz.
- A impressão digital de entrada garante que só o que depende do arquivo novo seja recalculado (`incremental.py`).
- O n8n (ou script) roda a ferramenta UMA vez, grava o arquivo na raiz gerenciada e chama `register_artifact`. O resto é do backend.

## 6. n8n sem duplicar processamento

- O n8n orquestra (gatilhos, chamada das ferramentas, notificação). A lógica de domínio fica no backend (`ARQUITETURA_BACKEND.md`, "Python × n8n").
- Entrada: API `ingest_reference` e `register_artifact`, ambas com `idempotency_key`. Também continua possível a missão `ii.mission.v1` assinada (gateway do `ii_mm`).
- Saída: eventos do outbox. Nesta missão, só como arquivo JSONL em staging (`events.JsonlSink`). Um consumidor HTTP para o n8n é trabalho futuro e precisa de autorização.
- Entrega é "pelo menos uma vez": o consumidor deve deduplicar por `event_id`.

## 7. Consultar pelo painel visual

- Use a API `ii.be.api.v1` (`api.py`): `list_references`, `get_reference`, `get_processing`, `get_evidence`, `get_classification`, `get_curation`, `register_curation`, `list_jobs`, `get_job`, `list_failures`, `request_reprocess`, `search`, `search_knowledge`, `diagnostics`.
- O servidor HTTP opcional (`http_local.py`) só escuta em 127.0.0.1, confere o cabeçalho Host e exige JSON. **Nenhuma porta foi aberta no Windows**, e o painel atual não foi alterado.

## 8. Exportar para Obsidian

A etapa `export` usa `ii_mm.obsidian_export` e grava só em staging. O `ii_mm` recusa pastas com `.obsidian`. Copiar do staging para o Vault continua sendo ação humana.

## 9. Indisponível na nuvem

- Mídias e saídas reais de ffmpeg e Whisper.
- O catálogo real.
- O estado local do Projeto-MVP.
- O vídeo-piloto `DQV5dm6gCvH`, que continua `blocked_missing_evidence`.
- Qualquer métrica de qualidade da classificação: todos os dados são sintéticos.

## 10. Validação necessária no Windows

1. Validar a RC1 primeiro (handoff da Missão 03).
2. `py -3 -X utf8 run_tests.py` em `proposals\backend_engine_v1`, com o Python que será usado. Conferir os testes de concorrência, que usam threads e WAL no NTFS.
3. `py -3 -X utf8 -m ii_be.demo` e comparar o resumo com o da nuvem (`RELATORIO_MISSAO_SUPREMA_04_BACKEND.md`, seção 8).
4. Benchmark local: `py -3 -X utf8 tools\bench_backend.py --sizes 82,1000`.
5. Antivírus e indexador: verificar se seguram o `-wal` ou a raiz de artefatos. O banco do backend não deve ficar em pasta sincronizada (OneDrive).

**Os comandos acima não foram executados no Windows.** Antes do uso, devem passar pelo mesmo procedimento isolado da Missão 03, numa pasta nova fora do Projeto-MVP.

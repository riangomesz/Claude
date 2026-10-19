# Progresso: Missão Suprema 04 (Backend Intelligence Engine)

Branch: `claude/instagram-intelligence-backend-supreme-04`, criada a partir de `3ec455c` (branch da RC1, intocada).
RC1 congelada (`d0e1916`, manifesto `10f0e9d8…`): nenhum arquivo de `proposals/multimodal_v2/` é alterado; o validador
de recebimento continua OK após cada checkpoint.

## Decisões arquiteturais (registradas antes do código)

1. **Uma autoridade por dado.** Identidade de referência, vídeos, análises e revisões de categoria/ferramenta continuam
   nas tabelas do `ii_mm`; o backend só acrescenta tabelas `be_*` (trilha própria de migração `be_schema_migrations`).
2. **A fila é a autoridade sobre execução**; o estado de processamento da referência é DERIVADO (jobs + resultados de
   etapa), com os nomes do `ii_mm.pipeline.STAGES`. O backend não grava `processing_state`: duas máquinas na mesma
   tabela seriam duas autoridades. Reuso do lease: mesma semântica e a mesma exceção `LeaseLost` do `ii_mm`.
3. **SQLite + processos locais + stdlib.** Sem Redis/Kafka/broker: outbox transacional e fila em SQLite (WAL,
   `BEGIN IMMEDIATE`) atendem ao volume real (centenas a dezenas de milhares de referências).
4. **Processamento incremental por impressão digital de entrada** com corte antecipado (`incremental.py`).
5. **Etapas audiovisuais só recebem saídas de ferramentas existentes** (ffprobe, ffmpeg, whisper, observações);
   nada é reimplementado e nenhuma mídia privada é processada na nuvem.
6. **Curadoria humana soberana**: decisões ficam em `reviews/review_state` (ii_mm) e `be_curation*`; reclassificação
   automática nunca as substitui; atores automáticos (`auto:`, `agent:`, `worker:`) não podem registrar curadoria.

## Checkpoints

### C1: P0 (ingestão, identidade, fila, scheduler, incremental, artefatos, etapas, worker)
- Módulos: `db`, `errors`, `identity`, `ingest`, `artifacts`, `events` (outbox), `queue`, `scheduler`, `incremental`,
  `stages`, `worker`, `knowledge`, `observability`, `engine`, `synthetic`.
- Testes: 51 (ingestão/identidade 11, fila 13, scheduler/incremental 11, artefatos 7, concorrência 9) — todos OK.
- Defeitos encontrados e corrigidos durante o C1:
  - parâmetro de compartilhamento `?igsh=` (identifica quem compartilhou) seria gravado em `refs`/aliases → `clean_url`;
  - `safe_relpath` aceitava `media//x` e `./x` (PurePosixPath colapsava os componentes) → validação por componente cru;
  - adaptador `record_from_url` vazava `IdentityError` em vez de `InvalidInput`.

### C2: P1 (classificação, curadoria, busca, gateway, API/HTTP, observabilidade, segurança)
- Módulos: `classification` (10 facetas), `curation` (soberania humana, etag), `search` (catálogo do ii_mm + filtros do
  backend), `gateway` (somente mock; aprovação humana obrigatória quando aplicável), `api` (contratos `ii.be.api.v1`),
  `http_local` (loopback + Host + JSON obrigatório), `observability` (redação de segredos e conteúdo).
- Testes: 80 no total, todos OK (`-W error::ResourceWarning`). Novos: serviços 10, gateway 8, API/HTTP/observabilidade 7,
  segurança 4.
- Defeitos encontrados e corrigidos durante o C2:
  - URL com credenciais embutidas (`usuario:senha@host`) seria gravada → `clean_url` usa só o hostname;
  - `author_handle`/hashtags/legenda aceitavam caracteres de controle (NUL, escape ANSI) → recusados na validação;
  - API: o motor por thread vazaria conexões no servidor HTTP com várias threads → motor por chamada, fechado ao final.

### C3: demonstração ponta a ponta + defeito de identidade + incompatibilidade I1
- `ii_be/demo.py`: 18 passos com dados sintéticos, queda simulada e retomada; duas execuções dão o mesmo resumo
  (`tests/test_demo.py`).
- **D-BE1 (defeito do backend, corrigido):** a etapa `assemble` não dependia diretamente de `acquire`; o documento ia para
  o ii_mm sem `content_sha256` e a deduplicação por conteúdo (`videos`) não acontecia. Corrigido no grafo; regressão em
  `tests/test_shared_media.py`.
- **I1 (incompatibilidade do ii_mm, não alterado):** a análise corrente é por VÍDEO; com o mesmo arquivo em duas
  referências, `current_analysis_id(primeira)` passa a devolver o documento da outra publicação. Mitigação no backend:
  `RefScopedRepository` (subclasse) usado por revisão, índice, facetas e API. Os filtros SQL do catálogo do ii_mm
  continuam por vídeo (limitação registrada para uma futura rc2 do núcleo).
- Testes: 84, todos OK.
- Próximo passo: benchmark 82/1.000/10.000, documentação (arquitetura, contratos, README, handoff, adoção) e relatório.

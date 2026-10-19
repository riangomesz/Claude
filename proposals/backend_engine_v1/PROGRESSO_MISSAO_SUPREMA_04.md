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
- Próximo passo: serviço de classificação (facetas), gateway simulado, curadoria, busca, API/HTTP local, segurança.

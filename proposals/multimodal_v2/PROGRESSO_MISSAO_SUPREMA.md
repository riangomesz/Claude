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
| 10 | Adaptadores áudio/vídeo | IMPLEMENTADO / TESTADO | `ii_mm/adapters.py`, `tests/test_adapters.py` |
| 05–09, 11–18 | (fila) | PENDENTE | |

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

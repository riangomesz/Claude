# `ii_be`: README operacional

Motor operacional (backend) do Instagram Intelligence sobre o núcleo `ii_mm`. É proposta isolada: nada aqui está ligado ao Projeto-MVP, ao n8n real, ao Obsidian real nem à ponte ii-bridge.

## Requisitos

- Python 3.11 ou superior. Testado em 3.11.17, 3.12.3 e 3.13.16 (Linux). Só biblioteca padrão.
- SQLite 3.24 ou superior: UPSERT, comparação de tuplas e índice parcial.
- A árvore `proposals/multimodal_v2` (núcleo `ii_mm`, RC1) ao lado de `proposals/backend_engine_v1`, ou a variável `II_MM_DIR` apontando para a pasta que contém `ii_mm/`.

## Comandos

Execute na pasta `proposals/backend_engine_v1`. Os comandos foram executados no Linux; no Windows, troque `python3` por `py -3`. **Windows não testado.**

```bash
python3 -X utf8 run_tests.py                         # suíte do backend
python3 -X utf8 -m ii_be.demo                        # demonstração ponta a ponta (pasta temporária, apagada no fim)
python3 -X utf8 -m ii_be.demo --keep /tmp/ii_be_demo # mantém banco, artefatos, notas e eventos numa pasta NOVA
python3 -X utf8 tools/bench_backend.py --sizes 82,1000 --out /tmp/bench.json
python3 -X utf8 tools/contracts.py --check           # exemplos de contrato iguais aos gerados pelo código
```

A suíte do núcleo (RC1) continua em `proposals/multimodal_v2/run_tests.py` e não é alterada por este pacote.

## Uso em código (resumo)

```python
from ii_be.engine import Engine
from ii_be.ingest import record_from_url

e = Engine("C:/ii_be/backend.sqlite", root="C:/ii_be/store", export_dir="C:/ii_be/staging")
r = e.ingest(record_from_url("https://www.instagram.com/reel/XXXX/", metadata={"caption": "..."}))
e.register_artifact(r.reference_id, "video", "media/XXXX.mp4", origin="tool:download")
e.register_artifact(r.reference_id, "ffprobe", "tools/XXXX/ffprobe.json", origin="tool:ffprobe")
e.register_artifact(r.reference_id, "srt", "tools/XXXX/legenda.srt", origin="tool:whisper")
e.run()                       # eventos → planejamento → etapas → classificação (ii_mm) → índice → staging
e.processing(r.reference_id)  # estado por etapa, com o equivalente do ii_mm.pipeline
e.diagnostics()               # pendentes, em execução, bloqueados, falhas recentes, tempo por etapa
```

- O banco **nunca** pode se chamar `catalog.sqlite`: o `ii_mm` recusa o nome.
- A raiz de artefatos precisa ser uma pasta nova ou já marcada com `.ii_be_store`.
- A pasta de staging nunca pode ser o Vault: o `ii_mm` recusa pastas com `.obsidian`.

## Operação do dia a dia

| Situação | O que fazer |
|---|---|
| Ver o que está parado | `e.diagnostics()["jobs"]` e `e.queue.blocked()`; pela API, `list_failures` |
| Job em `dead_letter` | Ler `last_error_class` e as tentativas (`get_job`); corrigir a causa; `requeue_job` (mesmo id, histórico preservado) |
| Etapa esperando insumo (`waiting_dependency`) | Registrar o artefato que falta (`register_artifact`); o job volta a andar sozinho |
| Reprocessar só uma etapa | `request_reprocess` com `stages=["classify"]`; as seguintes só refazem se o resultado mudar |
| Worker caiu | Nada a fazer: o lease vence e outro worker assume. A tentativa fica como `lease_lost` |
| Parar um job | `cancel_job` (em execução: cooperativo, nunca grava resultado) |
| Limpar temporários | `artifacts.cleanup_temp` (só artefatos `temp`, só dentro da raiz gerenciada) |

## Estrutura

```
ii_be/       código (ver ARQUITETURA_BACKEND.md, seção 2)
tests/       suíte (unittest; concorrência com threads e banco WAL)
fixtures/    exportação da Meta e manifesto, sintéticos
contratos/   exemplos gerados pelo código (tools/contracts.py)
tools/       benchmark e gerador de contratos
benchmarks/  resultados do benchmark sintético
```

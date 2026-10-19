# Creative Intelligence Engine (`ii_ce`) — Missão Suprema 06

Transforma uma referência já analisada pelo `ii_be`/`ii_mm` em um **dossiê de ação**: o que o vídeo ensina, como foi feito (com o que é comprovável separado do que é hipótese), como reproduzir, e propostas originais para Rian Rocha IA e Objetaria, com roteiro e plano de produção.

Estende o backend da MS04 **por composição**: mesmo SQLite, tabelas próprias `ce_*`, migração própria. Não altera `ii_be`, `ii_mm`, frontend, `main` nem workflows existentes. **Nenhuma chamada externa**: os especialistas são adaptadores MOCK.

## Rodar

```
python -X utf8 run_tests.py            # 44 testes
python -X utf8 -m ii_ce.demo --out saida   # demonstração ponta a ponta (13 verificações), só dados sintéticos
python -X utf8 -m ii_ce.serve --db COPIA.sqlite --root COPIA/store   # API local (MOCK), loopback
```

Exemplo pronto para inspecionar: `exemplo_dossie_sintetico/dossie/<ref>/` (comece por `README.md` e `00_RESUMO_EXECUTIVO.md`).

## Mapa

| Caminho | Papel |
|---|---|
| `ii_ce/orchestrator.py` | `CreativeEngine`: investigações versionadas, tarefas com lease, aprovação, revisão humana, status |
| `ii_ce/evidence.py` | pacote de evidências congelado + seleção mínima por especialista |
| `ii_ce/planner.py` | escolhe especialistas por necessidade e registra o motivo de cada escolha e de cada corte |
| `ii_ce/providers.py` | contrato dos especialistas, `MockSpecialist`, gateway (aprovação, prazo, validação) |
| `ii_ce/reconcile.py` | afirmações → estado de verificação pela EVIDÊNCIA; contradições; revisão humana por cima |
| `ii_ce/analysis.py`, `kit.py` | decomposição, hipóteses de produção, plano de reprodução; roteiro/shot list/prompts |
| `ii_ce/commercial.py` + `profiles/*.json` | perfis comerciais versionados (dados, não código) e motor de adaptação |
| `ii_ce/dossier.py`, `obsidian.py` | dossiê Markdown/JSON/CSV idempotente; notas para staging do Obsidian |
| `ii_ce/events.py`, `api.py` | outbox para o n8n; API local `ii.ce.api.v1` (reusa o servidor loopback do `ii_be`) |
| `n8n/` | workflow importável (inativo, sem credenciais) + README + gerador |

Documentos: `ARQUITETURA_CREATIVE_ENGINE.md`, `HANDOFF_ANTIGRAVITY_CREATIVE_ENGINE.md`, `RELATORIO_MISSAO_SUPREMA_06.md`.

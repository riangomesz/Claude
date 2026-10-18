# Plano de integração segura: `ii_mm` → Instagram Intelligence (Antigravity)

Este plano substitui a ordem de integração de `INTEGRACAO_ANTIGRAVITY.md` (Missão 01), que continua válido como referência de módulos.

**Autorização:** os Estágios 1 e 2 podem ser executados pelo Antigravity. O **Estágio 3 não está autorizado por este plano**: depende de avaliação humana registrada e de decisão explícita do responsável pelo projeto.

## 1. Arquitetura final

```
artefatos já produzidos no Windows            ii_mm (somente stdlib)                          saídas
(ffmpeg, whisper, ii_coverage, catálogo)
 ├─ SRT / segmentos / ffprobe / cenas ──► adapters ─┐
 ├─ manifestos de frames ───────────────► adapters ─┤
 ├─ observações (ii.visual_observation.v1) ► adapters ┼► normalize ─► classifier ─► repository (SQLite próprio)
 ├─ linhas de instagram_items (ro) ─────► legacy ───┤        │            │          ├─ catalog / technique_library
 └─ fichas ii.intelligence.card v1/v2 ──► legacy ───┘     quality     narrative     ├─ review (histórico imutável)
                                                                       techniques   └─ obsidian_export (staging)
 n8n ── missão assinada ─► n8n_contract.MissionGateway ─► pipeline (estados + lease) ─► resultado
 catálogo legado ─(mode=ro)─► shadow ─► relatório de divergências (nada é gravado)
```

Contrato central: `ii.reference_analysis.v2`, com 6 estados de evidência. O conhecimento externo é um tipo de fonte (`external_knowledge`) e só vale como `inference`. Quadros amostrados nunca provam mecanismo de movimento: só `video_clip` sustenta `temporal_sequence`.

## 2. Dependências

| Item | Requisito | Observação |
|---|---|---|
| Python | testado em 3.13.16 (Linux) | Sem pacotes externos. Conferir no Python do Windows |
| SQLite | ≥ 3.24 (UPSERT, comparação de tuplas) | FTS5 e JSON1 não são usados |
| Projeto-MVP | só leitura | Necessário apenas para os 10 testes opt-in (`PROJETO_MVP_DIR`) |
| ffmpeg / whisper / modelos | **não** usados pelo `ii_mm` | O Antigravity produz os artefatos; o núcleo só lê |

## 3. Pontos de adaptação

| Ponto | Onde | O que o Antigravity ajusta |
|---|---|---|
| Valores reais de `tipo` das observações da Fase 5 | `legacy.FICHA_TIPO_TO_TAG` | Conferir com `revisao_visual_fase5.json` |
| Origem manual de `editorial_category` | `legacy.HUMAN_EDITORIAL_SOURCES` | Confirmar os valores usados no painel |
| Léxico de ferramentas | `vocabulary.TOOL_LEXICON`, `AI_TOOLS` | Ampliar com as ferramentas do nicho |
| Pistas textuais e narrativas | `text_classifier.RULES`, `narrative.TEXT_CUES/TEXT_EXCLUDE` | Revisar com o curador; cada mudança roda contra o golden |
| Duração da mídia | `legacy.from_instagram_item(duration_s=…)` ou `media_duration_sec` | Sem duração o documento não é montado (bloqueio explícito) |
| Diretório de staging | `obsidian_export.export_reference(doc, staging)` | Qualquer pasta fora do Vault |

## 4. Estágios de adoção

### Estágio 1: compatibilidade e testes isolados (sem tocar em nada do projeto)

1. Copiar `proposals/` para uma pasta fora do projeto (ou usar esta branch).
2. Conferir a integridade: `python3 tools/build_handoff.py --check` deve imprimir `pacote ok`.
3. Rodar `python3 run_tests.py`: 307 testes, 297 OK e 10 pulados.
4. Rodar `PROJETO_MVP_DIR=<clone local> python3 run_tests.py`: os 307 devem passar. Isso confere DDL real, regressão de `curation.py`, modo sombra com a função legada real, vazamento de conexões e isolamento das fixtures.
5. Revisar `MATRIZ_COMPATIBILIDADE.md` e marcar o que divergir do estado local.

**Critério de saída:** suíte verde no Windows, com e sem `PROJETO_MVP_DIR`. Qualquer falha opt-in indica diferença entre o estado local e o publicado (`c6845a4`) e é registrada antes de seguir.

### Estágio 2: modo sombra, sem alterar classificações existentes

1. `python3 handoff/exemplo_uso.py --legacy-db <catalog.sqlite> --out <pasta fora do Vault> --limit 200`. Leitura `mode=ro`, zero gravações.
2. Revisar `relatorio_sombra.md`. Para cada divergência, conferir as evidências citadas. Registrar em planilha ou nota: concorda com o atual, com o novo, com nenhum.
3. Opcional, num banco **novo e separado** (`storage/ii_v2.sqlite`, nunca `catalog.sqlite`): `open_database()` + `Repository.save_analysis()` para os itens com mídia e pacote de evidências.
4. Opcional, n8n: só um workflow **novo**, apontando para o gateway local e com segredo HMAC próprio. Nenhum workflow existente é editado.

**Critério de saída:** pelo menos 50 itens revisados por humano no relatório de sombra, com o registro das decisões. Isso é insumo para o Estágio 3, não autorização.

### Estágio 3: avaliação humana e decisão de adoção (NÃO autorizado automaticamente)

Requer, por escrito: (a) o registro da revisão humana do Estágio 2; (b) a decisão do responsável sobre quais categorias passam a ser **sugeridas** no painel; (c) o plano de rollback assinado. Mesmo adotado, o novo classificador continua como **sugestão**: a decisão de curadoria segue humana.

## 5. Desligado no início (e por quê)

| Funcionalidade | Estado inicial | Motivo |
|---|---|---|
| `MeasuredRule` (medição sustentando categoria) | desligada | Limiares não calibrados |
| Gravar em `catalog.sqlite` | proibido (`connect()` recusa o nome) | O banco v2 é separado |
| Substituir `curation.suggest_editorial_category` | não fazer | Só depois do Estágio 3 |
| Exportar para o Vault real | proibido (`assert_staging`) | Copiar do staging continua manual |
| Gateway n8n exposto além de `127.0.0.1` | não fazer | Contrato pensado para uso local com HMAC |
| Aplicar `patches/legacy_close_sqlite_connections.diff` | decisão do Antigravity | Patch validado numa cópia; aplicar é mudança no legado |
| Modelos pagos via missão | proibidos por padrão | Exigem `max_usd > 0` e `approved_by` |

## 6. Testes de aceitação

| Teste | Comando | Prova |
|---|---|---|
| Suíte completa | `python3 run_tests.py` | Núcleo íntegro |
| Compatibilidade real | `PROJETO_MVP_DIR=… python3 run_tests.py` | DDL, regressão, sombra, conexões, isolamento |
| Pacote íntegro | `python3 tools/build_handoff.py --check` | Arquivos e contratos iguais aos revisados |
| Ponta a ponta com queda e reenvio | `python3 -m unittest tests.test_ms02_e2e` | Retomada, idempotência, integridade |
| Demonstração | `python3 -m ii_mm.demo` | Fluxo completo em diretório temporário |
| Benchmark (opcional) | `python3 tools/benchmark.py --sizes 82,1000` | Desempenho no ambiente Windows (não comparar direto com a nuvem) |

## 7. Rollback

Ver `RISCO_E_ROLLBACK.md`. Em resumo: os Estágios 1 e 2 não alteram o projeto, então o rollback é apagar a pasta copiada, o banco `ii_v2.sqlite` (se criado), a pasta de staging e o workflow n8n novo (se criado).

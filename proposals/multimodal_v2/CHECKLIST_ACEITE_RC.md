# Checklist de aceite: `ii_mm-1.0.0-rc1`

Etapa 19 da Missão Suprema 03. Marque cada item com a evidência (arquivo ou saída). Um item sem evidência conta como não cumprido. Os comandos estão em `GUIA_WINDOWS_POWERSHELL.md`; os critérios C1 a C10, em `CRITERIOS_ADOCAO.md`.

## Estágio 1: testes isolados

Pode ser executado pelo Antigravity sem aprovação adicional. Nada do Projeto-MVP é alterado.

- [ ] Código obtido numa pasta **nova**, fora do Projeto-MVP, no commit publicado no HANDOFF (`git -C <repo> rev-parse HEAD`)
- [ ] `ii_rc.ps1 -Etapa Conferir -ManifestoSha256 <hash do HANDOFF>` → `OK: pacote íntegro e ambiente compatível`
- [ ] Versões registradas (linha `Python … SQLite …` do validador): Python ≥ 3.11, SQLite ≥ 3.24
- [ ] Executado em Windows PowerShell 5.1 **e** PowerShell 7, ou registrado qual dos dois foi usado
- [ ] `-Etapa Testes` sem projeto: `OK (skipped=N)`; log guardado
- [ ] `-Etapa Testes` com `-ProjetoMvp`: `OK`; log guardado
- [ ] `git status --short` do Projeto-MVP idêntico antes e depois (C2)
- [ ] Nenhum `__pycache__` ou arquivo novo dentro do pacote (rodar `-Etapa Conferir` de novo ao final)
- [ ] `-Etapa Compatibilidade`: `compativel_com_baseline: true`, ou cada diferença analisada por escrito (C3)
- [ ] Revisão dos itens NÃO VERIFICADO de `MATRIZ_COMPATIBILIDADE.md` que o ambiente local permite conferir (valores reais de `tipo` da Fase 5; origens reais de `editorial_category_source`)
- [ ] Falhas, se houver, registradas com saída completa e devolvidas ao Claude Cloud. **Não corrigir localmente o pacote**

**Saída do Estágio 1:** relatório de compatibilidade e logs. Só prosseguir com todos os itens marcados ou com as exceções aceitas por escrito.

## Estágio 2: modo sombra

Pode ser executado pelo Antigravity. Nenhuma classificação existente é alterada.

- [ ] Snapshot feito pela etapa `Sombra` (origem aberta só para leitura); hash do catálogo anotado antes e depois, numa janela sem outras escritas (C1)
- [ ] `PRAGMA integrity_check` do snapshot = `ok`
- [ ] `relatorio_sombra.json`/`.md` e `revisao_divergencias.csv` gerados **fora** do projeto e do Vault
- [ ] Segunda execução sobre o mesmo snapshot com o mesmo resultado (C5)
- [ ] Decisões humanas do catálogo aparecem como decisão humana e não foram reclassificadas (conferir no relatório 3 itens com `editorial_category` manual)
- [ ] Divergências revisadas pelo curador na planilha (C7a)
- [ ] Avaliação de 30 a 50 vídeos concluída (`AVALIACAO_HUMANA.md`): `concordancia.json` e o registro da amostra (C7b)
- [ ] Tempos do snapshot e da sombra registrados; nenhum impacto percebido no painel (C8)
- [ ] (Opcional) Banco v2 **separado** (`ii_v2.sqlite`, fora de pasta sincronizada): `integrity_check` ok e salvamento repetido sem duplicar (C1, C5)
- [ ] (Opcional) Workflow n8n **novo** com segredo próprio; nenhum workflow existente editado (C2)
- [ ] Ensaio de rollback de cada artefato criado (C9)
- [ ] Resultados devolvidos ao Claude Cloud (HANDOFF, ponto 12)

**Saída do Estágio 2:** evidências para a decisão. **Não é autorização.**

## Estágio 3: integração supervisionada

**Exige aprovação humana explícita.** Nenhum item abaixo pode ser marcado por um agente.

- [ ] Estágios 1 e 2 completos, com evidências anexadas
- [ ] Documento de decisão (C10) assinado pelo responsável pelo projeto, com:
  - categorias que passam a ser **sugeridas**;
  - onde aparecem no painel;
  - quem revisa;
  - como desligar.
- [ ] Plano de rollback específico do escopo aprovado, com o ensaio registrado
- [ ] Mudanças no Projeto-MVP feitas pelo Antigravity em branch própria, revisadas por humano antes do merge
- [ ] Testes do legado e a suíte da RC verdes depois da mudança
- [ ] Período de observação definido, com critério de reversão (`RISCO_E_ROLLBACK.md`)

| Aprovação | Nome | Data | Escopo |
|---|---|---|---|
| Responsável pelo projeto | | | |

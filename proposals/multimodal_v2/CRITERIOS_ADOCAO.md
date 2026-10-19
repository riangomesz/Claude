# Critérios de adoção do `ii_mm`

Etapa 09 da Missão Suprema 03. **Não existe adoção automática.** Cumprir todos os critérios torna a RC *elegível* para o Estágio 3. A decisão de adotar é humana, registrada por escrito pelo responsável pelo projeto, e cobre só o escopo escrito na decisão. Mesmo adotado, o classificador novo produz **sugestões**: a decisão de curadoria continua humana.

Cada critério diz como verificar, que evidência registrar e o que bloqueia. Não há limiares numéricos inventados: onde não existe calibração, o critério exige a evidência e a decisão humana sobre ela.

| # | Critério | Como verificar | Evidência a registrar | Bloqueia se |
|---|---|---|---|---|
| C1 | **Integridade do banco** | (a) Catálogo legado: hash antes e depois da sombra com `Get-FileHash`, numa janela sem outras escritas; `PRAGMA integrity_check` no **snapshot**. (b) Banco v2 (se criado): `PRAGMA integrity_check` e `PRAGMA foreign_key_check` | Hashes, saída dos PRAGMAs | Hash do catálogo mudar por causa do `ii_mm`; qualquer erro de integridade |
| C2 | **Nenhuma alteração não autorizada** | `git status --short` no Projeto-MVP antes e depois (deve ser idêntico); nenhum arquivo novo no Vault; nenhum workflow n8n editado; pasta do pacote sem arquivos novos (o validador acusa extras) | Saídas antes e depois | Qualquer diferença atribuível à RC |
| C3 | **Contratos compatíveis** | `ii_rc.ps1 -Etapa Compatibilidade`; testes opt-in verdes | `relatorio_compatibilidade.json` | Item `alterado` ou `ausente` sem análise registrada (diferença analisada e aceita não bloqueia) |
| C4 | **Testes locais** | `ii_rc.ps1 -Etapa Testes` no Windows, com e sem `PROJETO_MVP_DIR`, no Python que será usado em produção | `testes_sem_projeto.log`, `testes_com_projeto.log`, saída do validador (versões de Python e SQLite) | Qualquer falha ou erro sem causa registrada |
| C5 | **Idempotência** | Rodar a sombra duas vezes sobre o mesmo snapshot (pastas diferentes): `relatorio_sombra.json` igual nos totais e nos itens. No banco v2: salvar a mesma análise duas vezes não cria linha nova (coberto por `test_repository` e `test_ms02_e2e`) | Comparação dos dois relatórios | Resultado diferente para a mesma entrada |
| C6 | **Tratamento de falhas** | Coberto pela suíte: queda no meio da gravação faz rollback (`test_ms02_recovery`), lease perdido não sobrescreve o novo dono (`test_ms03_lease`), snapshot desiste em vez de esperar indefinidamente (`test_ms03_shadow`), entrada malformada vira relatório e não exceção (`test_ms02_adversarial`). No Windows: interromper uma etapa com Ctrl+C e rodá-la de novo | Log da interrupção e da retomada | Estado inconsistente após interrupção; arquivo travado que exija reiniciar a máquina |
| C7 | **Revisão humana das divergências** | (a) `revisao_divergencias.csv` com as divergências do lote revisadas. (b) Avaliação de 30 a 50 vídeos (`AVALIACAO_HUMANA.md`) | Planilhas preenchidas, `concordancia.json`, notas do curador | Divergências não revisadas; categoria com falso positivo recorrente sem decisão (corrigir regra, desligar a categoria ou aceitar) |
| C8 | **Desempenho** | Tempo da sombra para o lote; tempo do snapshot do catálogo real; espera máxima observada por escritores do legado durante o snapshot (se algum rodar). Referência na nuvem: `BENCHMARK.md` e a seção E do guia (139 MB em cerca de 1,8 s; espera máxima de escritor de 0,18 s) | Tempos medidos no Windows | Snapshot ou consulta que atrapalhe o uso normal do painel, segundo o operador |
| C9 | **Plano de rollback** | Para cada artefato criado, o desfazer correspondente de `RISCO_E_ROLLBACK.md` foi **ensaiado** (por exemplo, apagar `ii_v2.sqlite` e confirmar que o painel continua igual) | Registro do ensaio | Algum artefato sem caminho de reversão testado |
| C10 | **Escopo escrito** | Documento de decisão com: categorias que passam a ser sugeridas, onde aparecem, quem revisa, como desligar | Documento assinado | Ausente: sem ele não há Estágio 3 |

## O que continua proibido mesmo com todos os critérios cumpridos

- Gravar no `catalog.sqlite`: `connect()` recusa o nome; o banco v2 é separado.
- Sobrescrever decisões humanas (`editorial_category` manual, `triage_decision`, revisões).
- Substituir `curation.suggest_editorial_category` sem decisão específica.
- Exportar direto para o Vault: só staging, cópia manual.
- Ligar `MeasuredRule` (limiares não calibrados).
- Executar modelos pagos pela missão n8n sem `max_usd > 0` e `approved_by`.
- Aplicar o patch L1 sem os testes legados antes e depois. A decisão é do Antigravity, como mudança do legado.

## Quem decide

| Decisão | Responsável |
|---|---|
| Executar Estágios 1 e 2 | Antigravity (operador local) |
| Aceitar diferenças de contrato (C3) | Antigravity, com registro |
| Julgar divergências e rótulos (C7) | Curador humano |
| Adotar (Estágio 3) | Responsável pelo projeto, por escrito |
| Reverter | Qualquer um dos acima, a qualquer momento, pelos critérios de `RISCO_E_ROLLBACK.md` |

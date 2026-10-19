# Handoff para o Antigravity: Release Candidate `ii_mm-1.0.0-rc1`

| Campo | Valor |
|---|---|
| Identificador da RC | `ii_mm-1.0.0-rc1` (`ii_mm.__version__ = "1.0.0rc1"`); **sem tag pública** |
| Repositório e branch | `riangomesz/Claude`, branch `claude/instagram-intelligence-audit-4ezsd1` |
| Commit do código da RC | `d0e1916099bc945a7e8478a4d14b55c919ce4c40` (último commit que altera arquivos do manifesto; commits posteriores da branch só acrescentam documentos fora dele) |
| SHA-256 do manifesto (LF) | `10f0e9d88afaa435f5ad1e4899bcb6b942fff812f9831554c34671898e75e209` |
| Manifesto | `proposals/multimodal_v2/handoff/MANIFESTO_PACOTE.json` (`ii.handoff_manifest.v2`, 119 arquivos, hash por arquivo com CRLF normalizado) |
| Zip determinístico (opcional) | `python -X utf8 tools/build_handoff.py --zip <destino>` → `sha256=355a0c2568251d902c20651b3c323fc18b9172fa47759e0a2b9cae7c3f0f6678` com zlib 1.3. Com outra versão do zlib, o hash do zip pode mudar; o hash do **manifesto** não muda |
| Base do Projeto-MVP verificada | clone publicado `c6845a4` (o estado local pode ter avançado) |

Este documento fica **fora** do manifesto de propósito: ele publica o hash que confere o manifesto.

## 1. O que foi construído

O `ii_mm` é um núcleo isolado, só com a biblioteca padrão, que classifica referências audiovisuais por **evidências com proveniência**.

- **Evidências:** 6 estados (observada, medida, dita na fala, metadado, inferência, não verificada). Não há porcentagem de confiança.
- **Contrato:** `ii.reference_analysis.v2`.
- **Adaptadores** para artefatos que o Windows já produz: SRT, segmentos, ffprobe, cenas, manifestos de quadros, observações.
- **Adaptadores do legado:** linhas de `instagram_items` com 65 colunas, `VisualMacroAnalysis`, candidatos de transição, fichas v1/v2.
- **Banco próprio:** SQLite com migrações versionadas, catálogo paginado, revisão humana com histórico, pipeline com lease e heartbeat.
- **Contrato n8n** com HMAC e exportação para staging do Obsidian.
- **Modo sombra** que compara o classificador atual com o novo sem gravar nada.
- **Fluxo de avaliação humana** para 30 a 50 vídeos.

Mapa completo em `INVENTARIO_COMPONENTES.md`.

Novidades desta RC (Missão Suprema 03):
- pacote autossuficiente com validador de recebimento;
- script PowerShell guiado;
- correções de portabilidade para Windows (W2–W6, PS1, PS2);
- D-RC1 a D-RC5: pacote incompleto, origem editorial nula tratada como automática, injeção no relatório da sombra, lease perdido sobrescrevendo outro executor, snapshot bloqueando escritores do legado.

## 2. O que foi testado (nuvem, Linux)

| Execução | Resultado |
|---|---|
| Suíte sem `PROJETO_MVP_DIR`, Python 3.11.17 / 3.12.3 / 3.13.16 | 384 testes: 371 OK + 13 pulados (opt-in), nas 3 versões |
| Suíte com `PROJETO_MVP_DIR` = **cópia** descartável do clone `c6845a4`, nas 3 versões | 384 OK nas 3 versões |
| `-W error::ResourceWarning` sem o clone | OK (nenhuma conexão vazada pelo `ii_mm`) |
| Autoteste do pacote: zip montado, extraído, validado e com a própria suíte executada a partir da cópia extraída | OK (teste `SelfContainedPackageTest`) |
| Validador contra adulterações (arquivo ausente, modificado ou extra, manifesto forjado, versões, caminhos perigosos, `managed_dirs` fora do pacote) | OK (`test_ms03_receiver`) |
| `ii_rc.ps1` em todas as etapas e recusas, com **PowerShell 7.4.6 no Linux** | OK, inclusive `-Etapa Tudo` com o hash do manifesto |
| Clone do Projeto-MVP após tudo | `git status` vazio, nenhuma pasta criada |

Todos os dados de teste são **sintéticos**. O vídeo-piloto `DQV5dm6gCvH` continua `blocked_missing_evidence`: os anexos não estavam disponíveis, e a demonstração sintética **não é** análise dele.

## 3. O que precisa ser validado no Windows

Detalhes em `DEPENDENCIAS_WINDOWS.md`, seção 4.

1. Suíte inteira no Python local, com e sem `-ProjetoMvp`.
2. `ii_rc.ps1` no **Windows PowerShell 5.1** e no **PowerShell 7**. Na nuvem, só o 7 no Linux foi testado.
3. Limpeza de temporários sem `PermissionError` (travas de arquivo do Windows).
4. Relatório de compatibilidade contra o Projeto-MVP **local** (pode ter avançado além de `c6845a4`).
5. Valores reais de `tipo` da Fase 5 (`revisao_visual_fase5.json`) e de `editorial_category_source`.
6. Tempo do snapshot do catálogo real.

## 4. Como obter o código

Numa pasta **nova**, fora do Projeto-MVP (PowerShell):

```powershell
$Raiz = 'C:\ii_rc'
New-Item -ItemType Directory -Path $Raiz
git clone --branch claude/instagram-intelligence-audit-4ezsd1 --single-branch https://github.com/riangomesz/Claude.git "$Raiz\repo"
git -C "$Raiz\repo" log --oneline -1
$Pacote = "$Raiz\repo\proposals\multimodal_v2"
```

A branch pode ter commits de documentação depois de `d0e1916`; o manifesto é o mesmo. Para ficar exatamente no commit do código: `git -C "$Raiz\repo" checkout --detach d0e1916`.

## 5. Como validar os hashes

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$Pacote\handoff\windows\ii_rc.ps1" -Etapa Conferir -PacoteDir $Pacote -ManifestoSha256 10f0e9d88afaa435f5ad1e4899bcb6b942fff812f9831554c34671898e75e209
```

Esperado: `OK: pacote íntegro e ambiente compatível`. Qualquer `INTEGRIDADE:` significa parar. Códigos de saída e interpretação: `GUIA_WINDOWS_POWERSHELL.md`, seção A.

## 6. Como executar os testes isolados

```powershell
$Trabalho = "$Raiz\trabalho"
$ProjetoMvp = 'C:\caminho\do\Projeto-MVP'
$Script = "$Pacote\handoff\windows\ii_rc.ps1"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File $Script -Etapa Preparar -PacoteDir $Pacote -TrabalhoDir $Trabalho -ProjetoMvp $ProjetoMvp
powershell.exe -NoProfile -ExecutionPolicy Bypass -File $Script -Etapa Testes   -PacoteDir $Pacote -TrabalhoDir $Trabalho -ProjetoMvp $ProjetoMvp
```

Esperado: `OK (skipped=13)` sem o projeto e `OK` com ele (384 testes). Os testes que usam o projeto copiam `core/`, `config/` e `temporal_intelligence/` para uma pasta temporária. **O Projeto-MVP não é tocado.**

## 7. Como comparar com o Projeto-MVP atual

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File $Script -Etapa Compatibilidade -PacoteDir $Pacote -TrabalhoDir $Trabalho -ProjetoMvp $ProjetoMvp
```

Gera `$Trabalho\relatorio_compatibilidade.json`: assinaturas de 13 módulos, valores literais e as 65 colunas de `instagram_items`, comparados com `c6845a4`. Diferenças são esperadas se o projeto avançou. Registre cada uma e confira com `MATRIZ_COMPATIBILIDADE.md`.

## 8. Como executar o modo sombra

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File $Script -Etapa Sombra -PacoteDir $Pacote -TrabalhoDir $Trabalho -CatalogoDb "$ProjetoMvp\storage\catalog.sqlite" -Limite 200
```

- O catálogo é copiado por snapshot, com a origem aberta em `mode=ro`, em blocos e com desistência após 120 s se estiver travado.
- A comparação roda sobre a cópia. Nada é gravado no catálogo e decisões humanas não são reclassificadas.
- Saídas: `relatorio_sombra.json`/`.md` e `revisao_divergencias.csv`.
- Prefira rodar fora de uma importação em massa.

## 9. Como registrar divergências

1. Abra `$Trabalho\sombra\revisao_divergencias.csv` (UTF-8 com BOM; abre no Excel).
2. Para cada linha, consulte as evidências do item em `relatorio_sombra.md` e preencha as colunas do revisor: com quem concorda (atual, novo, nenhum) e por quê.
3. Para medir o classificador, siga `AVALIACAO_HUMANA.md`. A amostra de 30 a 50 vídeos é rotulada às cegas com `tools/avaliacao.py amostra` e a concordância sai com `tools/avaliacao.py concordancia`, em contagens.

## 10. Como reverter uma instalação experimental

| Criado | Como desfazer |
|---|---|
| `$Trabalho` (logs, relatórios, snapshot) | `-Etapa Limpar` (apaga só a pasta com o marcador `.ii_rc_trabalho`) |
| `$Raiz\repo` e `$Raiz\venv` opcional | Conferir com `Get-ChildItem -LiteralPath $Raiz` e então `Remove-Item -LiteralPath "$Raiz\repo" -Recurse -Force` |
| Banco v2 opcional (`ii_v2.sqlite` + `-wal`/`-shm`) | Apagar os três arquivos; o catálogo legado não o referencia |
| Workflow n8n novo opcional | Desativar e apagar; revogar o segredo HMAC |

Nenhum passo deste handoff altera o Projeto-MVP. Portanto, para Estágios 1 e 2, não há reversão no projeto. Rollback completo por estágio: `RISCO_E_ROLLBACK.md`.

## 11. Alterações que continuam proibidas

- Gravar no `catalog.sqlite` (o código recusa) ou sobrescrever decisões humanas.
- Substituir `curation.suggest_editorial_category`, alterar workflows n8n existentes ou escrever no Vault (só staging).
- Integrar ao Projeto-MVP (Estágio 3) sem a decisão escrita de `CRITERIOS_ADOCAO.md` (C10). Nenhum agente pode autorizá-la.
- Aplicar `patches/legacy_close_sqlite_connections.diff` sem os testes legados antes e depois.
- Corrigir o pacote localmente. Falhas voltam ao Claude Cloud; o validador acusaria a alteração.
- Ligar `MeasuredRule` ou executar modelos pagos pela missão n8n.

## 12. Como devolver os resultados ao Claude Cloud

Reúna numa pasta, **sem** bancos, mídia, `.env`, tokens nem caminhos pessoais desnecessários:

1. Saída completa de `-Etapa Conferir`: linhas `RC:` e `Python … SQLite …`.
2. `testes_sem_projeto.log` e `testes_com_projeto.log`.
3. `relatorio_compatibilidade.json`.
4. Totais do modo sombra (`relatorio_sombra.json`, campo `totals`) e a planilha de divergências revisada. Se contiver legendas privadas, envie só totais e decisões.
5. Se feita: `concordancia.json` e `planilha_avaliacao.amostra.json`.
6. Checklist (`CHECKLIST_ACEITE_RC.md`) com o que foi marcado e as evidências.
7. Versão do Windows, do PowerShell (`$PSVersionTable.PSVersion`) e do Python.

Para entregar, cole o conteúdo numa nova sessão do Claude Code na nuvem nesta mesma branch, ou anexe os arquivos. O Claude Cloud corrige o que for defeito do pacote, gera uma nova RC (`rc2`) com novo hash de manifesto e devolve um novo handoff.

O prompt pronto para o agente está em `PROMPT_ANTIGRAVITY_VALIDACAO_ISOLADA.md`.

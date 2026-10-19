# Guia PowerShell: validação isolada da RC `ii_mm-1.0.0-rc1` no Windows

Etapa 06 da Missão Suprema 03. Serve para uma pessoa e para um agente (Antigravity). Cada seção tem objetivo, comandos, resultado esperado e o que fazer se falhar.

**O que este guia nunca faz:**
- não instala pacotes;
- não altera o Projeto-MVP;
- não abre o catálogo para escrita;
- não para serviços;
- não edita workflows n8n nem o Vault;
- não usa comandos de remoção amplos.

A única remoção (seção F) apaga uma pasta criada pelo próprio script e marcada por ele.

**Como os comandos foram verificados:** o script `handoff/windows/ii_rc.ps1` foi executado etapa por etapa com **PowerShell 7.4.6 no Linux**, inclusive todos os casos de recusa (pasta de trabalho dentro do projeto ou do pacote, pasta alheia sem marcador, sombra repetida, pacote errado). **Não foi executado no Windows nem no Windows PowerShell 5.1.** O script evita recursos exclusivos do 7 e é ASCII puro, porque o 5.1 lê scripts sem BOM como ANSI. Conferir isso é parte do Estágio 1.

## Convenções

Abra o PowerShell **sem** privilégios de administrador. Os exemplos usam estas variáveis; ajuste os caminhos:

```powershell
$Raiz       = 'C:\ii_rc'                                   # pasta NOVA, fora do Projeto-MVP (caminho curto: limite de 260 caracteres)
$Pacote     = "$Raiz\repo\proposals\multimodal_v2"
$Trabalho   = "$Raiz\trabalho"                             # criada e apagada pelo script (seções B e F)
$ProjetoMvp = 'C:\caminho\do\Projeto-MVP'                  # SOMENTE LEITURA
$Catalogo   = "$ProjetoMvp\storage\catalog.sqlite"         # SOMENTE LEITURA (o script copia por snapshot)
$Script     = "$Pacote\handoff\windows\ii_rc.ps1"
```

Para chamar o script sem alterar a política de execução da máquina, use `-ExecutionPolicy Bypass` na linha de comando. Isso vale só para esse processo:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File $Script -Etapa Conferir -PacoteDir $Pacote
# ou, no PowerShell 7:
pwsh.exe -NoProfile -ExecutionPolicy Bypass -File $Script -Etapa Conferir -PacoteDir $Pacote
```

O script procura o Python nesta ordem: `py -3`, `python`, `python3`. Para fixar um executável, passe `-Python 'C:\Caminho\python.exe'`, só o caminho, sem argumentos. Toda chamada usa `-I -B -X utf8`:
- `-I` ignora `PYTHONPATH` e o site do usuário;
- `-B` não grava `__pycache__` dentro do pacote;
- `-X utf8` evita `cp1252`.

## A. Conferência dos arquivos

**Objetivo:** obter o código numa pasta nova e provar que ele é exatamente o publicado, **antes** de executar qualquer código do pacote.

```powershell
New-Item -ItemType Directory -Path $Raiz                   # se já existir, escolha outra $Raiz
git clone --branch claude/instagram-intelligence-audit-4ezsd1 --single-branch https://github.com/riangomesz/Claude.git "$Raiz\repo"
git -C "$Raiz\repo" checkout --detach <COMMIT_DA_RC>       # commit publicado no HANDOFF
git -C "$Raiz\repo" status --short                         # deve sair vazio
powershell.exe -NoProfile -ExecutionPolicy Bypass -File $Script -Etapa Conferir -PacoteDir $Pacote -ManifestoSha256 <SHA256_DO_MANIFESTO>
```

`<COMMIT_DA_RC>` e `<SHA256_DO_MANIFESTO>` estão em `HANDOFF_ANTIGRAVITY_RELEASE_CANDIDATE.md`, fora do pacote. Sem `-ManifestoSha256`, um manifesto adulterado junto com os arquivos passaria despercebido.

Sem o script, o comando equivalente é:

```powershell
py -3 -I -B -X utf8 "$Pacote\handoff\verificar_recebimento.py" --manifest-sha256 <SHA256_DO_MANIFESTO>
```

O validador:
- usa só a biblioteca padrão;
- não importa o `ii_mm` e não grava nada;
- sonda o SQLite só em memória.

Ele confere:
- o hash do manifesto e a versão do manifesto;
- o identificador da RC;
- o Python mínimo, os módulos da stdlib e a versão do SQLite (UPSERT e comparação de tuplas);
- o hash de cada arquivo, com CRLF normalizado;
- arquivos ausentes, modificados ou extras nas pastas gerenciadas;
- caminhos perigosos no Windows: absoluto, `..`, `:`/ADS, nomes reservados, ponto final, colisão por caixa, comprimento.

| Resultado | Significado | Ação |
|---|---|---|
| `OK: pacote íntegro e ambiente compatível` (código 0) | Pode seguir | Anotar as linhas `RC:` e `Python … SQLite …` |
| `INTEGRIDADE: …` (código 1) | Arquivo ausente, modificado, extra ou manifesto diferente do publicado | **Parar.** Não executar o pacote; registrar a saída |
| `AMBIENTE: …` (código 2) | Python, SQLite ou módulo abaixo do necessário | Usar outro Python (`-Python`); não "consertar" o pacote |
| `FATAL: …` (código 3) | Manifesto ilegível ou de versão desconhecida | Parar e registrar |
| `aviso: cache de bytecode` | `__pycache__` criado por execução anterior sem `-B` | Inofensivo |

## B. Ambiente temporário isolado

**Objetivo:** criar a pasta de trabalho onde ficam logs, relatórios e snapshot. Não há ambiente virtual porque não há pacote a instalar: o isolamento vem de `-I -B` e de nunca gravar no pacote nem no projeto.

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File $Script -Etapa Preparar -PacoteDir $Pacote -TrabalhoDir $Trabalho -ProjetoMvp $ProjetoMvp
```

- Cria `$Trabalho` com o marcador `.ii_rc_trabalho`.
- **Recusa** uma pasta de trabalho dentro do Projeto-MVP ou do pacote.
- **Recusa** uma pasta que já existe sem o marcador, ou seja, que não foi criada pelo script.
- Sem `-TrabalhoDir`, o padrão é `%TEMP%\ii_rc_trabalho`.

Se a organização exigir um ambiente virtual, crie-o dentro de `$Raiz`. Ele é opcional e não muda o resultado:

```powershell
py -3 -m venv "$Raiz\venv"
# depois, em todas as etapas: -Python "$Raiz\venv\Scripts\python.exe"
```

## C. Execução dos testes

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File $Script -Etapa Testes -PacoteDir $Pacote -TrabalhoDir $Trabalho -ProjetoMvp $ProjetoMvp
```

Roda a suíte duas vezes, com logs UTF-8 em `$Trabalho`:

| Execução | Log | O que cobre |
|---|---|---|
| Sem `PROJETO_MVP_DIR` | `testes_sem_projeto.log` | Núcleo inteiro com dados sintéticos; os testes opt-in ficam pulados (`skipped`) |
| Com `PROJETO_MVP_DIR=$ProjetoMvp` | `testes_com_projeto.log` | Além disso: DDL real das 65 colunas, regressão de `curation.py`, sombra com a função legada real, contratos do relatório de compatibilidade, vazamento de conexões do legado |

**O projeto não é alterado:** os testes opt-in copiam `core/`, `config/` e `temporal_intelligence/` para uma pasta temporária (sem bancos nem mídia) e trabalham só na cópia. A variável de ambiente é restaurada ao fim, mesmo em erro.

**Resultado esperado:** última linha `OK` ou `OK (skipped=N)` nas duas execuções. As contagens exatas estão no HANDOFF.

| Sintoma | Interpretação |
|---|---|
| Falha só com o projeto | O código local avançou além do commit `c6845a4`; seguir para a seção D e registrar |
| `PermissionError` ao apagar pasta temporária | Arquivo aberto (antivírus, indexador ou conexão não fechada); registrar o caminho e repetir uma vez |
| `ResourceWarning` citando `core/` | Risco L1 do legado (conexões SQLite não fechadas), conhecido e não alterado |
| `UnicodeDecodeError` | Encoding: registrar o teste e o arquivo; não deveria ocorrer com `-X utf8` |

## D. Comparação com o código atual do Projeto-MVP

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File $Script -Etapa Compatibilidade -PacoteDir $Pacote -TrabalhoDir $Trabalho -ProjetoMvp $ProjetoMvp
```

Gera `$Trabalho\relatorio_compatibilidade.json`, comparando o projeto local com `handoff/baseline_contratos_c6845a4.json`:
- assinaturas de 13 módulos, lidas por AST, sem importar nada;
- valores literais (origem padrão de `editorial_category`, decisões de triagem válidas);
- colunas reais de `instagram_items`, obtidas num banco temporário montado a partir de uma cópia de `core/` e `config/`.

A ferramenta recusa gravar o relatório dentro do projeto.

| Saída | Ação |
|---|---|
| `"compativel_com_baseline": true` (código 0) | Seguir para a seção E |
| `"compativel_com_baseline": false` e o aviso "Diferencas em relacao a baseline" (código 1) | Abrir o JSON. Itens `alterado`, `ausente` ou `novo` indicam o que mudou desde `c6845a4`; conferir a linha correspondente em `MATRIZ_COMPATIBILIDADE.md` antes do modo sombra |

## E. Modo sombra

**Objetivo:** comparar a classificação atual com a nova sem gravar nada no catálogo e gerar a planilha de divergências para revisão humana.

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File $Script -Etapa Sombra -PacoteDir $Pacote -TrabalhoDir $Trabalho -CatalogoDb $Catalogo -Limite 200
```

1. O script faz um snapshot do catálogo em `$Trabalho\sombra\snapshot_catalogo.sqlite` pela API de backup do SQLite, abrindo a origem com `mode=ro`.
   - A cópia anda em blocos e solta o bloqueio entre um bloco e outro. Medição com um banco sintético de 139 MB e um escritor gravando a cada 0,2 s: a maior espera do escritor foi de 0,18 s.
   - Se a origem estiver travada por mais de 120 s, o snapshot desiste e apaga a cópia parcial. Ele não compete com o projeto.
   - Mesmo assim, prefira rodar fora de uma importação em massa.
2. A comparação roda sobre o snapshot e gera em `$Trabalho\sombra`:

| Arquivo | Conteúdo |
|---|---|
| `relatorio_sombra.json` / `.md` | Concordâncias, divergências e a origem de cada classificação (evidências citadas). Textos externos neutralizados |
| `revisao_divergencias.csv` | Uma linha por divergência, com colunas em branco para o revisor. UTF-8 com BOM (abre no Excel); fórmulas neutralizadas |

Decisões humanas do catálogo (`editorial_category` manual, `triage_decision`) **não são reclassificadas**: aparecem como decisão humana. Sem `-CatalogoDb`, a etapa roda com fixtures sintéticas (`--demo`). **Isso não é análise real.**

A etapa recusa sobrescrever uma pasta `sombra` existente. Para repetir, use outra `-TrabalhoDir` ou a seção F.

**Para conferir que o catálogo não mudou**, compare o hash antes e depois. Se houver outra execução gravando no catálogo, o hash pode mudar por causa dela, não por causa da sombra:

```powershell
(Get-FileHash -Algorithm SHA256 -LiteralPath $Catalogo).Hash
```

## F. Encerramento e limpeza

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File $Script -Etapa Limpar -PacoteDir $Pacote -TrabalhoDir $Trabalho
```

- Apaga **somente** `$Trabalho`, e só se ela contiver o marcador `.ii_rc_trabalho`. Sem o marcador, recusa.
- **Antes**, copie os relatórios que serão devolvidos: `relatorio_compatibilidade.json`, `sombra\relatorio_sombra.*`, `sombra\revisao_divergencias.csv` e os `.log`.
- A cópia do repositório (`$Raiz\repo`) e o ambiente virtual opcional (`$Raiz\venv`) foram criados por você nas seções A e B. Remova-os manualmente, conferindo o caminho antes:

```powershell
Get-ChildItem -LiteralPath $Raiz                            # confira: só repo, venv (opcional) e nada do Projeto-MVP
Remove-Item -LiteralPath "$Raiz\repo" -Recurse -Force
Remove-Item -LiteralPath "$Raiz\venv" -Recurse -Force       # só se você criou
```

Nada fora de `$Raiz` e `$Trabalho` é criado pelo guia. Os arquivos temporários dos testes ficam em `%TEMP%` e são apagados pelos próprios testes.

## Tudo de uma vez (para agentes)

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File $Script -Etapa Tudo -PacoteDir $Pacote -TrabalhoDir $Trabalho -ProjetoMvp $ProjetoMvp -CatalogoDb $Catalogo -ManifestoSha256 <SHA256_DO_MANIFESTO>
```

Executa A (conferência), B, C, D (se houver `-ProjetoMvp`) e E, parando na primeira falha. Não executa F.

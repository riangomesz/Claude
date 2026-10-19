# Dependências e portabilidade para Windows

Etapa 03 da Missão Suprema 03. **A suíte passar no Linux não prova compatibilidade com o Windows.** Este documento separa três coisas: o que foi corrigido com teste, o que foi conferido só estaticamente e o que **não pôde ser verificado** na nuvem e precisa ser conferido no Estágio 1.

## 1. Requisitos

| Item | Requisito | Base da afirmação |
|---|---|---|
| Python | **3.11 ou superior** | Suíte executada em 3.11.15, 3.12 e 3.13.16 (Linux). Não há API exclusiva do 3.11 no código, e a sintaxe é conferida com `feature_version=(3, 10)`, mas 3.10 **não foi executado**, por isso o mínimo declarado é 3.11 |
| SQLite | **3.24.0 ou superior** (UPSERT `ON CONFLICT DO UPDATE` e comparação de tuplas na paginação) | O Python do Windows traz o próprio `sqlite3.dll`; `verificar_recebimento.py` imprime a versão e executa uma sonda em memória com UPSERT e comparação de tuplas |
| Pacotes externos | **nenhum** | `tests/test_ms03_portability.py` não precisa de rede; o inventário (`tools/inventory.py`) lista só módulos da stdlib |
| Módulos da stdlib usados | `argparse`, `ast`, `base64`, `contextlib`, `copy`, `csv`, `dataclasses`, `datetime`, `hashlib`, `hmac`, `importlib`, `json`, `math`, `os`, `pathlib`, `random`, `re`, `sqlite3`, `tempfile`, `time`, `typing`, `unicodedata`, `urllib`, `uuid` (núcleo) e mais `shutil`, `subprocess`, `zipfile`, `trace`, `platform` nas ferramentas | Todos existem no Windows. `verificar_recebimento.py` confere a importação de cada um antes de qualquer execução |
| Módulos POSIX | **nenhum** no núcleo; `resource` só opcional no benchmark | W2 (abaixo) |
| PowerShell | `ii_rc.ps1` escrito para 5.1 e 7, sem sintaxe exclusiva do 7 | Executado com PowerShell **7.4.6 no Linux**; Windows PowerShell 5.1 **não testado** |
| ffmpeg, whisper, OpenCV, modelos | **não usados** pelo `ii_mm` | O núcleo só lê artefatos já produzidos |

## 2. Problemas encontrados e corrigidos (com teste)

| # | Problema | Efeito no Windows | Correção | Teste |
|---|---|---|---|---|
| W2 | `tools/benchmark.py` importava `resource` no topo | `ModuleNotFoundError` ao abrir o benchmark | Importação opcional; RSS vira `None` | `test_ms03_portability.W2BenchmarkWithoutResourceModuleTest` (subprocesso com `resource` bloqueado) |
| W3 | Caminho POSIX (`/proc/meminfo`) lido sem proteção | Exceção fora do Linux | Leitura protegida, construída com `os.sep` | Conferência estática de caminhos POSIX |
| W4 | Teste de symlink sem tratamento | Criar symlink exige privilégio ou modo desenvolvedor: o teste falharia | `OSError` vira `skipTest` explícito | `test_ms02_adversarial` |
| W5 | 5 leituras ou escritas de texto e `subprocess.run(text=True)` sem `encoding` | Padrão `cp1252`: acentos corrompidos ou `UnicodeDecodeError` | `encoding="utf-8"` em todos; subprocessos com `PYTHONUTF8=1` | Conferência estática: todo `read_text`/`write_text`/`subprocess.run(text=True)` declara encoding |
| W6 | URIs de artefato aceitavam `:` no meio, nomes de dispositivo e ponto ou espaço final | `video.mp4:oculto` grava num fluxo alternativo NTFS (ADS); `CON`/`NUL` não são arquivos; `nota.` vira `nota` | `n8n_contract._bad_uri` recusa os três casos em qualquer componente | `test_ms03_portability.W6MissionUriWindowsTest` |
| PS1 | Script `.ps1` em UTF-8 sem BOM com travessão e seta | O 5.1 lê como ANSI: o byte `0x94` do travessão vira aspa tipográfica, que o PowerShell trata como delimitador de string | Script em ASCII puro | `test_ms03_docs.PowerShellAsciiTest` |
| PS2 | `Invoke-Py` devolvia a saída do Python misturada ao código de saída; resultado de um elemento virava string (`$py[0]` = primeiro caractere) | Etapas sempre falhando ou executando `p` em vez de `python` | `@(...)`, saída via `Write-Host`, `2>&1` com `ErrorActionPreference=Continue` só durante a chamada | Execução funcional com pwsh 7.4.6 (registro no relatório da missão) |

## 3. Conferido estaticamente (sem execução no Windows)

- **Nomes de arquivo do pacote:** nenhum nome reservado (`CON`, `PRN`, `AUX`, `NUL`, `COM1`–`COM9`, `LPT1`–`LPT9`), nenhum caractere proibido (`<>:"|?*`), nenhum ponto ou espaço final, nenhuma colisão por caixa e caminhos relativos com menos de 160 caracteres (`test_ms03_portability`). Como o limite clássico do Windows é 260 (`MAX_PATH`), extraia o pacote numa pasta curta, por exemplo `C:\ii_rc`.
- **Finais de linha:** `proposals/.gitattributes` fixa LF para `.py`, `.md`, `.json`, `.diff` e `.ps1`. Mesmo que o Git converta para CRLF (`core.autocrlf=true`), o manifesto usa `sha256_lf` (CRLF normalizado para LF antes do hash), então a conferência não acusa falso positivo.
- **Caminhos:** o código usa `pathlib`/`os.path`; nenhum separador `/` fixo em caminho de sistema de arquivos. URIs internas (`artifact://…`) usam `/` por contrato.
- **Escrita atômica:** `obsidian_export` usa `os.replace`, que no Windows substitui o destino só se nenhum outro processo o tiver aberto. Um Vault aberto no Obsidian não é afetado, porque a exportação vai sempre para staging.
- **Relógio:** pipeline e lease recebem o relógio por injeção, e os testes não usam `sleep`. A resolução de relógio do Windows (cerca de 15,6 ms) não afeta a suíte.

## 4. Não verificado na nuvem (conferir no Estágio 1)

| Item | Por que não foi possível | Como conferir no Windows |
|---|---|---|
| Execução real da suíte no Windows | Não há Windows no contêiner | `ii_rc.ps1 -Etapa Testes` (logs em UTF-8 na pasta de trabalho) |
| Windows PowerShell 5.1 | Só o pwsh 7.4.6 estava disponível (no Linux) | Rodar `ii_rc.ps1` em `powershell.exe` (5.1) e em `pwsh.exe` (7) |
| Trava de arquivo ao apagar pastas temporárias | Linux permite apagar arquivo aberto; o Windows não | A suíte usa `TemporaryDirectory`; um `PermissionError` na limpeza indica conexão SQLite não fechada |
| WAL em pasta somente leitura ou sincronizada (OneDrive) | O contêiner roda como root (permissões ignoradas) | Não colocar `ii_v2.sqlite` em pasta sincronizada. O modo sombra lê o catálogo por snapshot, o que evita `-wal`/`-shm` ao lado do catálogo |
| Antivírus ou indexador segurando arquivos temporários | Não reproduzível aqui | Se a limpeza falhar de forma intermitente, registrar o caminho e repetir; não é falha de lógica |
| Python 3.10 | Não executado | Usar 3.11 ou superior |
| Console sem UTF-8 | Não reproduzível aqui | `ii_rc.ps1` usa `-X utf8` e ajusta `[Console]::OutputEncoding` só durante a chamada |

## 5. Risco herdado do legado (não alterado)

L1 (`RISCO_E_ROLLBACK.md`): no Python 3.13, `with sqlite3.connect()` do legado deixa a conexão aberta até o coletor de ciclos. No Windows isso pode travar o arquivo do banco. Nos testes opt-in isso aparece como `ResourceWarning` vindo de `core/` (código do Projeto-MVP), não do `ii_mm`. Para conferir o `ii_mm` isoladamente: `python -X utf8 -W error::ResourceWarning run_tests.py` **sem** `PROJETO_MVP_DIR`. A correção (`patches/legacy_close_sqlite_connections.diff`) é decisão do Antigravity.

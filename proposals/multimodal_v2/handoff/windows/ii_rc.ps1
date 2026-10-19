<#
.SYNOPSIS
    Validacao ISOLADA da Release Candidate ii_mm (Estagios 1 e 2). Nao altera o Projeto-MVP nem o catalogo.

.DESCRIPTION
    Etapas (uma por chamada, ou -Etapa Tudo):
      Conferir         valida o pacote (hashes, caminhos, Python, SQLite) ANTES de executar qualquer codigo dele
      Preparar         cria a pasta de trabalho temporaria com marcador proprio
      Testes           roda a suite sem e com PROJETO_MVP_DIR (os testes copiam o codigo do projeto para uma pasta temporaria)
      Compatibilidade  compara contratos com o Projeto-MVP atual (somente leitura; relatorio na pasta de trabalho)
      Sombra           modo sombra sobre SNAPSHOT do catalogo (origem aberta so para leitura)
      Limpar           apaga SOMENTE a pasta de trabalho criada por este script (exige o marcador)
    Compativel com Windows PowerShell 5.1 e PowerShell 7 (sem recursos exclusivos do 7).

.EXAMPLE
    .\handoff\windows\ii_rc.ps1 -Etapa Conferir -PacoteDir C:\ii_rc\proposals\multimodal_v2 -ManifestoSha256 <hash do handoff>
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('Conferir', 'Preparar', 'Testes', 'Compatibilidade', 'Sombra', 'Limpar', 'Tudo')]
    [string]$Etapa,
    [Parameter(Mandatory = $true)][string]$PacoteDir,
    [string]$ProjetoMvp = '',
    [string]$CatalogoDb = '',
    [string]$TrabalhoDir = '',
    [string]$ManifestoSha256 = '',
    [string]$Python = '',
    [int]$Limite = 200
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0
$Marcador = '.ii_rc_trabalho'

function Resolve-Python {
    if ($Python -ne '') { return @($Python) }
    if (Get-Command py -ErrorAction SilentlyContinue) { return @('py', '-3') }
    if (Get-Command python -ErrorAction SilentlyContinue) { return @('python') }
    if (Get-Command python3 -ErrorAction SilentlyContinue) { return @('python3') }
    throw 'Python nao encontrado. Informe -Python com o caminho do executavel (3.11 ou superior).'
}

function Invoke-Py {
    param([string[]]$Argumentos, [string]$Log = '')
    # @(...) evita que um resultado de um elemento vire string (e $py[0] vire o primeiro caractere)
    $py = @(Resolve-Python)
    $base = @()
    if ($py.Count -gt 1) { $base = $py[1..($py.Count - 1)] }
    # -I: isolado (ignora PYTHON* e site do usuario) | -B: nao grava bytecode | -X utf8: E/S em UTF-8
    $todos = @($base) + @('-I', '-B', '-X', 'utf8') + $Argumentos
    Write-Host ('> ' + $py[0] + ' ' + ($todos -join ' '))
    $linhas = New-Object System.Collections.Generic.List[string]
    $eapAnterior = $ErrorActionPreference
    $codificacaoAnterior = $null
    try { $codificacaoAnterior = [Console]::OutputEncoding; [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false) } catch { $codificacaoAnterior = $null }
    try {
        # No Windows PowerShell 5.1, stderr redirecionado vira ErrorRecord e, com 'Stop', interromperia na primeira linha
        $ErrorActionPreference = 'Continue'
        & $py[0] @todos 2>&1 | ForEach-Object { $s = "$_"; Write-Host $s; $linhas.Add($s) }
        $codigo = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $eapAnterior
        if ($null -ne $codificacaoAnterior) { try { [Console]::OutputEncoding = $codificacaoAnterior } catch { } }
    }
    if ($Log -ne '') { [System.IO.File]::WriteAllLines($Log, $linhas, (New-Object System.Text.UTF8Encoding($false))) }
    return $codigo
}

function Resolve-Caminho {
    # Relativo a pasta atual do PowerShell (Set-Location), nao ao diretorio do processo .NET
    param([string]$Caminho)
    if ($Caminho -eq '') { return '' }
    return $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($Caminho)
}

function Get-PastaTrabalho {
    if ($TrabalhoDir -ne '') { return Resolve-Caminho $TrabalhoDir }
    return [System.IO.Path]::Combine([System.IO.Path]::GetTempPath(), 'ii_rc_trabalho')
}

function Assert-ForaDe {
    param([string]$Caminho, [string]$Proibido, [string]$Nome)
    if ($Proibido -eq '') { return }
    $a = [System.IO.Path]::GetFullPath($Caminho).TrimEnd('\', '/') + [System.IO.Path]::DirectorySeparatorChar
    $b = [System.IO.Path]::GetFullPath($Proibido).TrimEnd('\', '/') + [System.IO.Path]::DirectorySeparatorChar
    if ($a.StartsWith($b, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Recusado: a pasta de trabalho nao pode ficar dentro $Nome ($Proibido)."
    }
}

$PacoteDir = Resolve-Caminho $PacoteDir
$ProjetoMvp = Resolve-Caminho $ProjetoMvp
$CatalogoDb = Resolve-Caminho $CatalogoDb
if (-not (Test-Path -LiteralPath ([System.IO.Path]::Combine($PacoteDir, 'run_tests.py')))) {
    throw "PacoteDir deve ser a pasta multimodal_v2 do pacote (nao encontrei run_tests.py em $PacoteDir)."
}
$Trab = Get-PastaTrabalho
Assert-ForaDe -Caminho $Trab -Proibido $ProjetoMvp -Nome 'do Projeto-MVP'
Assert-ForaDe -Caminho $Trab -Proibido $PacoteDir -Nome 'do pacote'

function Etapa-Conferir {
    $validador = [System.IO.Path]::Combine($PacoteDir, 'handoff', 'verificar_recebimento.py')
    $arg = @($validador)
    if ($ManifestoSha256 -ne '') { $arg += @('--manifest-sha256', $ManifestoSha256) }
    $code = Invoke-Py -Argumentos $arg
    if ($code -ne 0) { throw "Conferencia falhou (codigo $code). Nao execute o pacote." }
}

function Etapa-Preparar {
    if (Test-Path -LiteralPath $Trab) {
        if (-not (Test-Path -LiteralPath ([System.IO.Path]::Combine($Trab, $Marcador)))) {
            throw "A pasta $Trab ja existe e nao foi criada por este script. Escolha outra com -TrabalhoDir."
        }
        Write-Host "Pasta de trabalho ja preparada: $Trab"
        return
    }
    New-Item -ItemType Directory -Path $Trab | Out-Null
    Set-Content -LiteralPath ([System.IO.Path]::Combine($Trab, $Marcador)) -Value ('ii_mm RC - criado em ' + (Get-Date -Format o)) -Encoding Ascii
    Write-Host "Pasta de trabalho criada: $Trab"
}

function Assert-Preparado {
    if (-not (Test-Path -LiteralPath ([System.IO.Path]::Combine($Trab, $Marcador)))) { throw 'Rode antes: -Etapa Preparar' }
}

function Etapa-Testes {
    Assert-Preparado
    $run = [System.IO.Path]::Combine($PacoteDir, 'run_tests.py')
    $antigo = $env:PROJETO_MVP_DIR
    try {
        Remove-Item Env:\PROJETO_MVP_DIR -ErrorAction SilentlyContinue
        $c1 = Invoke-Py -Argumentos @($run) -Log ([System.IO.Path]::Combine($Trab, 'testes_sem_projeto.log'))
        $c2 = 0
        if ($ProjetoMvp -ne '') {
            $env:PROJETO_MVP_DIR = $ProjetoMvp
            $c2 = Invoke-Py -Argumentos @($run) -Log ([System.IO.Path]::Combine($Trab, 'testes_com_projeto.log'))
        } else {
            Write-Host 'Sem -ProjetoMvp: testes opt-in de compatibilidade ficaram pulados.'
        }
    } finally {
        if ($null -ne $antigo) { $env:PROJETO_MVP_DIR = $antigo } else { Remove-Item Env:\PROJETO_MVP_DIR -ErrorAction SilentlyContinue }
    }
    if ($c1 -ne 0 -or $c2 -ne 0) { throw "Testes falharam (sem projeto: $c1, com projeto: $c2). Veja os .log em $Trab" }
}

function Etapa-Compatibilidade {
    Assert-Preparado
    if ($ProjetoMvp -eq '') { throw 'Informe -ProjetoMvp' }
    $tool = [System.IO.Path]::Combine($PacoteDir, 'tools', 'compat_report.py')
    $out = [System.IO.Path]::Combine($Trab, 'relatorio_compatibilidade.json')
    $code = Invoke-Py -Argumentos @($tool, '--projeto', $ProjetoMvp, '--out', $out)
    if ($code -eq 1) { Write-Warning "Diferencas em relacao a baseline c6845a4: revise $out antes do modo sombra." }
    elseif ($code -ne 0) { throw "Relatorio de compatibilidade falhou (codigo $code)." }
}

function Etapa-Sombra {
    Assert-Preparado
    $ex = [System.IO.Path]::Combine($PacoteDir, 'handoff', 'exemplo_uso.py')
    $out = [System.IO.Path]::Combine($Trab, 'sombra')
    if (Test-Path -LiteralPath $out) { throw "Ja existe $out (nao sobrescrevo). Use outra -TrabalhoDir ou -Etapa Limpar." }
    if ($CatalogoDb -ne '') {
        $code = Invoke-Py -Argumentos @($ex, '--legacy-db', $CatalogoDb, '--out', $out, '--limit', "$Limite")
    } else {
        Write-Host 'Sem -CatalogoDb: rodando com fixtures sinteticas (--demo).'
        $code = Invoke-Py -Argumentos @($ex, '--demo', '--out', $out)
    }
    if ($code -ne 0) { throw "Modo sombra falhou (codigo $code)." }
}

function Etapa-Limpar {
    if (-not (Test-Path -LiteralPath $Trab)) { Write-Host "Nada a limpar: $Trab nao existe."; return }
    if (-not (Test-Path -LiteralPath ([System.IO.Path]::Combine($Trab, $Marcador)))) {
        throw "Recusado: $Trab nao tem o marcador $Marcador (nao foi criada por este script)."
    }
    Remove-Item -LiteralPath $Trab -Recurse -Force
    Write-Host "Removida somente a pasta de trabalho: $Trab"
}

switch ($Etapa) {
    'Conferir'        { Etapa-Conferir }
    'Preparar'        { Etapa-Preparar }
    'Testes'          { Etapa-Testes }
    'Compatibilidade' { Etapa-Compatibilidade }
    'Sombra'          { Etapa-Sombra }
    'Limpar'          { Etapa-Limpar }
    'Tudo'            { Etapa-Conferir; Etapa-Preparar; Etapa-Testes; if ($ProjetoMvp -ne '') { Etapa-Compatibilidade }; Etapa-Sombra }
}
Write-Host "Etapa '$Etapa' concluida."

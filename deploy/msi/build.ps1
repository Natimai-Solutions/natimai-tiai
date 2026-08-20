#Requires -Version 5.1
<#
.SYNOPSIS
    Construit le MSI de l'agent Tia'i en local (le pendant du job `msi` de
    .github/workflows/release.yml).

.DESCRIPTION
    Compile le binaire Go si aucun n'est fourni, installe l'outil `wix`
    (.NET tool) et son extension Util s'ils manquent, puis produit
    dist/tiai-agent-<version>-windows-<arch>.msi.

    Prérequis : Go (si -AgentExe absent) et le SDK .NET (pour `dotnet tool`).

.PARAMETER Version
    Version complète (ex. 0.3.0 ou 0.0.0-dev.abc123). Injectée dans le binaire
    si celui-ci est compilé ici ; la partie numérique seule sert de version MSI.

.PARAMETER Arch
    amd64 (défaut) ou arm64.

.PARAMETER AgentExe
    Binaire tiai-agent.exe déjà compilé. S'il est omis, `go build` est lancé
    dans agent/ pour l'architecture demandée.

.EXAMPLE
    .\build.ps1 -Version 0.3.0
    .\build.ps1 -Version 0.3.0 -Arch arm64 -AgentExe ..\..\dist\tiai-agent-0.3.0-windows-arm64.exe
#>
[CmdletBinding()]
param(
    [string] $Version = '0.0.0-dev.local',
    [ValidateSet('amd64', 'arm64')][string] $Arch = 'amd64',
    [string] $AgentExe = '',
    [string] $OutDir = ''
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
if ([string]::IsNullOrWhiteSpace($OutDir)) { $OutDir = Join-Path $repoRoot 'dist' }
if (-not (Test-Path $OutDir)) { New-Item -ItemType Directory -Path $OutDir -Force | Out-Null }

# Windows Installer n'accepte qu'une version numérique x.y.z : on tronque un
# éventuel suffixe de pré-version (0.0.0-dev.abc123 -> 0.0.0). La version
# complète, elle, vit dans le binaire (ldflags) et dans le nom du fichier.
$msiVersion = ($Version -split '-')[0]
if ($msiVersion -notmatch '^\d+\.\d+\.\d+$') {
    throw "Version MSI invalide '$msiVersion' (attendu x.y.z numerique, tire de '$Version')."
}

# --- 1. Binaire ---------------------------------------------------------------
if ([string]::IsNullOrWhiteSpace($AgentExe)) {
    $AgentExe = Join-Path $OutDir "tiai-agent-$Version-windows-$Arch.exe"
    Write-Host "Compilation de l'agent ($Arch) -> $AgentExe"
    Push-Location (Join-Path $repoRoot 'agent')
    try {
        $env:GOOS = 'windows'; $env:GOARCH = $Arch; $env:CGO_ENABLED = '0'
        go build -trimpath -ldflags "-s -w -X tiai/agent/internal/agent.Version=$Version" -o $AgentExe .
        if ($LASTEXITCODE -ne 0) { throw "go build a echoue (code $LASTEXITCODE)." }
    }
    finally {
        Pop-Location
        Remove-Item Env:GOOS, Env:GOARCH, Env:CGO_ENABLED -ErrorAction SilentlyContinue
    }
}
if (-not (Test-Path -LiteralPath $AgentExe)) { throw "Binaire introuvable : $AgentExe" }

# --- 2. Outil WiX ---------------------------------------------------------------
if ($null -eq (Get-Command wix -ErrorAction SilentlyContinue)) {
    Write-Host 'Installation de WiX (dotnet tool global)...'
    dotnet tool install --global wix
    if ($LASTEXITCODE -ne 0) { throw 'Installation de wix impossible.' }
    $env:Path = "$env:Path;$env:USERPROFILE\.dotnet\tools"
}
if (-not ((wix extension list --global) -match 'WixToolset\.Util\.wixext')) {
    wix extension add --global WixToolset.Util.wixext
    if ($LASTEXITCODE -ne 0) { throw "Ajout de l'extension WixToolset.Util.wixext impossible." }
}

# --- 3. MSI ---------------------------------------------------------------------
$wixArch = if ($Arch -eq 'amd64') { 'x64' } else { 'arm64' }
$msiPath = Join-Path $OutDir "tiai-agent-$Version-windows-$Arch.msi"

wix build (Join-Path $PSScriptRoot 'Package.wxs') `
    -ext WixToolset.Util.wixext `
    -arch $wixArch `
    -d "ProductVersion=$msiVersion" `
    -d "AgentExe=$AgentExe" `
    -o $msiPath
if ($LASTEXITCODE -ne 0) { throw "wix build a echoue (code $LASTEXITCODE)." }

Write-Host "MSI genere : $msiPath (version MSI $msiVersion, binaire $Version)"

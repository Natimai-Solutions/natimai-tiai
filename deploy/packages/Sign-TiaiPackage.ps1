#Requires -Version 5.1
<#
.SYNOPSIS
    Signe le manifeste d'un paquet de deploiement Tiai (methode B).

.DESCRIPTION
    La console fabrique le manifeste d'un paquet de fichiers : le nom et
    l'empreinte SHA-256 de chaque fichier, la ligne de commande d'installation
    et de desinstallation. Ce script le signe sur VOTRE poste, avec un
    certificat de signature de code dont la cle privee ne quitte jamais ce
    poste (magasin de certificats, carte a puce...). Le serveur Tiai ne voit
    que la signature : meme compromis, il ne peut pas en fabriquer.

    Les postes executent un paquet signe seulement si l'empreinte SHA-256 du
    certificat figure dans la valeur DeploySigners (HKLM\SOFTWARE\Tiai), posee
    par GPO. Le script affiche cette empreinte.

    Avant de signer, le script affiche ce que le manifeste fait executer :
    relisez-le. Signer, c'est autoriser les postes a l'executer en SYSTEM.

.PARAMETER Manifest
    Le fichier .tiai-manifest.json telecharge depuis la page du paquet
    (bouton "Telecharger le manifeste").

.PARAMETER CertificateThumbprint
    Empreinte (celle affichee par certmgr, SHA-1) du certificat a utiliser,
    s'il y en a plusieurs dans le magasin. Cherche dans CurrentUser\My puis
    LocalMachine\My, parmi les certificats de signature de code dont la cle
    privee est disponible.

.PARAMETER Output
    Fichier de signature produit. Par defaut : <manifeste>.sig.json, a deposer
    sur la page du paquet ("Deposer la signature").

.PARAMETER Force
    Signe sans demander de confirmation (automatisation).

.PARAMETER ShowThumbprint
    N'ecrit rien : affiche seulement l'empreinte SHA-256 du certificat, a
    recopier dans la GPO (DeploySigners).

.EXAMPLE
    .\Sign-TiaiPackage.ps1 -Manifest .\Client-PRONOTE-2026.2.8.tiai-manifest.json

.EXAMPLE
    .\Sign-TiaiPackage.ps1 -ShowThumbprint
#>
[CmdletBinding(DefaultParameterSetName = 'Sign')]
param(
    [Parameter(Mandatory = $true, ParameterSetName = 'Sign', Position = 0)]
    [string] $Manifest,

    [string] $CertificateThumbprint,

    [Parameter(ParameterSetName = 'Sign')]
    [string] $Output,

    [Parameter(ParameterSetName = 'Sign')]
    [switch] $Force,

    [Parameter(Mandatory = $true, ParameterSetName = 'Show')]
    [switch] $ShowThumbprint
)

$ErrorActionPreference = 'Stop'

function Get-SigningCertificate {
    param([string] $Thumbprint)
    $all = @()
    foreach ($store in 'Cert:\CurrentUser\My', 'Cert:\LocalMachine\My') {
        $all += @(Get-ChildItem -Path $store -CodeSigningCert -ErrorAction SilentlyContinue |
            Where-Object { $_.HasPrivateKey -and $_.NotAfter -gt (Get-Date) })
    }
    if ($Thumbprint) {
        $wanted = ($Thumbprint -replace '[^0-9A-Fa-f]', '').ToUpperInvariant()
        $all = @($all | Where-Object { $_.Thumbprint -eq $wanted })
    }
    if ($all.Count -eq 0) {
        throw "Aucun certificat de signature de code utilisable (cle privee presente, non expire)$(if ($Thumbprint) { " avec l'empreinte $Thumbprint" })."
    }
    if ($all.Count -gt 1) {
        $list = ($all | ForEach-Object { "  $($_.Thumbprint)  $($_.Subject)  (expire le $($_.NotAfter.ToString('yyyy-MM-dd')))" }) -join "`n"
        throw "Plusieurs certificats possibles : precisez -CertificateThumbprint.`n$list"
    }
    return $all[0]
}

function Get-Sha256Thumbprint {
    param($Certificate)
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        return ([BitConverter]::ToString($sha.ComputeHash($Certificate.RawData))).Replace('-', '')
    }
    finally {
        $sha.Dispose()
    }
}

$cert = Get-SigningCertificate -Thumbprint $CertificateThumbprint
$sha256 = Get-Sha256Thumbprint -Certificate $cert

if ($PSCmdlet.ParameterSetName -eq 'Show') {
    Write-Host "Certificat : $($cert.Subject)"
    Write-Host "Expire le  : $($cert.NotAfter.ToString('yyyy-MM-dd'))"
    Write-Host ''
    Write-Host 'Empreinte SHA-256 a mettre dans DeploySigners (GPO) :'
    Write-Host $sha256
    return
}

$path = (Resolve-Path -LiteralPath $Manifest).Path
# The signature covers these exact bytes: read and sign them as they are,
# never a re-serialised copy.
$bytes = [System.IO.File]::ReadAllBytes($path)
$doc = [System.Text.Encoding]::UTF8.GetString($bytes) | ConvertFrom-Json
if ($doc.format -ne 'tiai-package-1') {
    throw "Ce fichier n'est pas un manifeste de paquet Tiai (format '$($doc.format)')."
}

# What is shown below is what is signed: a control character (ESC, CR, a
# C1 code) in a name or an argument could move the cursor and erase a line,
# and show a command other than the one the postes will run (audit S25).
# Refused outright, before anything is displayed.
#
# With them what Unicode offers for the same trick (audit T38): characters
# that reorder what is displayed, or that show nothing at all. The server
# refuses the same set (_CONTROL, backend/app/api/routes/packages.py), and a
# test of the backend keeps the two equal - but the manifest signed here is
# a file, which may not have come from the server:
#   U+00AD          soft hyphen
#   U+061C          Arabic letter mark
#   U+200B-U+200F   zero-width space, joiners, left-to-right/right-to-left marks
#   U+2028-U+202E   line and paragraph separators, bidirectional embeddings
#   U+2060-U+206F   word joiner, invisible operators, bidirectional isolates
#   U+FEFF          byte order mark / zero-width no-break space
#   U+E0000-U+E007F tag characters: a surrogate pair in a .NET string, U+DB40
#                   then U+DC00-U+DC7F
# Letters written right to left are not refused. Written as \uXXXX escapes of
# the .NET regular expression: this file stays pure ASCII.
$ForbiddenCharacters = '[\x00-\x1F\x7F-\x9F\u00AD\u061C\u200B-\u200F\u2028-\u202E\u2060-\u206F\uFEFF]|\uDB40[\uDC00-\uDC7F]'
function Assert-NoControl {
    param([string]$Label, $Value)
    foreach ($v in @($Value)) {
        if ($null -ne $v -and "$v" -match $ForbiddenCharacters) {
            throw "Caractere de controle ou invisible dans $Label : manifeste refuse, rien n'a ete signe."
        }
    }
}
Assert-NoControl 'le nom' $doc.name
Assert-NoControl 'la version' $doc.version
foreach ($f in $doc.files) { Assert-NoControl 'un nom de fichier' $f.name }
foreach ($s in @($doc.install, $doc.uninstall)) {
    if ($s) {
        Assert-NoControl 'le fichier a lancer' $s.run
        Assert-NoControl 'les arguments' $s.args
    }
}

# An installation that has msiexec remove a product takes off what it was sent
# to install: every poste refuses it (agent deploy.MsiExecRemoves), and so
# does the server (manifest.msiexec_removal). The same rule on the three
# sides, the pattern kept equal to the server's by a backend test:
#   - each argument is split on whitespace: msiexec parses its command line
#     itself, and may read "/qn /x {code}" passed as one argument as two;
#   - each piece is rid of one pair of surrounding double quotes;
#   - it removes when it starts with /x or /uninstall (either prefix, whatever
#     is glued to it: "/x{code}") or with REMOVE= ("/i {code} REMOVE=ALL" is
#     the other documented way to uninstall), in ASCII letters of either case.
# -cmatch and both cases spelled out: -match folds case by the rules of the
# current culture (under tr-TR, "I" is not the capital of "i"), msiexec does
# not.
$MsiExecRemoval = '^[/-]([xX]|[uU][nN][iI][nN][sS][tT][aA][lL][lL])|^[rR][eE][mM][oO][vV][eE]='
if ($doc.install -and $doc.install.run -ceq 'msiexec') {
    foreach ($a in @($doc.install.args)) {
        if ($null -eq $a) { continue }
        # \x1C-\x1F: whitespace for the server and the agent, not for \s.
        foreach ($piece in ("$a" -split '[\s\x1C-\x1F]+')) {
            $p = $piece
            # Compared as characters: String.StartsWith would compare by the
            # culture's rules.
            if ($p.Length -ge 2 -and $p[0] -eq [char]34 -and $p[$p.Length - 1] -eq [char]34) {
                $p = $p.Substring(1, $p.Length - 2)
            }
            if ($p -cmatch $MsiExecRemoval) {
                throw "L'installation lance une desinstallation (msiexec /x, /uninstall ou REMOVE=, argument ""$a"") : manifeste refuse, rien n'a ete signe. Placez cette commande dans la desinstallation du paquet."
            }
        }
    }
}

function Format-Step {
    param($Step)
    if (-not $Step) { return '(aucune)' }
    $parts = @($Step.args | ForEach-Object { if ($_ -match '\s|^$') { '"' + $_ + '"' } else { $_ } })
    return "$($Step.run) $($parts -join ' ')".Trim()
}

Write-Host ''
Write-Host "Paquet          : $($doc.name) $($doc.version)"
Write-Host "Identifiant     : $($doc.package_id)"
Write-Host 'Fichiers        :'
foreach ($f in $doc.files) {
    Write-Host ("  {0}  ({1:N0} octets)  SHA-256 {2}" -f $f.name, $f.size, $f.sha256)
}
Write-Host "Installation    : $(Format-Step $doc.install)"
Write-Host "Desinstallation : $(Format-Step $doc.uninstall)"
Write-Host "Codes de succes : $($doc.success_codes -join ', ')"
Write-Host "Certificat      : $($cert.Subject)"
Write-Host ''

if (-not $Force) {
    $answer = Read-Host 'Signer ce paquet ? Les postes qui approuvent ce certificat executeront ces commandes en SYSTEM. (o/N)'
    if ($answer -notmatch '^(o|oui|y|yes)$') {
        Write-Host 'Abandon : rien n''a ete signe.'
        exit 1
    }
}

$hash = [System.Security.Cryptography.HashAlgorithmName]::SHA256
$rsa = [System.Security.Cryptography.X509Certificates.RSACertificateExtensions]::GetRSAPrivateKey($cert)
if ($rsa) {
    $signature = $rsa.SignData($bytes, $hash, [System.Security.Cryptography.RSASignaturePadding]::Pkcs1)
    $algorithm = 'rsa-pkcs1-sha256'
}
else {
    $ecdsa = [System.Security.Cryptography.X509Certificates.ECDsaCertificateExtensions]::GetECDsaPrivateKey($cert)
    if (-not $ecdsa) {
        throw 'Cle du certificat ni RSA ni ECDSA : non prise en charge.'
    }
    # .NET returns r||s (IEEE P1363); the server and the agent accept it.
    $signature = $ecdsa.SignData($bytes, $hash)
    $algorithm = 'ecdsa-sha256'
}

if (-not $Output) {
    # Client-PRONOTE-2026.2.8.tiai-manifest.json -> Client-PRONOTE-2026.2.8.sig.json
    $Output = ($path -replace '(\.tiai-manifest)?\.json$', '') + '.sig.json'
}

$document = [ordered]@{
    format      = 'tiai-signature-1'
    algorithm   = $algorithm
    signature   = [Convert]::ToBase64String($signature)
    certificate = [Convert]::ToBase64String($cert.RawData)
} | ConvertTo-Json
[System.IO.File]::WriteAllText($Output, $document, (New-Object System.Text.UTF8Encoding $false))

Write-Host "Signature ecrite : $Output"
Write-Host 'A deposer sur la page du paquet, bouton "Deposer la signature".'
Write-Host ''
Write-Host 'Empreinte SHA-256 du certificat (valeur DeploySigners de la GPO) :'
Write-Host $sha256

<#
.SYNOPSIS
    Signe des fichiers Windows (Authenticode) dans la chaîne de release.

.DESCRIPTION
    Appelé par .github/workflows/release.yml sur le runner Windows, deux fois :
    sur les .exe avant que le MSI ne les embarque (le service installé est alors
    signé lui aussi), puis sur les .msi eux-mêmes.

    Le certificat arrive par les secrets du dépôt :
      SIGNING_CERT_PFX_BASE64  certificat de signature de code + clé privée,
                               export PFX encodé en base64 ;
      SIGNING_CERT_PASSWORD    mot de passe du PFX (vide s'il n'en a pas).
    et l'horodateur, facultatif, par une variable du dépôt :
      SIGNING_TIMESTAMP_URL    serveur RFC 3161 (défaut : DigiCert).

    L'horodatage n'est pas un raffinement : sans lui, une signature cesse d'être
    valide le jour où le certificat expire, et chaque binaire déjà déployé avec
    lui. Avec lui, elle reste valide pour toujours — elle prouve que le fichier
    a été signé pendant la validité du certificat.

    Sans certificat configuré, le script ne fait rien (code 0) et le dit : les
    binaires partent non signés, comme avant, et `-ExpectedHash` du script GPO
    reste le contrôle d'intégrité. Pour en faire une erreur, la variable du
    dépôt REQUIRE_SIGNING=true fait échouer une release taguée non signée.

.PARAMETER Path
    Fichiers à signer.

.EXAMPLE
    ./.github/scripts/Sign-Authenticode.ps1 -Path dist/tiai-agent-windows-amd64.exe
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string[]] $Path
)

$ErrorActionPreference = 'Stop'

if (-not $env:SIGNING_CERT_PFX_BASE64) {
    if ($env:REQUIRE_SIGNING -eq 'true' -and $env:GITHUB_REF_TYPE -eq 'tag') {
        Write-Output '::error title=Signature obligatoire::REQUIRE_SIGNING=true mais le secret SIGNING_CERT_PFX_BASE64 est absent.'
        exit 1
    }
    Write-Output '::warning title=Binaires non signés::Secret SIGNING_CERT_PFX_BASE64 absent : fichiers publiés sans signature Authenticode.'
    exit 0
}

# signtool est livré avec le SDK Windows de l'image du runner ; on prend la
# version la plus récente installée plutôt qu'un chemin figé qui casserait à la
# prochaine mise à jour de l'image.
$signtool = Get-ChildItem "${env:ProgramFiles(x86)}\Windows Kits\10\bin\*\x64\signtool.exe" -ErrorAction SilentlyContinue |
    Where-Object { $_.Directory.Parent.Name -match '^\d+(\.\d+)+$' } |
    Sort-Object { [version]$_.Directory.Parent.Name } -Descending |
    Select-Object -First 1
if (-not $signtool) {
    throw 'signtool.exe introuvable : SDK Windows absent de cette image de runner.'
}
Write-Output "signtool : $($signtool.FullName)"

$timestampUrl = if ($env:SIGNING_TIMESTAMP_URL) { $env:SIGNING_TIMESTAMP_URL } else { 'http://timestamp.digicert.com' }
$pfx = Join-Path $env:RUNNER_TEMP 'tiai-signing.pfx'

try {
    [IO.File]::WriteAllBytes($pfx, [Convert]::FromBase64String($env:SIGNING_CERT_PFX_BASE64))
    # Charger le PFX ici, avant signtool, donne une erreur lisible sur un
    # mot de passe faux ou un export sans clé privée — et l'empreinte attendue
    # pour la vérification finale.
    $cert = New-Object System.Security.Cryptography.X509Certificates.X509Certificate2(
        $pfx, $env:SIGNING_CERT_PASSWORD)
    if (-not $cert.HasPrivateKey) {
        throw 'Le PFX ne contient pas de clé privée : réexporter le certificat avec sa clé.'
    }
    Write-Output "Certificat : $($cert.Subject) (empreinte $($cert.Thumbprint), expire le $($cert.NotAfter.ToString('yyyy-MM-dd')))"

    $passwordArgs = if ($env:SIGNING_CERT_PASSWORD) { @('/p', $env:SIGNING_CERT_PASSWORD) } else { @() }

    foreach ($file in $Path) {
        if (-not (Test-Path $file)) { throw "Fichier à signer introuvable : $file" }

        # Les horodateurs publics ont des ratés passagers : trois essais
        # espacés avant de déclarer la release en échec.
        $signed = $false
        for ($attempt = 1; $attempt -le 3 -and -not $signed; $attempt++) {
            & $signtool.FullName sign /f $pfx @passwordArgs /fd SHA256 `
                /tr $timestampUrl /td SHA256 `
                /d "Tia'i - agent de gestion de parc" `
                /du 'https://github.com/Natimai-Solutions/natimai-tiai' `
                $file
            if ($LASTEXITCODE -eq 0) {
                $signed = $true
            } elseif ($attempt -lt 3) {
                Write-Output "Échec de signature de $file (essai $attempt/3), nouvel essai dans 15 s…"
                Start-Sleep -Seconds 15
            }
        }
        if (-not $signed) { throw "Signature impossible : $file" }

        # Pas de `signtool verify /pa` : avec un certificat de l'AC interne, la
        # racine n'est pas approuvée sur le runner et la vérification de chaîne
        # échouerait à tort. On vérifie ce qui dépend de nous : le fichier porte
        # bien une signature de CE certificat, et un horodatage.
        $sig = Get-AuthenticodeSignature -FilePath $file
        if (-not $sig.SignerCertificate -or $sig.SignerCertificate.Thumbprint -ne $cert.Thumbprint) {
            throw "Signature absente ou d'un autre certificat sur $file (statut : $($sig.Status))."
        }
        if (-not $sig.TimeStamperCertificate) {
            throw "Signature sans horodatage sur $file."
        }
        Write-Output "Signé : $file (statut local : $($sig.Status))"
    }
}
finally {
    Remove-Item $pfx -Force -ErrorAction SilentlyContinue
}

#Requires -Version 5.1
<#
.SYNOPSIS
    Installe ou met a jour l'agent Tiai (service Windows). Script de demarrage GPO.

.DESCRIPTION
    Concu pour Computer Configuration -> Policies -> Windows Settings ->
    Scripts (Startup), donc execute par LocalSystem a chaque demarrage.

    Idempotent : compare le binaire du partage a celui installe (hash), ne
    recopie que s'il differe, reapplique les valeurs HKLM\SOFTWARE\Tiai (une
    modification de GPO est donc prise au boot suivant), puis s'assure que le
    service tourne. Un poste deja a jour ressort en quelques dizaines de ms.

    Aucun config.yaml n'est genere : l'agent tolere son absence et se configure
    depuis le registre et ses valeurs par defaut. Le seul reglage obligatoire
    est ApiBaseURL.

    Le token par poste (DPAPI, token.dat) et l'enrolement sont geres par l'agent
    lui-meme au premier demarrage : rien a faire ici.

.PARAMETER SourceExe
    Chemin UNC du binaire de reference, p. ex.
    \\natimai.local\NETLOGON\Tiai\tiai-agent.exe
    Le partage doit etre lisible par "Domain Computers" (le script tourne sous
    le compte machine, pas sous le compte utilisateur).

.PARAMETER ApiBaseUrl
    URL du serveur Tiai, ecrite dans HKLM\SOFTWARE\Tiai\ApiBaseURL.

.PARAMETER EnrollmentSecret
    Secret d'enrolement partage. S'il est laisse vide, le script cherche un
    fichier "enrollment-secret.txt" a cote de SourceExe -- a privilegier, car
    les parametres de script GPO sont stockes dans scripts.ini (SYSVOL), lisible
    par tout utilisateur authentifie.

.PARAMETER ExpectedHash
    SHA-256 attendu du binaire (celui publie dans SHA256SUMS.txt de la release).
    Renseigne, le script REFUSE d'installer un binaire du partage qui ne le
    porte pas : sans lui, un acces en ecriture sur le partage suffit a faire
    executer n'importe quoi en SYSTEM sur tout le parc au prochain demarrage.
    L'epingle vit dans les parametres de la GPO, que seul un admin du domaine
    modifie -- falsifier le binaire ne suffit donc plus. A mettre a jour a
    chaque nouvelle release, en meme temps que le binaire depose.

.PARAMETER Location
    Emplacement du poste, en texte libre ("Lycee de Taravao"), ecrit dans
    HKLM\SOFTWARE\Tiai\Location. Une GPO liee a l'OU d'un site le pose sur
    tous ses postes. Laisse vide, la valeur registre n'est pas touchee.
    Pour retirer un emplacement pose auparavant, passer -ClearLocation.

.PARAMETER ClearLocation
    Ecrit une Location vide, ce qui retire l'emplacement (y compris celui d'un
    config.yaml : dans le registre, c'est la presence de la valeur qui compte).

.PARAMETER ReportSessionUsername
    Remontee du NOM de l'utilisateur connecte ('true' / 'false'). La presence
    d'une session est remontee dans tous les cas ; seul le nom est concerne.
    Laisse vide, la valeur registre n'est pas touchee et l'agent applique son
    defaut (activee). Donnee personnelle : voir la section "Session utilisateur"
    du README agent.

.EXAMPLE
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File \\natimai.local\NETLOGON\Tiai\Install-TiaiAgent.ps1 -SourceExe \\natimai.local\NETLOGON\Tiai\tiai-agent.exe -ApiBaseUrl https://tiai.natimai.local

.EXAMPLE
    # GPO liee a l'OU d'un site : chaque poste remonte son emplacement.
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File \\natimai.local\NETLOGON\Tiai\Install-TiaiAgent.ps1 -SourceExe \\natimai.local\NETLOGON\Tiai\tiai-agent.exe -ApiBaseUrl https://tiai.natimai.local -Location "Lycee de Taravao"

.EXAMPLE
    # Parc ou le nom de l'utilisateur ne doit pas remonter au serveur.
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File \\natimai.local\NETLOGON\Tiai\Install-TiaiAgent.ps1 -SourceExe \\natimai.local\NETLOGON\Tiai\tiai-agent.exe -ApiBaseUrl https://tiai.natimai.local -ReportSessionUsername false
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string] $SourceExe,
    [Parameter(Mandatory = $true)][string] $ApiBaseUrl,
    [string] $ExpectedHash = '',
    [string] $EnrollmentSecret = '',
    [ValidateSet('INFO', 'DEBUG')][string] $LogLevel = 'INFO',
    [int]    $HeartbeatIntervalSeconds = 0,
    [int]    $TelemetryIntervalSeconds = 0,
    # Sentinelle chaine vide, et non un booleen : 0 est une valeur signifiante
    # ("ne pas remonter le nom"), donc l'idiome -gt 0 des intervalles ne
    # s'applique pas -- il faut pouvoir distinguer "false" de "non precise".
    [ValidateSet('', 'true', 'false')][string] $ReportSessionUsername = '',
    [string] $Location = '',
    [switch] $ClearLocation,
    [string] $InstallDir = "$env:ProgramFiles\Tiai",
    [int]    $ShareTimeoutSeconds = 120
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$ServiceName = 'TiaiAgent'
$DataDir     = Join-Path $env:ProgramData 'Tiai'
$TargetExe   = Join-Path $InstallDir 'tiai-agent.exe'
$RegPath     = 'HKLM:\SOFTWARE\Tiai'
$LogPath     = Join-Path $DataDir 'deploy.log'

function Write-Log {
    param([string] $Message, [string] $Level = 'INFO')
    $line = '{0} [{1}] {2}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $Level, $Message
    Write-Host $line
    try { Add-Content -Path $LogPath -Value $line -Encoding utf8 } catch { }
}

function Invoke-Agent {
    # Appelle le binaire et remonte un echec en exception (le natif ne leve pas).
    param([string[]] $AgentArgs)
    $output = & $TargetExe @AgentArgs 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw ("tiai-agent {0} a echoue (code {1}) : {2}" -f ($AgentArgs -join ' '), $LASTEXITCODE, ($output -join ' '))
    }
    return $output
}

try {
    if (-not (Test-Path $DataDir)) { New-Item -ItemType Directory -Path $DataDir -Force | Out-Null }

    # --- 1. Attendre le partage -------------------------------------------------
    # Un script de demarrage peut partir avant que le reseau soit pret. La GPO
    # "Always wait for the network at computer startup and logon" reste la vraie
    # correction ; cette boucle couvre le reste (portables, Wi-Fi lent).
    $deadline = (Get-Date).AddSeconds($ShareTimeoutSeconds)
    while (-not (Test-Path -LiteralPath $SourceExe)) {
        if ((Get-Date) -ge $deadline) {
            throw "Source introuvable apres $ShareTimeoutSeconds s : $SourceExe"
        }
        Start-Sleep -Seconds 5
    }

    # --- 2. Faut-il (re)copier le binaire ? -------------------------------------
    $sourceHash = (Get-FileHash -LiteralPath $SourceExe -Algorithm SHA256).Hash

    # Epingle : le binaire du partage doit porter le hash annonce par la GPO.
    # Le partage est le maillon faible (quiconque y ecrit deploie du SYSTEM sur
    # tout le parc) ; l'epingle deplace la confiance vers les parametres de la
    # GPO, que seul un admin du domaine modifie. L'echec laisse le poste sur son
    # binaire actuel : un agent d'hier vaut mieux qu'un binaire inconnu.
    if (-not [string]::IsNullOrWhiteSpace($ExpectedHash)) {
        if ($sourceHash -ne $ExpectedHash.Trim().ToUpperInvariant()) {
            throw ("Le binaire du partage ne porte pas le hash attendu " +
                "(attendu $($ExpectedHash.Trim()), trouve $sourceHash) -- installation refusee.")
        }
    }

    $needsCopy  = $true
    if (Test-Path -LiteralPath $TargetExe) {
        $needsCopy = ((Get-FileHash -LiteralPath $TargetExe -Algorithm SHA256).Hash -ne $sourceHash)
    }

    $service = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue

    # Chemin d'installation deplace (changement d'InstallDir) : desinstaller pour
    # ne pas laisser le SCM pointer sur l'ancien exe.
    if ($null -ne $service) {
        $svcPath = (Get-CimInstance -ClassName Win32_Service -Filter "Name='$ServiceName'").PathName
        if ($svcPath -notlike "*$TargetExe*") {
            Write-Log "Service enregistre sur un autre chemin ($svcPath) -> reinstallation." 'WARN'
            if ($service.Status -ne 'Stopped') { Stop-Service -Name $ServiceName -Force }
            if ($svcPath -match '^\s*"([^"]+)"') { $oldExe = $Matches[1] }
            else { $oldExe = ($svcPath -split '\s+')[0] }
            if (Test-Path -LiteralPath $oldExe) { & $oldExe uninstall | Out-Null }
            if ($null -ne (Get-Service -Name $ServiceName -ErrorAction SilentlyContinue)) {
                & sc.exe delete $ServiceName | Out-Null
            }
            # La suppression peut rester "pending" tant qu'un handle est ouvert.
            $wait = (Get-Date).AddSeconds(30)
            while ($null -ne (Get-Service -Name $ServiceName -ErrorAction SilentlyContinue) -and (Get-Date) -lt $wait) {
                Start-Sleep -Seconds 2
            }
            $service = $null
        }
    }

    if ($needsCopy) {
        if ($null -ne $service -and $service.Status -ne 'Stopped') {
            Write-Log 'Nouveau binaire : arret du service avant remplacement.'
            Stop-Service -Name $ServiceName -Force
        }
        if (-not (Test-Path $InstallDir)) { New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null }

        # Le SCM annonce "Stopped" des que le service le declare, pas quand le
        # processus a rendu la main : le verrou sur l'image peut survivre
        # quelques dizaines de ms, et Windows refuse alors l'ecrasement.
        for ($try = 1; $try -le 5; $try++) {
            try {
                Copy-Item -LiteralPath $SourceExe -Destination $TargetExe -Force
                break
            }
            catch {
                if ($try -ge 5) { throw }
                Write-Log "Copie refusee (tentative $try/5) : $($_.Exception.Message)" 'WARN'
                Start-Sleep -Milliseconds 500
            }
        }
        Write-Log "Binaire deploye ($($sourceHash.Substring(0,12))...) dans $TargetExe."
    }

    # --- 3. Reglages registre (priment sur le YAML) -----------------------------
    if (-not (Test-Path $RegPath)) { New-Item -Path $RegPath -Force | Out-Null }
    Set-ItemProperty -Path $RegPath -Name 'ApiBaseURL' -Value $ApiBaseUrl -Type String
    Set-ItemProperty -Path $RegPath -Name 'LogLevel'   -Value $LogLevel   -Type String

    if ([string]::IsNullOrWhiteSpace($EnrollmentSecret)) {
        $secretFile = Join-Path (Split-Path -Parent $SourceExe) 'enrollment-secret.txt'
        if (Test-Path -LiteralPath $secretFile) {
            $EnrollmentSecret = (Get-Content -LiteralPath $secretFile -Raw).Trim()
        }
    }
    if (-not [string]::IsNullOrWhiteSpace($EnrollmentSecret)) {
        Set-ItemProperty -Path $RegPath -Name 'EnrollmentSecret' -Value $EnrollmentSecret -Type String
    }
    if ($HeartbeatIntervalSeconds -gt 0) {
        Set-ItemProperty -Path $RegPath -Name 'HeartbeatIntervalSeconds' -Value $HeartbeatIntervalSeconds -Type DWord
    }
    if ($TelemetryIntervalSeconds -gt 0) {
        Set-ItemProperty -Path $RegPath -Name 'TelemetryIntervalSeconds' -Value $TelemetryIntervalSeconds -Type DWord
    }
    if (-not [string]::IsNullOrWhiteSpace($ReportSessionUsername)) {
        $reportName = if ($ReportSessionUsername -eq 'true') { 1 } else { 0 }
        Set-ItemProperty -Path $RegPath -Name 'ReportSessionUsername' -Value $reportName -Type DWord
    }
    # L'emplacement : presence de la valeur = elle compte, vide = retire. D'ou
    # le switch explicite pour l'effacer, plutot que d'ecrire une chaine vide
    # chaque fois que le parametre n'est pas fourni.
    if (-not [string]::IsNullOrWhiteSpace($Location)) {
        Set-ItemProperty -Path $RegPath -Name 'Location' -Value $Location.Trim() -Type String
    }
    elseif ($ClearLocation) {
        Set-ItemProperty -Path $RegPath -Name 'Location' -Value '' -Type String
    }

    # Pas de config.yaml a generer : l'agent tolere son absence et se configure
    # entierement depuis les valeurs ci-dessus + ses defauts.

    # --- 3bis. Verrouiller les acces --------------------------------------------
    # HKLM\SOFTWARE est lisible par tout utilisateur authentifie par defaut : le
    # secret d'enrolement y serait lisible depuis n'importe quelle session. Meme
    # probleme pour ProgramData\Tiai (token.dat, journaux). DACL reduite a
    # SYSTEM + Administrateurs, en SDDL avec les SIDs universels (SY/BA) --
    # jamais de noms de groupes, localises differemment d'un Windows a l'autre.
    # Applique seulement si necessaire : le test porte sur les principaux admis
    # (pas sur la chaine SDDL, que Windows reordonne a la relecture), donc rien
    # n'est journalise au demarrage d'un poste deja durci.
    function Test-TiaiAclTight {
        param($Acl)
        if (-not $Acl.AreAccessRulesProtected) { return $false }
        $allowed = @('S-1-5-18', 'S-1-5-32-544')  # SYSTEM, BUILTIN\Administrators
        foreach ($ace in $Acl.GetAccessRules($true, $true, [System.Security.Principal.SecurityIdentifier])) {
            if ($allowed -notcontains $ace.IdentityReference.Value) { return $false }
        }
        return $true
    }
    try {
        if (-not (Test-TiaiAclTight (Get-Acl -Path $RegPath))) {
            $newAcl = New-Object System.Security.AccessControl.RegistrySecurity
            $newAcl.SetSecurityDescriptorSddlForm('D:P(A;CI;KA;;;SY)(A;CI;KA;;;BA)')
            Set-Acl -Path $RegPath -AclObject $newAcl
            Write-Log 'ACL de HKLM\SOFTWARE\Tiai restreinte a SYSTEM + Administrateurs.'
        }
        if (-not (Test-TiaiAclTight (Get-Acl -Path $DataDir))) {
            $newAcl = New-Object System.Security.AccessControl.DirectorySecurity
            $newAcl.SetSecurityDescriptorSddlForm('D:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)')
            Set-Acl -Path $DataDir -AclObject $newAcl
            Write-Log "ACL de $DataDir restreinte a SYSTEM + Administrateurs."
        }
    }
    catch {
        # Un durcissement qui echoue ne doit pas priver le parc de son agent ;
        # la ligne ERROR le rend visible dans deploy.log.
        Write-Log "Durcissement des ACL impossible : $($_.Exception.Message)" 'ERROR'
    }

    # --- 4. Service --------------------------------------------------------------
    if ($null -eq (Get-Service -Name $ServiceName -ErrorAction SilentlyContinue)) {
        Invoke-Agent @('install') | Out-Null
        Write-Log "Service $ServiceName installe."
    }
    else {
        # Reapplique demarrage automatique et relance sur echec a un service
        # deja installe : les postes poses par une version anterieure portent
        # encore "relance, relance, RIEN", et le SCM repete la derniere action.
        # Trois pannes dans la meme journee y laissaient donc le service arrete
        # jusqu'a ce qu'un humain le relance a la main, type de demarrage
        # toujours affiche en Automatique. En WARN et non fatal : un binaire
        # anterieur ne connait pas encore la sous-commande.
        try { Invoke-Agent @('repair') | Out-Null }
        catch { Write-Log "Reglages de service non reappliques : $($_.Exception.Message)" 'WARN' }
    }
    Set-Service -Name $ServiceName -StartupType Automatic

    $service = Get-Service -Name $ServiceName
    if ($service.Status -ne 'Running') {
        Start-Service -Name $ServiceName
        Write-Log "Service $ServiceName demarre."
    } elseif (-not $needsCopy) {
        Write-Log 'Deja a jour et en cours d''execution, rien a faire.'
    }

    exit 0
}
catch {
    Write-Log $_.Exception.Message 'ERROR'
    exit 1
}
finally {
    # Filet de securite, et il couvre le scenario qui a coute le plus cher : le
    # script arrete le service pour remplacer son binaire, puis une etape
    # suivante echoue (registre, ACL, droits), le catch journalise et sort --
    # et le poste passe la journee sans agent, service arrete, sans rien a
    # l'ecran pour le signaler. Quoi qu'il se soit passe au-dessus, on repart.
    try {
        $svc = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
        if ($null -ne $svc -and $svc.Status -ne 'Running') {
            Start-Service -Name $ServiceName
            Write-Log "Service $ServiceName relance (filet de securite)."
        }
    }
    catch {
        Write-Log "Impossible de relancer $ServiceName : $($_.Exception.Message)" 'ERROR'
    }
}

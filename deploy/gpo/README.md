# Déploiement de l'agent par GPO

L'agent est publié en `.exe` nu (pas de MSI), donc *Software Installation* n'est
pas utilisable : le vecteur est un **script de démarrage ordinateur**, exécuté
par `LocalSystem` avant ouverture de session — ce qu'il faut pour enregistrer le
service et pour DPAPI en scope machine.

[`Install-TiaiAgent.ps1`](Install-TiaiAgent.ps1) est idempotent : il tourne à
chaque démarrage, compare le binaire du partage à celui installé (SHA-256) et ne
fait quelque chose que si ça diffère. Un poste déjà à jour ressort immédiatement.

## 1. Préparer le partage

Déposer le binaire de la *release* et le script, par exemple dans
`\\natimai.local\NETLOGON\Tiai\` :

```
tiai-agent.exe            # renommé depuis tiai-agent-<version>-windows-amd64.exe
Install-TiaiAgent.ps1
enrollment-secret.txt     # optionnel, voir §3
```

Deux points qui font échouer la majorité des déploiements :

- **Le script tourne sous le compte machine**, pas sous l'utilisateur. Le partage
  doit être lisible par `Domain Computers` (permissions de partage **et** NTFS).
  `NETLOGON` l'est déjà.
- Un `.exe` téléchargé depuis GitHub porte un marqueur de zone. Faire
  `Unblock-File .\tiai-agent.exe` avant de le déposer.

Vérifier le hash publié dans `SHA256SUMS.txt` de la release avant de copier.

## 2. Créer la GPO

Liée à l'OU des postes, dans **Computer Configuration → Policies → Windows
Settings → Scripts (Startup/Shutdown) → Startup**, onglet **Scripts** (pas
« PowerShell Scripts » : passer par `powershell.exe` évite de dépendre de
l'*ExecutionPolicy* locale) :

| Champ | Valeur |
|---|---|
| Script Name | `powershell.exe` |
| Script Parameters | `-NoProfile -ExecutionPolicy Bypass -File \\natimai.local\NETLOGON\Tiai\Install-TiaiAgent.ps1 -SourceExe \\natimai.local\NETLOGON\Tiai\tiai-agent.exe -ApiBaseUrl https://tiai.natimai.local` |

Activer aussi **Computer Configuration → Policies → Administrative Templates →
System → Logon → Always wait for the network at computer startup and logon**.
Sans ça, le premier démarrage peut partir avant que le partage soit joignable
(le script attend malgré tout jusqu'à `-ShareTimeoutSeconds`, 120 s par défaut).

## 3. Le secret d'enrôlement

Les paramètres de script GPO sont stockés dans `scripts.ini`, dans SYSVOL, **lisible
par tout utilisateur authentifié** — même problème qu'avec les préférences de
registre (MS14-025). Ne pas y mettre le secret.

À la place, poser `enrollment-secret.txt` à côté du binaire, dans un dossier dont
les ACL n'autorisent que `Domain Computers` et les administrateurs : le script le
lit si `-EnrollmentSecret` est vide. Le secret n'est de toute façon utilisé qu'une
fois par poste ; l'agent bascule ensuite sur son token personnel (chiffré DPAPI
dans `token.dat`).

## 4. Ce que fait le script sur le poste

1. copie `tiai-agent.exe` dans `C:\Program Files\Tiai\` (service arrêté d'abord
   si le binaire change → c'est le mécanisme de mise à jour : on remplace le
   fichier sur le partage, les postes se mettent à jour au démarrage suivant) ;
2. écrit `HKLM\SOFTWARE\Tiai` (`ApiBaseURL`, `EnrollmentSecret`, `LogLevel`,
   intervalles) — **à chaque exécution**, donc un changement de GPO est repris ;
3. `install` + `Automatic` + `start`.

Aucun `config.yaml` n'est déposé : l'agent tolère son absence et se configure
depuis le registre et ses valeurs par défaut. `ApiBaseURL` est le seul réglage
obligatoire — sans lui, l'agent refuse de démarrer avec un message le disant.

Journal : `C:\ProgramData\Tiai\deploy.log` (le script) et `agent.log` (l'agent).

## 5. Déployer sans attendre un redémarrage

Un script de démarrage ne rejoue pas sur `gpupdate`. Pour le parc déjà allumé,
ajouter dans la même GPO une **Immediate Task** (Computer Configuration →
Preferences → Control Panel Settings → Scheduled Tasks → New → *Immediate Task
(At least Windows 7)*), exécutée en `NT AUTHORITY\SYSTEM`, avec la même ligne
`powershell.exe`. Elle part au prochain rafraîchissement de stratégie.

## 6. Retirer l'agent

Sortir un poste du périmètre de la GPO ne désinstalle rien. Prévoir un script de
fermeture (*Shutdown*) ou une tâche immédiate :

```powershell
& 'C:\Program Files\Tiai\tiai-agent.exe' uninstall   # arrête le service puis le supprime
Remove-Item 'C:\Program Files\Tiai' -Recurse -Force
Remove-Item 'C:\ProgramData\Tiai' -Recurse -Force    # token, identité de repli, file, logs
Remove-Item 'HKLM:\SOFTWARE\Tiai' -Recurse -Force
```

`uninstall` ne supprime **que** l'enregistrement du service : le binaire,
`C:\ProgramData\Tiai` et les valeurs de registre restent en place, d'où les
lignes suivantes. C'est voulu — pour une simple mise à jour, on veut justement
conserver le token et la file locale.

Attention, purger `C:\ProgramData\Tiai` ne donne pas forcément une nouvelle
identité au poste : l'ancre est le SMBIOS UUID, `agent_id` n'étant qu'un repli.
Sur du matériel réel le poste revient donc avec le même `machine_uuid` — sans
conséquence, l'enrôlement étant idempotent côté serveur.

## Notes

- **Postes ARM64** : le script ne choisit pas l'architecture. Utiliser une
  seconde GPO avec un filtre WMI
  (`SELECT * FROM Win32_Processor WHERE Architecture = 12`) pointant sur le
  binaire `windows-arm64`.
- **Binaire non signé** : sans impact ici (le service est lancé par le SCM, pas
  par un double-clic), mais SmartScreen avertit lors des essais manuels.

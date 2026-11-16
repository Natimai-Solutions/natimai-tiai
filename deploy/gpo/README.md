# Déploiement de l'agent par GPO

Le vecteur documenté ici est un **script de démarrage ordinateur**, exécuté par
`LocalSystem` avant ouverture de session — ce qu'il faut pour enregistrer le
service et pour DPAPI en scope machine — qui gère aussi la mise à jour du
binaire et la réapplication des réglages à chaque boot. Les releases publient
également un installateur `.msi` pour qui préfère *Software Installation* ou
une pose manuelle : voir [deploy/msi/](../msi/README.md).

[`Install-TiaiAgent.ps1`](Install-TiaiAgent.ps1) est idempotent : il tourne à
chaque démarrage, compare le binaire du partage à celui installé (SHA-256) et ne
fait quelque chose que si ça diffère. Un poste déjà à jour ressort immédiatement.

## 1. Préparer le partage

Déposer le binaire de la *release* et le script, par exemple dans
`\\natimai.local\NETLOGON\Tiai\` :

```
tiai-agent.exe            # renommé depuis tiai-agent-windows-amd64.exe de la release
Install-TiaiAgent.ps1
enrollment-secret.txt     # optionnel, voir §3
```

Deux points qui font échouer la majorité des déploiements :

- **Le script tourne sous le compte machine**, pas sous l'utilisateur. Le partage
  doit être lisible par `Domain Computers` (permissions de partage **et** NTFS).
  `NETLOGON` l'est déjà.
- Un `.exe` téléchargé depuis GitHub porte un marqueur de zone. Faire
  `Unblock-File .\tiai-agent.exe` avant de le déposer.

**Le script n'est pas un fichier de la release**, qui ne publie que les
`.exe`, les `.msi` et `SHA256SUMS.txt` : il se prend dans ce dossier du dépôt,
au tag de la release, et se copie à la main sur le partage. À chaque nouvelle
version, **copier d'abord le nouveau script, et seulement ensuite modifier les
paramètres de la GPO** (§2). Un paramètre que le script du partage ne connaît
pas encore — `-AllowInsecureHttp` face à un script antérieur, par exemple —
est rejeté par PowerShell avant la première ligne du script : rien n'est écrit
dans `deploy.log`, et aucun poste n'est installé ni mis à jour, à chaque
démarrage, tant que l'ancien script reste sur le partage.

Relever le hash publié dans `SHA256SUMS.txt` de la release : il se vérifie au
moment de copier, **et** il se passe au script en `-ExpectedHash` (§2) pour que
chaque poste le re-vérifie à chaque démarrage. Sans cette épingle, quiconque
obtient l'écriture sur le partage fait exécuter son binaire en SYSTEM sur tout
le parc au prochain boot ; avec elle, il faudrait aussi modifier la GPO.

## 2. Créer la GPO

Liée à l'OU des postes, dans **Computer Configuration → Policies → Windows
Settings → Scripts (Startup/Shutdown) → Startup**, onglet **Scripts** (pas
« PowerShell Scripts » : passer par `powershell.exe` évite de dépendre de
l'*ExecutionPolicy* locale) :

| Champ | Valeur |
|---|---|
| Script Name | `powershell.exe` |
| Script Parameters | `-NoProfile -ExecutionPolicy Bypass -File \\natimai.local\NETLOGON\Tiai\Install-TiaiAgent.ps1 -SourceExe \\natimai.local\NETLOGON\Tiai\tiai-agent.exe -ApiBaseUrl https://tiai.natimai.local -ExpectedHash <SHA-256 de SHA256SUMS.txt>` |

`-ExpectedHash` est optionnel mais recommandé : le script refuse alors un
binaire du partage qui ne porte pas ce hash (le poste garde sa version en
place). À chaque nouvelle release, mettre à jour **les deux ensemble** : le
binaire déposé sur le partage et le hash dans les paramètres de la GPO.

Pour un parc où le **nom** de l'utilisateur connecté ne doit pas remonter au
serveur, ajouter `-ReportSessionUsername false` aux paramètres ci-dessus : la
console verra alors qu'une session est ouverte, sans savoir de qui. Le réglage
est écrit au démarrage suivant du poste, et l'agent l'applique au démarrage de
son service qui suit (§4), sans réinstallation.

Pour un parc **multi-sites**, lier une GPO par site (ou un filtre WMI) et ajouter
`-Location "Lycée de Taravao"` : chaque poste remonte alors son emplacement, la
console filtre le parc par site, et le réveil Wake-on-LAN relayé sait quel poste
voisin solliciter (DEPLOYMENT.md, « Réveil des postes », point 4). Sans le
paramètre, la valeur registre n'est pas touchée ; `-ClearLocation` la retire.

`-ApiBaseUrl` en `http://` (port HTTP direct du backend, réseau de test
seulement) exige `-AllowInsecureHttp true` : sans lui, l'agent refuse l'URL, le
secret d'enrôlement puis le token passant en clair. Son service ne s'arrête
pas pour autant : il reste « En cours d'exécution », ne contacte pas le
serveur, et écrit pourquoi dans `agent.log` toutes les 1 à 15 minutes
(`agent: cannot run yet (api_base_url … is http://…)`) ; le script le signale
aussi dans `deploy.log` (ligne `WARN`). Poser la valeur ensuite le répare à
l'essai suivant, sans redémarrage.

- **Format.** `true` ou `false` ici ; `1` ou `0` dans la propriété
  `ALLOWINSECUREHTTP` du [MSI](../msi/README.md). Toute autre valeur fait
  rejeter la ligne par PowerShell, avec le même effet qu'un paramètre inconnu
  (§1).
- **Ordre.** Le paramètre n'existe que dans le script de cette version : copier
  le script sur le partage **avant** de l'ajouter à la GPO (§1). Sur un parc
  installé en `http://`, l'ajouter **au plus tard en même temps** que le
  binaire qui l'exige (agent publié après la v1.1.0) : le script écrit le
  registre avant de relancer le service.
- **Retrait.** Sans le paramètre, la valeur registre `AllowInsecureHTTP` n'est
  pas touchée ; `-AllowInsecureHttp false` retire une autorisation posée
  auparavant. Un agent déjà en marche ne relit toutefois le registre qu'au
  démarrage de son service (§4) : il continue en `http://` jusqu'à son
  prochain redémarrage.

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

1. vérifie le binaire du partage contre `-ExpectedHash` s'il est fourni, puis
   le copie dans `C:\Program Files\Tiai\` (service arrêté d'abord si le binaire
   change → c'est le mécanisme de mise à jour : on remplace le fichier sur le
   partage, les postes se mettent à jour au démarrage suivant) ;
2. écrit `HKLM\SOFTWARE\Tiai` (`ApiBaseURL`, `EnrollmentSecret`, `LogLevel`,
   intervalles, `ReportSessionUsername`, `AllowInsecureHTTP`, `Location`) — **à
   chaque exécution** : un changement de GPO arrive donc dans le registre au
   démarrage suivant du poste (voir ci-dessous quand l'agent le lit) ;
3. restreint les ACL de `HKLM\SOFTWARE\Tiai` et de `C:\ProgramData\Tiai` à
   SYSTEM + Administrateurs : par défaut, tout utilisateur du poste pourrait y
   lire le secret d'enrôlement et le token chiffré ;
4. `install` + `Automatic` + `start`.

**Quand l'agent lit le registre.** Au démarrage de son service, et seulement
là. Or, au démarrage d'un poste, le service est en général déjà lancé quand le
script s'exécute : la valeur qu'il vient d'écrire n'est appliquée qu'au
démarrage **suivant** du service — redémarrage du poste, ou
`Restart-Service TiaiAgent`. Deux exceptions : le script qui remplace le
binaire relance le service après avoir écrit le registre, la mise à jour de
l'agent emporte donc les nouveaux réglages ; et un agent qui attend une
configuration utilisable (pas d'`ApiBaseURL`, URL en `http://` sans
autorisation) la relit à chaque essai, toutes les 1 à 15 minutes. Les valeurs
`Deploy*` du déploiement logiciel, posées par ailleurs, sont relues à chaque
commande.

Aucun `config.yaml` n'est déposé : l'agent tolère son absence et se configure
depuis le registre et ses valeurs par défaut. `ApiBaseURL` est le seul réglage
obligatoire — sans lui, le service tourne sans contacter le serveur, l'écrit
dans `agent.log` et réessaie jusqu'à ce que la valeur arrive.

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
- **Signature** : les releases sont signées (Authenticode) quand le dépôt porte
  le certificat de signature de code, cf. [DEPLOYMENT.md](../../DEPLOYMENT.md)
  § « Signature de l'agent ». Sans lui, le binaire part non signé : sans impact
  ici (le service est lancé par le SCM, pas par un double-clic), mais
  SmartScreen avertit lors des essais manuels. Signé ou non, `-ExpectedHash`
  reste le contrôle qui compte ici : l'intégrité du binaire est vérifiée sur
  chaque poste contre une valeur que seule la GPO porte — la signature dit qui
  l'a produit, l'empreinte que c'est exactement celui que la GPO a choisi.

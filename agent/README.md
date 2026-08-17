# Tiai — Agent (Windows)

Service Windows léger, déployé par GPO, qui interroge le serveur (polling),
remonte l'état Defender, la session utilisateur ouverte et l'adresse IP du
poste, et exécute les commandes (scan / mise à jour signatures).

## Layout

```
main.go                    commandes CLI (run / init-config / install / uninstall / start / stop / status / version)
internal/
  config/    config ProgramData (config.yaml) + surcharge registre (HKLM\SOFTWARE\Tiai) ; token chiffré DPAPI (token.dat)
  dpapi/     wrapper DPAPI (CryptProtectData, scope machine) ; passthrough hors Windows
  identity/  résolution identité (SMBIOS UUID via WMI / repli UUID agent) + empreinte (MachineGuid registre, TPM EK best-effort)
  sysinfo/   hostname / domaine AD / version OS
  api/       client HTTP (enroll / heartbeat / result)
  collector/ Defender : état + menaces via WMI (ROOT\Microsoft\Windows\Defender) ; scans + MAJ via PowerShell
             session utilisateur ouverte via l'API WTS (wtsapi32)
             adresse IP principale via GetAdaptersAddresses (iphlpapi)
  queue/     file locale durable (résultats de commandes non remis) + back-off
  logging/   log fichier (agent.log, rotation simple) + niveau INFO/DEBUG
  service/   service Windows (golang.org/x/sys/windows/svc)
  agent/     boucle de polling + exécution des commandes
  models/    types de la couche transport
```

## Accès Defender (plan §2.6)

- **Lecture** (état, menaces) via **WMI** — pas de spawn de process par cycle :
  `MSFT_MpComputerStatus`, `MSFT_MpThreatDetection` + `MSFT_MpThreat` (jointure par `ThreatID`).
- **Actions** (scans, MAJ signatures) via **PowerShell** : `Start-MpScan`, `Update-MpSignature`.

## Session utilisateur

L'agent remonte à chaque heartbeat s'il y a **une session ouverte sur le poste**,
via l'**API WTS** (`WTSEnumerateSessions` + `WTSQuerySessionInformationW`). Il
tourne en `LocalSystem` dans la session 0 : `os/user` et `%USERNAME%` y sont
inutilisables, alors que WTS énumère toutes les sessions locales quel que soit
l'appelant — c'est précisément le cas d'usage de cette API, et elle coûte un
appel système, sans process lancé ni requête WMI.

Sont ignorées : la session 0 (services), et toute session sans nom
d'utilisateur — écran de connexion, écouteur `RDP-Tcp`, stations `UMFD`/`DWM`.
Quand plusieurs sessions coexistent (RDS, changement rapide d'utilisateur), une
seule est élue : active avant déconnectée, console avant distante, et à égalité
le plus petit identifiant de session pour que la réponse soit stable d'un poll
au suivant.

**Confidentialité.** Le nom de l'utilisateur est une donnée personnelle. La clé
`report_session_username` (YAML) ou la valeur registre `ReportSessionUsername`
(`REG_DWORD`, `0` = coupé) contrôle sa **remontée** ; la présence, elle, est
toujours remontée. Le nom est lu localement — c'est ce qui permet de distinguer
une session utilisateur de l'écran de connexion — puis abandonné avant d'être
sérialisé : il ne quitte jamais le poste quand l'option est coupée. Il n'est
**jamais** journalisé, à aucun niveau. La console affiche alors « Utilisateur
connecté » sans identité. Défaut : activé.

> **Session verrouillée = session ouverte.** Un poste verrouillé reste `WTSActive`
> et sera donc affiché comme occupé. C'est le sens voulu (« un utilisateur est
> connecté »), pas « un utilisateur est devant l'écran » : l'API WTS ne permet pas
> de distinguer les deux depuis la session 0. Une session RDP abandonnée sans
> déconnexion est en revanche bien signalée comme « déconnectée ».

L'information vaut ce que vaut le dernier heartbeat (60 s par défaut) : la
console l'accompagne du « vu le » du poste.

## Adresse IP

L'agent remonte **une** adresse IP par poste, relue à chaque heartbeat — pas
mise en cache au démarrage comme le hostname : un bail DHCP, une station
d'accueil ou un VPN la change sous un agent qui tourne depuis des semaines.
Lecture via **`GetAdaptersAddresses`** (`iphlpapi`) plutôt que `net.Interfaces()`
de la bibliothèque standard, qui n'expose ni la métrique d'interface ni la
présence d'une passerelle par défaut — les deux critères qui rendent le choix
déterministe au lieu d'heuristique.

Sont **exclues** d'office : les adresses de loopback (`127.0.0.0/8`, `::1`), les
adresses lien-local — `169.254.0.0/16`, l'auto-attribution APIPA d'un poste dont
le bail DHCP a échoué, et `fe80::/10` — et l'adresse non spécifiée. Sont écartés
de même les adaptateurs qui ne sont pas `IfOperStatusUp` (une carte débranchée
garde son adresse statique, une carte désactivée son dernier bail) et les
pseudo-interfaces tunnel (Teredo, ISATAP, 6to4).

Quand plusieurs adresses subsistent — cas moins rare qu'il n'y paraît : portable
sur station d'accueil, poste avec Hyper-V/WSL, VPN monté — une seule est élue,
dans cet ordre :

| Critère | Pourquoi |
|---|---|
| IPv4 avant IPv6 | c'est l'adresse qu'un admin va pinguer ou saisir dans un client RDP ; une IPv6 n'est remontée que pour un poste qui n'a aucune IPv4 |
| passerelle par défaut avant absence de passerelle | écarte les commutateurs virtuels *host-only* (vEthernet Hyper-V, WSL, VirtualBox, VMware) qui portent une adresse mais ne joignent aucun réseau — **sans** filtrer sur le nom des cartes, qu'aucune heuristique ne couvrirait de façon fiable |
| métrique d'interface la plus basse | c'est l'ordre de routage de Windows lui-même : l'Ethernet d'une station d'accueil passe devant le Wi-Fi resté associé |
| index d'interface, puis adresse | départage arbitraire mais **stable** : sur deux cartes réellement équivalentes, l'adresse affichée ne doit pas clignoter d'un poll au suivant |

Si rien ne subsiste, l'agent n'envoie pas le champ (plutôt qu'une chaîne vide) :
le serveur conserve alors la dernière adresse connue, datée par le « vu le » du
poste, au lieu d'effacer une information sur une lecture ratée.

> Une seule adresse est conservée côté serveur : l'objectif est de **joindre** le
> poste, pas d'inventorier ses cartes réseau. Le détail des interfaces relève du
> module Inventaire (phase ultérieure).

## Identité & sécurité

- Ancre = **SMBIOS/System UUID** (`Win32_ComputerSystemProduct.UUID`), repli sur un
  UUID agent persisté si l'ancre est absente/denylistée (plan §2.3).
- Empreinte (MachineGuid, SMBIOS UUID, hash EK TPM) remontée séparément pour la
  détection clone/altération côté serveur.
- Token par poste **chiffré au repos via DPAPI** (scope machine, lisible par le
  service `LocalSystem`), jamais écrit en clair dans le YAML.

## Robustesse (plan §2.9)

- Back-off exponentiel (plafonné) si le serveur est injoignable.
- File locale durable pour les **résultats de commandes** : un scan terminé alors
  que le serveur était down est rejoué au prochain contact. L'état/les menaces
  sont reconstruits à chaque heartbeat (pas mis en file).

## Build & essai

```bash
cd agent
go build -o tiai-agent.exe .
./tiai-agent.exe init-config --api-url https://tiai.natimai.local
./tiai-agent.exe run            # premier plan (Ctrl+C pour arrêter)
```

Déploiement en service :

```bash
./tiai-agent.exe install        # enregistre le service (auto-start + recovery)
./tiai-agent.exe start
./tiai-agent.exe status
```

L'agent s'auto-enrôle au 1er démarrage (en-tête `X-Enrollment-Secret`), stocke
le token reçu (DPAPI), puis n'utilise plus que `Authorization: Bearer <token>`.

## Publier un .exe sur GitHub

[`.github/workflows/release.yml`](../.github/workflows/release.yml) construit les
binaires Windows et les attache à la page *Releases* du dépôt. Rien à compiler à
la main, rien à committer : la version vient du tag.

```bash
git tag -a v0.2.0 -m "Agent v0.2.0"
git push origin v0.2.0
```

Le workflow joue les tests, cross-compile `windows/amd64` et `windows/arm64`,
génère `SHA256SUMS.txt` et crée la release avec les notes issues des commits.
Les postes téléchargent alors directement
`tiai-agent-0.2.0-windows-amd64.exe` — c'est le fichier à déposer sur le partage
GPO.

Pour un binaire de test sans publier, lancer le workflow à la main (onglet
*Actions* → *Release* → *Run workflow*) : les `.exe` sortent en artefact de
build, versionnés `0.0.0-dev.<sha>`.

**Version injectée au build.** `agent.Version` est un `var` écrasé par
`-ldflags -X` ; le code source garde `0.1.0` comme valeur des builds locaux. Pour
reproduire un build de release en local :

```bash
GOOS=windows GOARCH=amd64 CGO_ENABLED=0 go build -trimpath \
  -ldflags "-s -w -X tiai/agent/internal/agent.Version=0.2.0" \
  -o tiai-agent.exe .
```

**Binaire non signé.** Aucun certificat de signature de code n'est utilisé :
au premier lancement manuel, SmartScreen affichera un avertissement
« Éditeur inconnu ». Sans impact en déploiement GPO (le service est installé par
le système, pas par un double-clic de l'utilisateur), mais c'est à prévoir pour
les tests manuels — et à corriger par un certificat de signature si l'agent doit
un jour être distribué hors du parc.

## Logs

Les logs partent sur **stderr et** dans `<dossier config>\agent.log`
(`C:\ProgramData\Tiai\agent.log` par défaut ; rotation en `.old` au-delà de
5 Mio) — indispensable en mode service, où stderr n'aboutit nulle part.
Niveau via `log_level` (YAML) ou la valeur registre `LogLevel` : `INFO` par
défaut (démarrage, identité, enrôlement, commandes exécutées + durée, erreurs) ;
`DEBUG` logge aussi chaque heartbeat silencieux — utile pour vérifier que
l'agent poll bien pendant les tests. Le nom de l'utilisateur connecté n'est
journalisé à aucun niveau ; seule la désactivation de sa remontée est tracée une
fois au démarrage, pour rendre le réglage auditable.

Le code reste compilable hors Windows (stubs `*_other.go`) pour `go vet` / les
tests de logique pure ; les fonctionnalités Defender/service/registre/DPAPI sont
actives uniquement sous Windows.

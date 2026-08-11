# Tiai — Agent (Windows)

Service Windows léger, déployé par GPO, qui interroge le serveur (polling),
remonte l'état Defender et exécute les commandes (scan / mise à jour signatures).

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
l'agent poll bien pendant les tests.

Le code reste compilable hors Windows (stubs `*_other.go`) pour `go vet` / les
tests de logique pure ; les fonctionnalités Defender/service/registre/DPAPI sont
actives uniquement sous Windows.

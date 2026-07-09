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

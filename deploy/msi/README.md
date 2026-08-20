# Installateur MSI de l'agent

Chaque release publie, à côté des `.exe` nus, un installateur
`tiai-agent-<version>-windows-<arch>.msi` (x64 et arm64), construit par le job
`msi` de [release.yml](../../.github/workflows/release.yml) à partir de
[Package.wxs](Package.wxs) (WiX v4+). Il ouvre le déploiement par **GPO
Software Installation** — impossible avec un `.exe` nu — et sert aussi
d'installation manuelle propre (visible dans « Applications installées »,
mise à jour et désinstallation standard).

Le [script de démarrage GPO](../gpo/README.md) reste le vecteur recommandé pour
un parc : il gère aussi la mise à jour du binaire et la (ré)application des
réglages à chaque boot. Le MSI est l'alternative quand une politique interne
impose *Software Installation*, ou pour installer quelques postes à la main.

## Ce que fait le paquet

- copie `tiai-agent.exe` dans `%ProgramFiles%\Tiai` ;
- enregistre le service **TiaiAgent** (démarrage automatique, relance sur échec
  après 15 s, compteur remis à zéro après 24 h — les mêmes réglages que
  `tiai-agent install`) et le démarre ;
- écrit dans `HKLM\SOFTWARE\Tiai` les valeurs passées en propriétés (voir
  ci-dessous) — celles que l'agent lit déjà par-dessus son `config.yaml`
  facultatif.

L'enrôlement (token DPAPI dans `%ProgramData%\Tiai`) reste l'affaire de l'agent
au premier démarrage : rien à faire côté installateur.

## Propriétés

Toutes facultatives — une valeur absente n'écrit rien et l'agent applique son
défaut ou ce que la GPO a déjà posé dans le registre.

| Propriété | Valeur registre écrite | Format |
|---|---|---|
| `APIBASEURL` | `ApiBaseURL` | URL, ex. `https://tiai.natimai.local` |
| `ENROLLMENTSECRET` | `EnrollmentSecret` | chaîne (masquée dans les journaux MSI) |
| `LOGLEVEL` | `LogLevel` | `INFO` ou `DEBUG` |
| `HEARTBEATINTERVALSECONDS` | `HeartbeatIntervalSeconds` | entier > 0 |
| `WUCOLLECTINTERVALSECONDS` | `WUCollectIntervalSeconds` | entier > 0 |
| `WUINSTALLTIMEOUTSECONDS` | `WUInstallTimeoutSeconds` | entier > 0 |
| `REPORTSESSIONUSERNAME` | `ReportSessionUsername` | `1` ou `0` (pas `true`/`false`) |

```powershell
# Installation silencieuse avec configuration
msiexec /i tiai-agent-0.3.0-windows-amd64.msi /qn `
    APIBASEURL=https://tiai.natimai.local `
    ENROLLMENTSECRET=<secret>

# Diagnostic : journal détaillé
msiexec /i tiai-agent-0.3.0-windows-amd64.msi /qn /l*v install.log APIBASEURL=...
```

Sans `APIBASEURL` (ni valeur registre préexistante), l'installation réussit
quand même : le service démarre, constate l'absence d'URL et s'arrête ; il
repartira au prochain démarrage du poste, une fois la valeur posée (par GPO par
exemple).

## Mise à jour et désinstallation

- **Mise à jour** : installer le MSI de la nouvelle version, sans rien
  désinstaller (*major upgrade* — l'ancienne version est retirée
  automatiquement, service arrêté puis relancé). Les valeurs registre et
  `%ProgramData%\Tiai` sont **conservés** : inutile de repasser les propriétés.
- **Désinstallation** : `msiexec /x` (ou « Applications installées »). Le
  service et les fichiers programme sont retirés ; `HKLM\SOFTWARE\Tiai` et
  `%ProgramData%\Tiai` (token d'enrôlement, logs) sont volontairement laissés
  en place — une réinstallation retrouve le poste tel quel. Les supprimer à la
  main pour un retrait définitif.

## Déploiement par GPO Software Installation

Assigner le MSI **par ordinateur** (Computer Configuration → Policies →
Software Settings → Software installation) depuis un partage lisible par
`Domain Computers`. Deux façons de passer la configuration :

1. **Registre par GPO Preferences** (le plus simple) : déployer le MSI nu et
   pousser `ApiBaseURL` (et le reste) via Computer Configuration → Preferences
   → Windows Settings → Registry, clé `HKLM\SOFTWARE\Tiai`. C'est exactement ce
   que fait déjà le script de démarrage.
2. **Transformation MST** : GPO ne transmet pas de propriétés `msiexec` ; pour
   les figer dans le déploiement, créer un `.mst` (Orca, InstEd, `wix msi`)
   qui pose `APIBASEURL` & co., et l'attacher au paquet dans la GPO.

À chaque nouvelle version : remplacer le paquet dans la GPO (*upgrade* de
l'ancien) — ou préférer le script de démarrage, qui met à jour tout seul.

## Construire en local

```powershell
# Compile l'agent (Go requis) puis produit dist/tiai-agent-<version>-windows-amd64.msi
.\deploy\msi\build.ps1 -Version 0.3.0

# À partir d'un binaire déjà compilé, pour arm64
.\deploy\msi\build.ps1 -Version 0.3.0 -Arch arm64 -AgentExe .\dist\tiai-agent-0.3.0-windows-arm64.exe
```

Le script installe l'outil [`wix`](https://wixtoolset.org) (dotnet tool global)
et l'extension `WixToolset.Util.wixext` s'ils manquent — version épinglée,
identique à celle du CI — et accepte l'[EULA OSMF de WiX
v7](https://wixtoolset.org/osmf/) pour l'utilisateur courant (obligatoire
depuis août 2026, sinon toute commande `wix` échoue avec WIX7015).

Note versions : Windows Installer n'accepte qu'une version numérique `x.y.z` —
le suffixe d'un build de dev (`0.0.0-dev.abc123`) est tronqué pour le MSI, mais
la version complète reste dans le binaire (`tiai-agent.exe version`) et dans le
nom du fichier.

# Tiai — Agent (Windows)

Service Windows léger, déployé par GPO, qui interroge le serveur (polling),
remonte l'état Defender, l'antivirus enregistré (tiers compris), la session
utilisateur ouverte et l'adresse IP du poste, et exécute les commandes
demandées depuis la console : scan / mise à jour des signatures Defender, et un
catalogue fermé de commandes de maintenance et de diagnostic Windows.

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
             antivirus enregistré (tiers compris) via WMI (root\SecurityCenter2), lecture seule
             session utilisateur ouverte via l'API WTS (wtsapi32)
             adresse IP principale via GetAdaptersAddresses (iphlpapi)
             maintenance/diagnostic : catalogue fermé d'outils System32 (maintenance*.go)
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
- `AMRunningMode` est remonté avec l'état : c'est lui qui distingue « Defender
  éteint » de « Defender **passif** parce qu'un antivirus tiers a pris le relais »
  (`Normal` / `Passive` / `SxS Passive Mode` / `EDR Block Mode` ; vide avant
  Windows 10 1903, où la propriété n'existe pas).

## Commandes de maintenance à distance

Au-delà de Defender, l'agent exécute un **catalogue fermé** de commandes de
maintenance et de diagnostic Windows (cf. `plan-commandes-distantes.md`).

**Le catalogue *est* le modèle de sécurité.** Le serveur n'envoie qu'un
**identifiant de type** — `{id, type}`, protocole inchangé : **aucun argument ne
traverse le réseau**. L'exécutable et ses arguments fixes sont dans la table
[`maintenanceCatalogue`](internal/collector/maintenance.go), à l'intérieur du
binaire de l'agent. Un serveur compromis ne peut donc déclencher que l'une de ces
onze actions, jamais du code arbitraire. Sont **exclus par principe**, et ne
doivent pas être réintroduits au fil de l'eau : tout exécuteur de scripts libre,
et toute modification du registre, des fichiers, du pare-feu ou des comptes.

| Type | Commande | Famille | Délai max | `running` |
|---|---|---|---|---|
| `gpo_update` | `gpupdate /target:computer /force` | Maintenance | 5 min | — |
| `flush_dns` | `ipconfig /flushdns` | Maintenance | 5 min | — |
| `time_resync` | `w32tm /resync` | Maintenance | 5 min | — |
| `cert_pulse` | `certutil -pulse` | Maintenance | 5 min | — |
| `spooler_reset` | arrêt spouleur → purge de la file → redémarrage (natif Go) | Maintenance | 5 min | — |
| `sfc_scan` | `sfc /scannow` | Intégrité | 30 min | oui |
| `dism_restore_health` | `dism /online /cleanup-image /restorehealth` | Intégrité | 2 h | oui |
| `dism_component_cleanup` | `dism /online /cleanup-image /startcomponentcleanup` | Disque | 1 h | oui |
| `chkdsk_scan` | `chkdsk /scan` | Disque | 1 h | oui |
| `gpo_report` | `gpresult /r /scope:computer` | **Diagnostic** | 5 min | — |
| `net_config` | `ipconfig /all` | **Diagnostic** | 5 min | — |

Notes de périmètre :

- `gpupdate` tourne en `/target:computer` : l'agent est `LocalSystem`, il n'y a
  pas de ruche utilisateur à rafraîchir — le libellé de la console l'assume.
- `chkdsk /scan` est l'analyse **en ligne** : elle signale sans réparer, donc
  sans immobiliser le poste. La réparation (`/spotfix`) est hors catalogue.
- `spooler_reset` passe par le **gestionnaire de services** plutôt que par
  `net stop spooler` : l'API dit l'état réel du service au lieu d'une phrase
  localisée, et permet d'**attendre** l'arrêt effectif avant de supprimer les
  fichiers — sinon la purge court après un service qui n'a pas encore lâché ses
  handles. Seuls les `.spl` et `.shd` sont supprimés ; le service est redémarré
  même si la purge a échoué.
- `netsh winsock reset` est écarté pour l'instant : il exige un redémarrage
  derrière, il ira avec la commande `reboot` de la Phase 2.

**Chemins absolus, jamais le `PATH`.** Chaque exécutable est résolu en
`%SystemRoot%\System32\<exe>`. L'agent tourne en `LocalSystem` : un répertoire
inscriptible placé avant System32 dans le `PATH` transformerait sinon chacune de
ces commandes en exécution de code SYSTEM.

**Encodage : il n'y en a pas un, il y en a quatre.** C'est le piège de ce
chantier, et il est mesuré et non supposé (Windows 11 français, sortie capturée
dans un tube) :

| Outil | Écrit en | Comment c'est traité |
|---|---|---|
| `ipconfig`, `w32tm`, `gpupdate`, `chkdsk` | page de codes **OEM** (CP850) | conversion `MultiByteToWideChar(CP_OEMCP)` — le défaut |
| `certutil` | page de codes **ANSI** (CP1252) | déclaré `encANSI` dans le catalogue |
| `gpresult`, `dism` | **UTF-8** | détecté automatiquement : l'UTF-8 s'auto-identifie |
| `sfc` | **UTF-16LE** entrelacé de nuls | déclaré `encUTF16LE`, *et vérifié* sur les octets |

Ce n'est **pas** la page de codes de la console : sur la même machine,
`GetConsoleOutputCP()` répondait 65001 pendant qu'`ipconfig` émettait du CP850.
Ce qui compte est que la sortie soit redirigée, pas ce à quoi le terminal est
réglé — et en service, il n'y a pas de terminal du tout. Sans ce traitement, un
`ipconfig /all` remonte « Carte r�seau » et un `sfc` remonte du charabia.

**Sortie.** Les retours chariot sont rejoués comme le ferait une console (tout
ce qui précède le dernier `\r` d'une ligne a été écrasé) : les centaines de
lignes de progression de `dism` et `sfc` se réduisent ainsi à leur dernière
image, sans dépendre d'aucune langue ni d'aucun format. Le résultat est tronqué
à **64 Kio** avant l'envoi (le serveur re-plafonne à la réception).

**Statut intermédiaire.** Les quatre commandes longues postent
`{status: "running"}` avant de démarrer : sans lui, la console afficherait
« transmise » pendant vingt minutes de `sfc`. C'est un indice de progression et
non un résultat — l'envoi est *best-effort*, jamais mis en file, et le serveur
refuse un `running` qui arriverait après un verdict.

**Codes de retour.** Traduits seulement quand la signification est documentée
(`dism` 3010 = succès avec redémarrage requis, `0x800f081f` = source de
réparation inaccessible → message qui oriente vers WU/WSUS ; `w32tm` +
`0x80070426` = service W32Time arrêté ; codes `chkdsk` connus). Le reste est
remonté brut plutôt que deviné, mais en hexadécimal quand c'est un HRESULT :
`0x80070005` se reconnaît, `2147942405` ne dit rien.

Le worker de commandes reste **séquentiel** : une commande longue retarde les
suivantes du même poste. Comportement assumé, rendu visible par `running`.

## Antivirus tiers

Les classes Defender ne décrivent que Defender : un poste protégé par ESET ou
Bitdefender y apparaît comme « antivirus éteint », et nulle part comme protégé.
L'agent lit donc aussi le **Security Center** de Windows (WMI
`root\SecurityCenter2`, classe `AntiVirusProduct`), où **tout** antivirus
s'enregistre — c'est la condition pour que Windows cesse d'alerter l'utilisateur,
donc la source de vérité sur « qui garde ce poste ».

En sont tirés le **nom affiché** du produit et deux bits d'état extraits de
`productState` : protection temps réel active, et signatures données pour à jour.
Rien de plus n'est disponible : **ni version de signatures, ni date, ni moyen de
déclencher une mise à jour** — d'où le périmètre en lecture seule (les commandes
`quick_scan` / `full_scan` / `update_signatures` restent spécifiques à Defender).

`productState` n'est documenté nulle part (l'accès supporté est l'API COM
`wscapi`, hors de portée d'une requête WMI). Le décodage est donc **conservateur** :
seules les valeurs réellement observées sont traduites, tout le reste est remonté
comme *inconnu* plutôt que deviné — un « protection désactivée » affirmé à tort
sur un écran de console est pire qu'un tiret. Les éditeurs étant par ailleurs
inégaux sur le bit de fraîcheur, le serveur traite « fraîcheur inconnue » comme
acceptable et ne retient que le « périmé » explicite.

Trois réponses distinctes, et la distinction est signifiante :

| Situation | Remontée | Console |
|---|---|---|
| un produit enregistré | nom + état | le nom, badge coloré selon l'état |
| registre lisible et **vide** | bloc envoyé, nom vide | « Aucun » — un constat, pas une absence de mesure |
| registre illisible | **bloc omis** | « Inconnu » ; le serveur conserve la valeur précédente |

Le troisième cas est l'état **permanent** sur un SKU **Serveur**, qui n'embarque
aucun Security Center : le namespace n'existe pas et la requête ne peut qu'échouer.
L'échec est donc journalisé **une fois**, puis rétrogradé en `DEBUG` — sinon le log
de chaque serveur du parc répéterait la même ligne toutes les minutes à vie.

Quand plusieurs produits sont enregistrés — le cas normal, pas l'exception :
Defender reste inscrit à côté du tiers qui l'a mis en passif — un seul est élu :

| Critère | Pourquoi |
|---|---|
| produit actif avant produit arrêté | la question posée est « qu'est-ce qui protège le poste *maintenant* » ; un état illisible se classe entre les deux, il peut fort bien tourner |
| tiers avant Defender | si les deux tournent, Windows a confié la protection au tiers et Defender est passif — alors que sa propre classe WMI continue de se déclarer active, exactement le piège que ce collecteur contourne |
| nom le plus petit | départage arbitraire mais **stable** : deux antivirus tiers installés (pathologique, mais réel) ne doivent pas alterner d'un poll au suivant |

L'identification de Defender se fait sur son `instanceGuid` bien connu, sinon sur
l'URI `windowsdefender://` qu'il enregistre en guise de chemin d'exécutable, et
seulement en dernier recours sur le nom — jamais sur un simple « defender » :
« Bit**defender** » le contient, et prendre un antivirus tiers pour Defender est
précisément l'erreur à ne pas commettre.

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

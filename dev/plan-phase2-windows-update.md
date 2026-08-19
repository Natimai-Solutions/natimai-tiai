# Phase 2 — Windows Update : plan de travail

> **Statut : implémenté (2026-08-17)** — cf. §7 en fin de document.
>
> Objectif : remonter l'état Windows Update de chaque poste dans la console, et pouvoir **forcer la mise à jour d'un poste à distance**.
> Réutilise l'agent, le canal polling et la file de commandes existants (cf. `plan-projet-tiai.md` §Phase 2) — seuls de nouveaux types de commandes et un nouveau bloc de données s'ajoutent.

---

## 1. Cadrage retenu

| Sujet | Décision |
|---|---|
| Redémarrage | **Jamais d'auto-reboot.** L'agent remonte « redémarrage requis » ; une commande `reboot` séparée est déclenchable depuis la console, avec dialog de confirmation. |
| Périmètre d'installation | **Deux commandes** : `wu_install` (MAJ logicielles uniquement, pilotes exclus) et `wu_install_full` (logicielles + pilotes). Deux types distincts ⇒ pas besoin d'ajouter un payload au protocole de commandes. |
| Données remontées | MAJ **en attente** (titre, KB, sévérité, type logiciel/pilote) + redémarrage requis + dates de dernière recherche/installation. Pas d'historique des KB installés dans cette itération. |
| Technique d'accès | **API COM WUA** (`Microsoft.Update.Session`) pilotée en PowerShell via le wrapper `runPowerShell()` existant, sortie JSON parsée côté Go. PSWindowsUpdate écarté (module non standard). |
| Cadence de collecte | **Cycle lent dédié** (défaut 6 h, configurable), jamais dans le heartbeat 60 s — une recherche WU peut prendre plusieurs minutes. Re-collecte immédiate après un `wu_scan`/`wu_install*`. |

---

## 2. Contrat agent ↔ serveur

### Nouveau bloc optionnel du heartbeat (`windows_update`)

```json
{
  "windows_update": {
    "reboot_required": false,
    "last_search_time": "2026-08-13T04:00:00Z",
    "last_install_time": "2026-08-01T03:12:00Z",
    "pending": [
      {
        "update_id": "e6cf1350-...-{rev}",
        "kb": "KB5063878",
        "title": "Mise à jour cumulative 2025-08 ...",
        "severity": "Critical",
        "type": "software",
        "categories": ["Security Updates"],
        "is_downloaded": true,
        "size_mb": 620.5
      }
    ]
  }
}
```

Même modèle que le bloc `defender` : optionnel, patch conditionnel côté serveur (un heartbeat sans le bloc n'écrase rien).

### Nouveaux types de commandes (4, puis 5 — cf. §8)

| Type | Effet sur le poste | Sortie attendue |
|---|---|---|
| `wu_scan` | Recherche WU immédiate + rafraîchit l'état remonté | Nombre de MAJ en attente |
| `wu_install` | Recherche → AcceptEula → téléchargement → installation des MAJ **logicielles** | Résumé par MAJ (KB, ResultCode/HResult) + `reboot_required` |
| `wu_install_full` | Idem, **pilotes inclus** | Idem |
| `reboot` | `shutdown.exe /r /t 60` avec message utilisateur (le résultat est posté **avant** le reboot) | Confirmation |

### Statut intermédiaire `running`

`CommandStatus.RUNNING` et `started_at` existent déjà côté backend mais ne sont jamais écrits. On les câble : au démarrage d'une commande longue (`wu_install*`), l'agent poste `{status: "running"}` sur `POST /agent/commands/{id}/result` ; le serveur passe la commande en `RUNNING` + `started_at` sans la clore. Le résultat final (`succeeded`/`failed`) suit normalement. La console affiche déjà le statut `running` (mapping existant).

---

## 3. Jalons

### J1 — Backend : modèle de données + réception *(~1–1,5 j)*

**Migration [0005_windows_update.py](backend/app/alembic/versions/)** (`down_revision = "0004_password_reset"`, conventions : nommage manuel `NNNN_slug`, `sa.DateTime(timezone=True)`, `server_default` sur les non-nullables, `downgrade()` implémenté) :
- Colonnes `machines` : `wu_pending_count int null`, `wu_reboot_required bool NOT NULL server_default false`, `wu_last_search timestamptz null`, `wu_last_install timestamptz null`.
- Table `windows_updates` (MAJ **en attente**, une ligne par MAJ par poste) : `id bigserial PK`, `machine_id FK → machines.id ON DELETE CASCADE`, `update_id text`, `kb text null`, `title text`, `severity text null`, `type text` (`software`/`driver`), `categories text null`, `is_downloaded bool`, `size_mb float null`, `first_seen/last_seen timestamptz`, contrainte `UNIQUE (machine_id, update_id)`, index `(machine_id)`.

**Nouveau module `backend/app/features/windows_update/`** (calqué sur `features/threat/`) :
- `models.py` : table `WindowsUpdate` ; `schemas.py` : `WUStateReport` + `PendingUpdateReport` (partagés route agent / crud, comme `ThreatReport`) ; `crud.py` : `replace_pending(session, machine_id, updates)` — **sémantique de remplacement du set** (upsert des présentes + `DELETE` des disparues), contrairement aux menaces qui s'accumulent : une MAJ installée disparaît de la liste.
- Import dans [models.py](backend/app/features/models.py) (peuplement du metadata).

**Extension du heartbeat** ([agent.py](backend/app/api/routes/agent.py)) : champ `windows_update: WUStateReport | None` dans `HeartbeatRequest` ; si présent → met à jour les 4 colonnes machine + `replace_pending`. Respecter le piège existant : réponse construite **avant** le commit (`MissingGreenlet`).

**Extension des commandes** :
- `CommandType` ([command/models.py](backend/app/features/command/models.py)) += `WU_SCAN`, `WU_INSTALL`, `WU_INSTALL_FULL`, `REBOOT` (stockage `str` nu ⇒ aucune migration).
- `POST /agent/commands/{id}/result` ([agent.py](backend/app/api/routes/agent.py)) : accepter `status="running"` → `RUNNING` + `started_at`, sans `finished_at` ni clôture ; un résultat final ultérieur reste accepté.

**Exposition console** :
- `GET /machines` : lignes += `wu_pending_count`, `wu_reboot_required`.
- `GET /machines/{id}` (`MachineDetailOut`) : += les 4 champs WU + liste `pending_updates`.
- `GET /stats/overview` ([stats.py](backend/app/api/routes/stats.py)) : += `machines_wu_pending` (postes avec ≥ 1 MAJ en attente), `machines_reboot_required`.

**Tests pytest** (patrons existants : helpers `_enroll`/`_heartbeat` de [test_api_console.py](backend/tests/test_api_console.py), Postgres de test via `TIAI_TEST_DATABASE_URL`) :
- Heartbeat avec bloc `windows_update` → colonnes machine + set des MAJ (ajout, mise à jour, disparition d'une MAJ installée).
- Heartbeat sans le bloc → rien n'est écrasé.
- Résultat `running` → `RUNNING` + `started_at`, puis résultat final → `SUCCEEDED`.
- Création des 4 nouveaux types (permission `command:execute` inchangée), stats overview.

### J2 — Agent : collecte Windows Update *(~1–1,5 j)*

**Nouveau collecteur `agent/internal/collector/wu.go` / `wu_windows.go` / `wu_other.go`** (modèle : le collecteur Defender — logique pure testable dans le fichier neutre, COM/PowerShell dans `_windows.go`, stub `errUnsupported` dans `_other.go`) :
- `ReadWUState(ctx)` : script PowerShell embarqué → `Microsoft.Update.Session` / `CreateUpdateSearcher().Search("IsInstalled=0 and IsHidden=0")` (toutes les MAJ en attente, pilotes inclus — le `type` de chaque MAJ est remonté et le filtrage se fait à l'installation) ; `reboot_required` via `Microsoft.Update.SystemInfo` ; dates via `(New-Object -ComObject Microsoft.Update.AutoUpdate).Results` (`LastSearchSuccessDate`/`LastInstallationSuccessDate`, best-effort → null si indisponible) ; sortie `ConvertTo-Json -Depth 4` parsée en Go.
- Mappings purs dans `wu.go` (sévérité, type software/driver via les catégories, `KBArticleIDs` → `"KB..."`), testables hors Windows.

**Modèles transport** ([models.go](agent/internal/models/models.go)) : `WUState`, `PendingUpdate`, champ `WindowsUpdate *WUState` dans `HeartbeatRequest` (même pattern que `Defender *DefenderState`).

**Cycle lent** ([agent.go](agent/internal/agent/agent.go)) :
- Nouvelle clé de config `wu_collect_interval_seconds` (défaut **21600** = 6 h) + surcharge registre, comme les intervalles existants. (`TelemetryIntervalSeconds` à 900 s est trop fréquent pour une recherche WU ; il reste inutilisé/déprécié ou est supprimé — à trancher en revue.)
- Goroutine dédiée : première collecte ~2 min après le démarrage (ne pas peser sur le boot), puis toutes les 6 h ; résultat mis en cache sous mutex ; le heartbeat attache le bloc `windows_update` quand le cache a été rafraîchi depuis le dernier envoi réussi.
- Timeout de collecte dédié (~30 min : les recherches WU sont lentes sur les vieux postes).

**Tests Go** : parsing JSON → `WUState` (fixtures de sorties PowerShell réalistes, y compris champs manquants), mappings sévérité/type/KB, logique « attacher le bloc seulement si rafraîchi ».

### J3 — Agent : exécution des 4 commandes *(~1–1,5 j)*

**Dispatch** (`execute`, [agent.go:239](agent/internal/agent/agent.go#L239)) : 4 nouveaux `case`. Signature commune `func(ctx) (string, error)` conservée ; les deux installs partagent une implémentation paramétrée `runWUInstall(ctx, includeDrivers bool)`.

- `wu_scan` → `ReadWUState` forcé + rafraîchit le cache ; output : « N mises à jour en attente ».
- `wu_install` / `wu_install_full` : script PowerShell WUA : search (filtre pilotes selon la variante) → `AcceptEula()` si requis → `CreateUpdateDownloader()` → `CreateUpdateInstaller()` ; sortie JSON : par MAJ `{kb, title, result_code, hresult}` + `reboot_required` global. Mapping ResultCode (2 = Succeeded, 3 = SucceededWithErrors, 4 = Failed, 5 = Aborted) → statut final : `succeeded` si tout ≥ succès partiel, `failed` sinon, output lisible dans les deux cas. **Timeout dédié long** (config `wu_install_timeout_seconds`, défaut 7200). Cas d'échec explicites : service WU désactivé, installeur occupé (TrustedInstaller), 0 MAJ applicable (= succès « rien à faire »).
- Post-install/scan : re-collecte immédiate de l'état → la console voit le nouvel état au heartbeat suivant.
- Sérialisation des opérations WU (mutex partagé avec la collecte de fond : jamais deux sessions WUA simultanées).
- `reboot` (nouveau fichier `agent/internal/collector/system_windows.go`) : `shutdown.exe /r /t 60 /c "Redémarrage demandé par l'administrateur (Tiai)"`. Le résultat `succeeded` est posté avant l'expiration du délai ; en cas d'échec du POST, la file disque existante (`internal/queue`) le rejouera après reboot.
- Statut intermédiaire : avant de lancer `wu_install*`, POST `{status: "running"}` (best-effort, non bloquant).

**Note assumée (v1)** : le worker de commandes reste **séquentiel** — une installation longue retarde les autres commandes du poste. Acceptable et documenté ; le statut `running` rend l'attente visible en console.

**Tests Go** : mapping ResultCode → statut/output, construction du critère de recherche selon la variante, parsing du résumé d'installation.

### J4 — Console *(~1 j)*

**Services** :
- [commands.ts](frontend/src/services/commands.ts) : `CommandType` += `'wu_scan' | 'wu_install' | 'wu_install_full' | 'reboot'`.
- [machines.ts](frontend/src/services/machines.ts) : types `Machine`/`MachineDetail` += champs WU + `pending_updates`.
- [stats.ts](frontend/src/services/stats.ts) : overview += 2 KPI.

**[MachineDetailPage.vue](frontend/src/pages/MachineDetailPage.vue)** :
- Nouvelle carte « Windows Update » (pattern existant `q-card flat bordered` + `q-list dense`) : MAJ en attente, Redémarrage requis, Dernière recherche, Dernière installation.
- `q-table` des MAJ en attente (KB, titre, sévérité, type, téléchargée) — pattern des tables existantes.
- Dropdown « Action » += les 4 entrées. **Confirmation `$q.dialog`** (pattern `confirmRevoke`) pour `wu_install`, `wu_install_full` et `reboot` ; `wu_scan` part sans confirmation comme les scans Defender.

**[MachinesPage.vue](frontend/src/pages/MachinesPage.vue)** :
- Colonnes : badge « MAJ en attente » (`wu_pending_count`), icône « redémarrage requis ».
- Actions de masse += les 4 entrées, avec confirmation indiquant le **nombre de postes ciblés** pour install/reboot.
- Les deux tableaux d'actions (détail + masse) sont aujourd'hui dupliqués : les factoriser dans `commands.ts` (libellé + icône + confirmation requise) au passage.

**[DashboardPage.vue](frontend/src/pages/DashboardPage.vue)** : 2 cartes KPI (« MAJ en attente », « Redémarrage requis »).

**Tests vitest** (pattern services existant : mock `boot/axios`, assertion URL + params + retour) : nouveaux types de commandes, champs WU du détail machine, stats.

### J5 — Validation end-to-end + documentation *(~0,5–1 j)*

Voir §5 Vérification. Puis : mise à jour de `plan-projet-tiai.md` (suivi d'avancement Phase 2) et du README agent (nouvelles clés de config).

---

## 4. Extensibilité (décisions absorbées sans refonte)

| Évolution future | Comment le design l'absorbe |
|---|---|
| Sélection fine par KB | Ajout d'un champ `payload jsonb` optionnel sur `commands` + `Command.Payload` côté agent ; les types existants l'ignorent. Volontairement **pas** introduit maintenant (YAGNI). |
| Auto-reboot optionnel | Deviendrait un type `wu_install_reboot` ou un payload — même mécanique. |
| Historique des KB installés | Nouvelle table alimentée par `QueryHistory()` WUA, même pipeline heartbeat. |
| Fenêtres de maintenance | Côté serveur (création différée des commandes) — aucune modification agent. |

---

## 5. Vérification

1. **Qualité locale** : `ruff` + `mypy --strict` + `pytest` (Postgres de test) côté backend ; `gofmt` + `go vet` + `go test` + build croisé Windows côté agent ; `prettier` + `vue-tsc` + `vitest` côté frontend. CI existante inchangée (elle couvre déjà les trois).
2. **End-to-end simulé** (sans poste Windows) : stack `docker compose` dev + heartbeat forgé avec bloc `windows_update` (curl) → vérifier colonnes machine, table `windows_updates` (remplacement du set), affichage console, cycle commande `wu_install` avec résultat `running` puis `succeeded`.
3. **Poste réel** (DoD de la phase) : agent déployé sur un poste avec MAJ en attente →
   - la carte « Windows Update » se remplit après la première collecte ;
   - `wu_scan` depuis la console → état rafraîchi ;
   - `wu_install` → statut `running` visible, puis `succeeded` avec résumé par KB, `reboot_required` remonté ;
   - `reboot` avec confirmation → le poste redémarre après 60 s, le résultat est bien en base, l'agent re-heartbeat au retour ;
   - un poste **hors ligne** au moment de la commande la récupère à son retour (dans la limite du TTL).

---

## 6. Points d'attention

- **WSUS/GPO** : la recherche WUA utilise la source configurée du poste (WSUS si imposé par GPO) — comportement voulu, ne pas forcer Microsoft Update.
- **TTL des commandes** : défaut 60 min conservé. Pour `reboot`, ne **pas** allonger (un reboot différé de 24 h serait une surprise) ; pour `wu_install*`, un TTL plus long (ex. 4 h) est raisonnable — exposé plus tard si besoin.
- **Encodage/JSON PowerShell** : réutiliser `runPowerShell()` (UTF-8 déjà géré) ; `ConvertTo-Json` avec `-Depth` suffisant ; parser tolérant aux champs absents (`AllowMissingFields` esprit Defender).
- **Postes sans WU fonctionnel** (service désactivé, WMI cassé) : la collecte échoue en log sans bloquer le heartbeat (pattern best-effort existant) ; la commande échoue avec un message actionnable.
---

## 7. État de réalisation *(2026-08-17)*

**J1 à J4 livrés.** Le suivi détaillé vit dans `plan-projet-tiai.md` §Suivi
d'avancement ; ne sont notées ici que les décisions prises **en cours de route**,
là où ce plan laissait le choix ouvert ou s'est révélé inexact.

| Point du plan | Ce qui a été fait |
|---|---|
| Migration `0005_windows_update` | Devenue **`0008_windows_update`** : les migrations `0005` à `0007` (session, adresse IP, antivirus tiers) ont été livrées entre l'écriture de ce plan et sa mise en œuvre. `down_revision = "0007_av_product"`. |
| Statut intermédiaire `running` (J1) | **Déjà câblé** par le chantier « commandes de maintenance », qui l'a implémenté en s'appuyant sur cette spécification. Les deux installations s'y branchent sans une ligne de backend. |
| Factorisation du catalogue d'actions console (J4) | **Déjà faite**, même chantier. Il ne restait qu'à ajouter une section « Windows Update » et quatre entrées. |
| `TelemetryIntervalSeconds` — « à trancher en revue » | **Supprimé.** La clé n'était lue par aucun code depuis l'origine ; le cycle lent qu'elle annonçait existe désormais pour de bon sous le nom `wu_collect_interval_seconds`, avec un défaut de 6 h et non de 15 min. Une valeur résiduelle dans un YAML déployé est ignorée sans erreur. |
| `wu_pending_count` | **Dérivé côté serveur** de la liste reçue, plutôt que remonté comme champ propre : le badge de la liste et le tableau de la fiche détail ne peuvent alors pas se contredire sur le même poste. |
| Sévérité | **Normalisée en minuscules** côté serveur (`Critical` → `critical`), pour qu'un agent ancien et un agent récent atterrissent sur la valeur unique dont la console tire ses couleurs. Les MAJ en attente sont renvoyées **triées critique d'abord** : le vocabulaire MSRC trié alphabétiquement donne critical < important < low < moderate, ce qui est pire qu'inutile. |
| Fusion de postes | Les MAJ en attente du doublon ne sont **pas** rattachées au poste conservé : c'est de l'état courant et non de l'historique, elles entreraient en collision avec son propre set et son compteur ne correspondrait plus à ses lignes. La suppression du doublon les efface par cascade, le cycle suivant rétablit la vérité. |

**Deux bugs attrapés par leurs propres tests, tous deux sur le chemin nominal :**

1. Les apostrophes de `Type='Software'` refermaient le littéral PowerShell — le
   script d'installation **ne se parsait pas du tout**, sur la variante sans
   pilotes, c'est-à-dire celle de `wu_install`. Trouvé par un test qui fait
   parser les deux scripts par le parseur de PowerShell lui-même, ajouté
   précisément parce que la branche d'installation ne peut pas être exercée sans
   patcher une machine.
2. Une extension de pilote de quelques kilo-octets s'affichait « 0 Mio » à côté
   d'une icône de téléchargement. La conversion plancher désormais à 0,1 Mio.

### Vérification effectuée (§5)

1. **Qualité locale** — 178 tests backend verts sur Postgres 16, 98 % de
   couverture (`ruff`, `mypy --strict`) ; migration rejouée `upgrade`/`downgrade`/`upgrade` sur base
   vierge ; Go `gofmt`/`vet`/`test` verts, builds croisés `windows/amd64`,
   `windows/arm64` et `linux` ; 76 vitest, `vue-tsc` et `prettier` verts.
2. **Boucle complète sur poste réel contre la stack `docker compose` dev** —
   agent réel enrôlé, `wu_scan` déclenché depuis l'API console, **19 mises à
   jour** remontées en 13 s (accents intacts jusqu'en base), colonnes machine et
   table `windows_updates` renseignées, dates `LastSearchSuccessDate` /
   `LastInstallationSuccessDate` lues, pilotes correctement typés. Cycle de fond
   à 2 min confirmant l'upsert **en place** (`first_seen` conservé, `last_seen`
   avancé) et la retenue du bloc : **18 heartbeats, 2 écritures**.
3. **Reste à valider sur poste réel** — une installation effective
   (`wu_install` / `wu_install_full`) et un `reboot`. Ce sont les deux seules
   branches qu'on ne peut pas exercer sans patcher ou redémarrer une machine ;
   la syntaxe des scripts, le filtrage par variante et la lecture des
   `ResultCode` sont couverts par des tests, l'exécution réelle non.

---

## 8. Extension — `wu_reset` *(2026-08-19)*

Cinquième type de la famille, ajouté après coup : **réinitialiser les composants
Windows Update** d'un poste qui ne cherche, ne télécharge ou n'installe plus
rien. C'est le cas que les quatre commandes précédentes ne savaient pas traiter
— elles supposent toutes une pile WU fonctionnelle, et `wu_install` sur un poste
dont le magasin est corrompu ne fait que remonter le même HRESULT en boucle.

### Ce que fait la commande

La procédure documentée par Microsoft, sans rien de plus :

1. arrêt de `wuauserv`, `cryptsvc`, `bits`, `msiserver` ;
2. renommage de `%SystemRoot%\SoftwareDistribution` et de
   `%SystemRoot%\System32\catroot2` en `*.old` ;
3. redémarrage des services.

Windows reconstruit les deux dossiers à la recherche suivante. Le coût est réel
et il est annoncé dans la confirmation console : l'**historique des mises à jour**
du poste est perdu (il vit dans `SoftwareDistribution\DataStore`), et les
correctifs déjà téléchargés le seront à nouveau. Rien n'est installé, rien n'est
redémarré : le poste est remis en état de se mettre à jour, pas mis à jour.

### Écarts assumés par rapport à l'article

| Point | Décision |
|---|---|
| `net stop` / `ren` en shell | **Natif Go**, comme `spooler_reset` : le gestionnaire de services dit l'état réel au lieu d'une phrase localisée, permet d'**attendre** `Stopped` avant de renommer (un dossier encore ouvert ne se renomme pas), et n'introduit pas de shell dans un agent qui n'en a pas. |
| `ren` échoue à la 2ᵉ exécution | Un `*.old` laissé par une exécution précédente est **supprimé** avant le renommage. Rejouer la procédure sur un poste récalcitrant est le cas normal, pas l'exception. |
| `net start` des 4 services | Seuls les services que la commande a **effectivement arrêtés** sont relancés. `wuauserv` et `msiserver` démarrent à la demande sur un Windows moderne et sont couramment trouvés à l'arrêt ; surtout, un service désactivé par GPO doit le rester — le relancer serait la commande qui passe outre la stratégie d'un administrateur. |
| `regsvr32` des DLL WU, `netsh winsock reset`, `sc sdset` | **Hors périmètre.** Sans effet depuis Windows 8 pour le premier, exige un redémarrage pour le deuxième, verrouille l'accès au service quand il se trompe pour le troisième. Chacun est plus difficile à défaire que l'ensemble de ce que fait la commande. |

### Trois règles d'ordonnancement

Elles portent toute la sûreté de la commande :

- les renommages n'ont lieu qu'une fois **tous** les services arrêtés ;
- un service qui n'a **pas** pu être arrêté annule les renommages plutôt que de
  les laisser échouer un par un — un poste intact vaut mieux qu'un poste dont le
  magasin a bougé sous un `wuauserv` qui le tient encore ;
- les services sont **redémarrés quoi qu'il arrive** au milieu, exactement comme
  `spooler_reset` redémarre le spouleur par-dessus une purge ratée.

### Ce que ça a coûté

- **Backend** : une valeur d'énumération. `type` est stocké en `str` nu ⇒ aucune
  migration, aucun changement de protocole — la promesse du §4 tenue une fois de
  plus.
- **Agent** : `collector/wureset*.go` (tables, rapport, verdict et le renommage
  lui-même en neutre ; seul le gestionnaire de services est sous `_windows.go`),
  plus un `case` dans le dispatch. La commande prend le **même mutex** que le
  reste de la famille : renommer `SoftwareDistribution` sous une recherche ou une
  installation en cours est précisément la façon d'obtenir un magasin à moitié
  écrit, et le cycle de fond de 6 h finirait par tomber dessus.
- **Console** : une entrée de catalogue, en fin de section Windows Update — c'est
  ce vers quoi on se tourne quand les installations ont échoué, pas ce qu'on
  essaie en premier.
- Le cache WU de l'agent est **délibérément laissé intact** : ce que la
  réinitialisation jette est le magasin, pas la vérité. Les mises à jour qui
  manquaient manquent toujours, et les deux horodatages viennent des résultats
  Automatic Updates dans le registre, que la commande ne touche pas.

# Catalogue de commandes de maintenance à distance : plan de travail

> **✅ Livré le 2026-08-17.** Ce document reste la référence de conception : il explique *pourquoi* chaque choix a été fait. Les écarts constatés à l'implémentation sont notés en §8 — dont un de fond : le plan n'anticipait qu'**un** piège d'encodage, il y en avait **quatre**.
> Les deux briques partagées avec la Phase 2 (statut `running`, factorisation des actions UI) ont été réalisées **ici** : la Phase 2 les réutilise telles quelles, cf. §6.
>
> Objectif : exécuter à distance un **catalogue fermé** de commandes de maintenance et de diagnostic Windows, avec remontée du résultat dans la console.
> Chantier indépendant de la Phase 2 (Windows Update, cf. `plan-phase2-windows-update.md`), mais qui partage deux briques avec elle (statut `running`, factorisation des actions UI) — voir §6 Séquencement.

---

## 1. Modèle de sécurité

- **Catalogue fixe, codé en dur dans le binaire de l'agent.** Le serveur ne transmet que l'identifiant du type (`{id, type}`, protocole inchangé) ; **aucun argument ne traverse le réseau**. Même un serveur compromis ne peut déclencher que le catalogue, jamais de code arbitraire.
- Pas d'exécuteur de scripts libre, pas de modification registre/fichiers/pare-feu/utilisateurs — exclusions de principe, à ne pas réintroduire au fil de l'eau.
- Autorisation : permission existante `command:execute` (admin seul). Audit : table `commands` existante (`created_by`, horodatages).
- Confirmation UI (`$q.dialog`) pour les commandes de maintenance ; les diagnostics en lecture seule partent sans confirmation.
- **Chemins absolus sous `System32`, jamais le `PATH`** *(ajouté à l'implémentation, cf. §8)*. L'agent tourne en `LocalSystem` : un répertoire inscriptible par un utilisateur et placé avant `System32` dans le `PATH` transformerait chacune de ces commandes en exécution de code SYSTEM. Le catalogue ne stocke que des noms de fichiers nus, résolus en `%SystemRoot%\System32\<exe>` au lancement — un test vérifie qu'aucune entrée ne contient de séparateur de chemin.
- **L'agent ne peut plus poster que `running` / `succeeded` / `failed`** *(ajouté, cf. §8)*. Le corollaire naturel du reste : un agent capable de poster `pending` ou `expired` réécrirait la file qu'il est seulement censé vider.

## 2. Catalogue retenu (11 commandes)

La colonne **Encodage** a été renseignée *après* mesure sur poste réel — elle n'était pas prévue au plan (§8).

| `CommandType` | Commande exécutée | Famille | Durée | Confirmation | Encodage |
|---|---|---|---|---|---|
| `gpo_update` | `gpupdate /target:computer /force` | Maintenance AD | Courte | Non | OEM |
| `gpo_report` | `gpresult /r /scope:computer` | **Diagnostic** | Courte | Non | UTF-8 |
| `flush_dns` | `ipconfig /flushdns` | Maintenance réseau | Courte | Non | OEM |
| `net_config` | `ipconfig /all` | **Diagnostic** | Courte | Non | OEM |
| `time_resync` | `w32tm /resync` | Maintenance AD | Courte | Non | OEM |
| `cert_pulse` | `certutil -pulse` | Maintenance AD (AC interne) | Courte | Non | **ANSI** |
| `spooler_reset` | Arrêt spooler → purge file → redémarrage (natif Go, voir J2) | Maintenance | Courte | **Oui** | — |
| `sfc_scan` | `sfc /scannow` | Intégrité système | **Longue** (~10–20 min) | **Oui** | **UTF-16LE** |
| `dism_restore_health` | `dism /online /cleanup-image /restorehealth` | Intégrité système | **Longue** (jusqu'à ~1 h) | **Oui** | UTF-8 |
| `dism_component_cleanup` | `dism /online /cleanup-image /startcomponentcleanup` | Maintenance disque | **Longue** | **Oui** | UTF-8 |
| `chkdsk_scan` | `chkdsk /scan` | Intégrité disque | **Longue** | **Oui** | OEM |

Notes de périmètre :
- `gpupdate` en `/target:computer` : lancé par SYSTEM, seules les stratégies *ordinateur* s'appliquent — le type et son libellé UI l'assument explicitement.
- `chkdsk /scan` est l'analyse **en ligne** : elle signale sans réparer, donc sans immobiliser le poste. La réparation (`/spotfix`, appliquée au redémarrage) reste hors catalogue — c'est ce qui permet de lancer celle-ci sans précaution particulière, et le message d'échec y renvoie explicitement.
- Écarté pour le moment : `netsh winsock reset` (exige un reboot derrière). Réintégrable plus tard comme simple nouveau type.
- Deux classes de timeout : **courte** (5 min) et **longue** (`sfc` 30 min, `dism_restore_health` 2 h, `dism_component_cleanup` / `chkdsk_scan` 1 h). Les longues postent le statut intermédiaire `running`. Le couplage entre le drapeau « longue » et la classe de timeout est **testé** : une commande annoncée longue mais plafonnée à 5 min serait tuée pendant que la console l'affiche encore en cours.

## 3. Jalons

### J1 — Backend *(~0,5 j)*

Quasi rien à faire — c'est la récompense de l'architecture existante :
- `CommandType` ([command/models.py](backend/app/features/command/models.py)) += les 11 types (stockage `str` nu ⇒ **aucune migration**). Tenu : la prédiction était juste.
- Dépendance douce : l'acceptation de `status="running"` sur `POST /agent/commands/{id}/result` est spécifiée au plan Phase 2 (J1). Si ce chantier-ci démarre en premier, il l'implémente ; sinon il la réutilise. → **Implémenté ici.** `running` écrit `RUNNING` + `started_at` sans clore la commande (ni `finished_at`, ni écrasement de `result_output`), et est **ignoré** s'il arrive alors que la commande porte déjà un verdict : une livraison dupliquée ne doit pas rouvrir une commande close.
- **Tests pytest** : création de chaque nouveau type (patron `test_command_result_flow` de [test_api_console.py](backend/tests/test_api_console.py)), refus pour `readonly`, cycle `running` → `succeeded` si implémenté ici. → 17 tests ajoutés, dont un *paramétré sur les 11 types* et un garde-fou d'exhaustivité qui compare la liste paramétrée à l'énumération : un type ajouté sans test échoue la suite.

### J2 — Agent : exécution *(~1,5–2 j)*

**Nouveau fichier `agent/internal/collector/maintenance.go` / `maintenance_windows.go` / `maintenance_other.go`** (patron Defender : logique pure dans le fichier neutre, exécution dans `_windows.go`, stubs `errUnsupported` ailleurs) :

- **Exécution directe des .exe** via `exec.CommandContext` (gpupdate, sfc, dism, chkdsk, ipconfig, w32tm, gpresult, certutil) — pas de wrapper PowerShell nécessaire pour ces binaires, ~~ce qui évite une couche d'encodage~~. **Faux, et c'est l'écart principal de ce chantier** : éviter PowerShell évite *son* problème d'encodage et en découvre un autre, plus divers. Voir §7 et §8. Table interne : type → `{nom d'exe, args fixes, classe de timeout, encodage, verdict}`.
- **Cas `sfc_scan`** : sortie redirigée en **UTF-16LE entrelacée de nuls** → décodage dédié (fonction pure testée). Verdict = code retour + dernière ligne significative ~~(« aucune violation », « réparé », « non réparables »)~~ — **citée telle quelle, jamais reconnue** : ces libellés sont localisés, un Windows français ne les imprime jamais. Le code retour tranche succès/échec, la dernière ligne significative est reproduite verbatim.
- **Cas `dism`** : filtrer les lignes de progression (`\r`), interpréter le code retour (0 OK ; **3010 = succès avec redémarrage requis** ; `0x800f081f` source introuvable → message actionnable « source WU/WSUS inaccessible »). Le filtrage a fini **générique et non spécifique à dism** (§8).
- **Cas `spooler_reset`** : **natif Go** plutôt que shell — arrêt/démarrage du service via `golang.org/x/sys/windows/svc/mgr` (déjà importé pour le service Tiai), purge de `C:\Windows\System32\spool\PRINTERS\*.spl|*.shd` entre les deux. Plus sûr et testable qu'un one-liner PowerShell. À l'implémentation, deux précisions : on **attend** l'état `Stopped` avant de supprimer (sinon la purge court après un service qui n'a pas lâché ses handles), et le service est **redémarré même si la purge a échoué** — un poste sans spouleur est pire qu'une file encore pleine.
- **Garde-fous communs** : troncature de `output` (max ~64 Kio) avant POST ; mapping code retour → `succeeded`/`failed` avec message lisible ; statut `running` posté au démarrage des 4 commandes longues (best-effort, pattern Phase 2 J3).
- ~~**Dispatch** : 11 nouveaux `case` dans `execute`~~ → **une seule branche `default`** qui consulte le catalogue ([agent.go](agent/internal/agent/agent.go)), signature `func(ctx) (string, error)` conservée. Les onze entrées ne diffèrent que par des données : une douzième commande est une ligne de table et zéro ligne dans `agent.go`, ce que promettait déjà §4.

**Tests Go (logique pure)** : décodage UTF-16 de `sfc`, filtrage progression `dism`, mapping codes retour → statut/message, table type → commande (exhaustivité : chaque `CommandType` du catalogue a une entrée). Ajoutés en plus : détection UTF-8, formatage hexadécimal des HRESULT, non-découpe des runes à la troncature, et **trois tests d'intégration réels** sous Windows (`maintenance_windows_test.go`) qui lancent une commande par branche d'encodage — ce sont eux qui ont attrapé l'erreur de §8.

### J3 — Console *(~1–1,5 j)*

- [commands.ts](frontend/src/services/commands.ts) : `CommandType` += 11 valeurs, et **catalogue d'actions factorisé** `{type, label, icône, groupe, confirmation}` — remplace les deux tableaux dupliqués de [MachineDetailPage.vue](frontend/src/pages/MachineDetailPage.vue) et [MachinesPage.vue](frontend/src/pages/MachinesPage.vue). (Même factorisation prévue au plan Phase 2 J4 : le premier chantier qui passe la fait.) → **Faite ici**, avec deux champs de plus que prévu : `bulk` (éligibilité aux actions de masse) et `hint` (phrase de coût affichée dans la confirmation).
- **Organisation du menu** : avec Defender + WU + ce catalogue, le dropdown plat ne tient plus → sections avec en-têtes (`q-item-label header`) par groupe : Defender / Windows Update / Maintenance / Diagnostic. → Trois groupes livrés ; le quatrième arrive avec la Phase 2, sans autre changement qu'une valeur d'énumération et une entrée dans `groupOrder`.
- **Dialog « Résultat »** : la console n'affiche aujourd'hui que les *erreurs* de commande ; ajouter le pendant pour `result_output` (bouton loupe sur les commandes `succeeded`, même pattern que le dialog d'erreur existant, rendu `<pre>`). C'est là que `gpo_report` et `net_config` prennent leur valeur. → Livré en **un seul dialog** paramétré par le type de contenu plutôt qu'en deux quasi-identiques, et avec un bouton **Copier** : une sortie `ipconfig /all` finit dans un ticket, et la sélectionner à la souris dans un `<pre>` qui défile est une corvée.
- **Actions de masse** ([MachinesPage.vue](frontend/src/pages/MachinesPage.vue)) : les commandes de maintenance y figurent avec confirmation indiquant le nombre de postes ; les deux **diagnostics** (`gpo_report`, `net_config`) restent sur la page détail uniquement — leur valeur est la lecture individuelle du résultat, et en masse ils ne produisent que du bruit.
- **Tests vitest** (pattern services) : nouveaux types, catalogue factorisé (chaque type a un libellé/groupe), service commands inchangé par ailleurs. → 9 tests, dont l'exhaustivité du catalogue, la liste exacte des actions demandant confirmation, la présence d'un `hint` sur chacune, et l'exclusion des diagnostics du menu de masse.
- **Libellés des types dans l'historique** *(non prévu)* : avec quatorze types, la colonne « Type » affichant `dism_component_cleanup` devenait illisible → `commandTypeLabel`, qui retombe sur la valeur brute pour un type inconnu (une console plus ancienne face à un serveur plus récent doit afficher quelque chose, pas du vide).

### J4 — Validation + documentation *(~0,5 j)*

Voir §5. Puis mise à jour de `plan-projet-tiai.md` (suivi) et du README agent. → Fait, plus le **README racine** (le catalogue est une capacité produit, pas un détail d'agent : il figure dans « Pourquoi Tia'i » et le modèle de sécurité du catalogue dans le tableau des principes de conception). `DEPLOYMENT.md` est **inchangé** : ce chantier n'ajoute aucune clé de configuration ni surcharge registre.

## 4. Extensibilité

| Évolution future | Absorption |
|---|---|
| Nouvelle commande au catalogue | 1 valeur d'enum backend + 1 entrée de table agent + 1 entrée de catalogue UI — aucun changement de protocole ni migration. **Vérifié** : le dispatch agent est une consultation de table, pas un `switch` (§8) |
| `netsh winsock reset` | Même mécanique, à coupler avec la commande `reboot` de la Phase 2 |
| Commandes paramétrées (ex. ping vers une cible) | Exigerait le champ `payload` évoqué au plan Phase 2 §4 — volontairement hors périmètre : le catalogue reste sans arguments |

## 5. Vérification

1. ✅ **Qualité locale** : suites existantes (ruff/mypy/pytest ; gofmt/vet/go test + build croisé ; prettier/vue-tsc/vitest) — CI inchangée. **160 tests backend** (+17), **42 tests Go collector** (+30), **63 vitest** (+9, couverture 100 % maintenue sur `src/services` et `src/utils`), builds croisés `windows/amd64` et `windows/arm64`, build SPA vert.
2. ✅ **End-to-end**, fait **mieux que prévu** : plutôt qu'un agent simulé au curl, le **vrai binaire de l'agent** contre un backend local. Enrôlement → livraison au heartbeat → exécution → résultat en base. `net_config` et `flush_dns` en `succeeded`, accents vérifiés **directement en base** (`Nom de l'hôte`, `Cache de résolution DNS vidé.`) et non à travers une console qui aurait pu les mentir. `started_at` renseigné sur une commande longue, ce qui prouve le `running`. La consultation du dialog Résultat **dans un navigateur** reste à faire (logique testée, build vert).
3. **Poste réel** (DoD) — l'agent de test tournait **sans élévation**, et c'est ce qui départage la liste. Les trois commandes qui n'en ont pas besoin sont validées ; les huit autres ont, au mieux, leur chemin d'échec validé :
   - ✅ `net_config` et `gpo_report` → sortie complète et lisible (encodage correct) — validé, et c'est ce qui a révélé l'écart §8 ;
   - ✅ `flush_dns` → `succeeded` en quelques secondes ;
   - ⬜ `time_resync`, `cert_pulse`, `dism_component_cleanup` → **chemin d'échec validé** (« accès refusé » / « privilèges élevés requis », message lisible, code en hexadécimal, résultat correctement remonté). Chemin nominal à faire ;
   - ⬜ `gpo_update` → non exercé ;
   - ⬜ `spooler_reset` → le service repart, la file est vide ;
   - ⬜ `sfc_scan` → `running` visible pendant l'exécution, verdict final lisible (pas de texte UTF-16 corrompu) — **le seul cas d'encodage du catalogue encore non vérifié sur des octets réels** ;
   - ⬜ `dism_restore_health` → succès, ou échec avec message actionnable si la source est inaccessible ;
   - ⬜ `chkdsk_scan` → verdict lisible, et une corruption détectée renvoie bien vers `/spotfix` ;
   - ⬜ une commande longue n'empêche pas le heartbeat de continuer (worker séquentiel : les autres commandes attendent, comportement assumé).

> **Reste donc une seule campagne** : rejouer les huit commandes non cochées avec l'agent installé **en service** (`LocalSystem`), qui est de toute façon son mode de déploiement. Toutes les briques transverses — livraison, décodage, verdicts, `running`, troncature, remontée en base — sont validées et ne dépendent pas du niveau de privilège ; l'inconnue résiduelle est le comportement propre de chaque outil une fois qu'il peut réellement travailler, `sfc` en tête.

## 6. Séquencement avec la Phase 2

~~Les deux chantiers sont indépendants fonctionnellement mais partagent deux briques~~ → **Ce chantier est passé en premier et a posé les deux briques.** La Phase 2 les trouve faites :

| Brique | État | Ce que la Phase 2 a encore à faire |
|---|---|---|
| `running` / `started_at` (Phase 2 J1 + J3) | ✅ livré ici, backend **et** agent | Rien côté serveur. Côté agent, marquer `wu_install*` comme `long` — le mécanisme d'annonce est générique |
| Catalogue d'actions UI factorisé (Phase 2 J4) | ✅ livré ici (`commandActions`) | Ajouter 4 entrées et le groupe `windows_update` à `groupOrder` ; plus aucun tableau dupliqué à tenir |

Restent propres à la Phase 2 : sa migration (qui devient `0008_windows_update`, `0007_av_product` ayant été livrée entre-temps), son bloc de heartbeat, son cycle de collecte lent. **Un point d'attention nouveau pour elle** : ses quatre commandes passent par PowerShell/WUA et non par un `.exe` de `System32`, donc elles ne relèvent **pas** du catalogue `maintenance*.go` ni de sa table d'encodages — `runPowerShell()` règle déjà la question de son côté. Le `reboot`, en revanche, est un `shutdown.exe` de System32 : il peut rejoindre le catalogue tel quel.

## 7. Points d'attention

- **L'encodage n'est pas un piège `sfc`, c'en est quatre.** ~~C'est le seul binaire du lot à sortir de l'UTF-16 entrelacé~~ : `sfc` est bien le seul en UTF-16, mais les autres ne s'accordent pas pour autant. Mesuré (Windows 11 fr, sortie capturée dans un tube) : `ipconfig`/`w32tm` écrivent en **OEM** (CP850), `certutil` en **ANSI** (CP1252), `gpresult`/`dism` en **UTF-8**. Et ce n'est pas la page de codes de la console : `GetConsoleOutputCP()` répondait 65001 pendant qu'`ipconfig` émettait du CP850 — ce qui compte est que la sortie soit *redirigée*, pas ce à quoi le terminal est réglé. En service il n'y a de toute façon aucune console. Détail complet en §8.
- **`dism /restorehealth` dépend de la source WU/WSUS** du poste : sur un parc WSUS mal configuré il échoue — le message d'erreur doit orienter (« source de réparation inaccessible ») plutôt que recopier le charabia DISM.
- **`w32tm /resync`** échoue si le service de temps est arrêté → message actionnable.
- **Charge en masse** : `sfc`/`dism`/`chkdsk` sur tout le parc = pic d'I/O disque généralisé ; le polling étale naturellement (récupération au heartbeat), mais la confirmation de masse doit afficher le nombre de postes — et le TTL par défaut (60 min) borne l'étalement.
- **Volume des sorties** : troncature à ~64 Kio côté agent pour protéger la base et l'UI. Le serveur re-plafonne à la réception : l'agent est la partie que le serveur ne contrôle pas.
- **Codes de retour illisibles** *(constaté)* : Windows renvoie des HRESULT, que Go remonte en décimal non signé. `2147942405` ne dit rien à personne, `0x80070005` se reconnaît à vue (accès refusé) — d'où le formatage hexadécimal au-delà de 16 bits.

## 8. Écarts constatés à l'implémentation

Le plan a tenu dans sa structure — jalons, catalogue, modèle de sécurité, aucune migration — mais s'est trompé sur un point de fond, et a gagné trois durcissements en route.

### L'écart de fond : quatre encodages, pas un

Le plan traitait l'encodage comme une singularité de `sfc`, et considérait même que se passer de PowerShell « évitait une couche d'encodage ». C'est l'inverse : le wrapper `runPowerShell()` existant *neutralisait* la question en réencodant en UTF-8 avant de rendre la main. En appelant les `.exe` directement, on hérite du choix de chaque outil — et il n'y a pas de choix commun.

La première version préférait `GetConsoleOutputCP()`, en raisonnant qu'un enfant hérite de la console du parent. **Le test d'intégration réel l'a démenti immédiatement** : sur un terminal réglé à 65001, `ipconfig` émettait `0x93` pour `ô`, ce qui est du CP850 et rien d'autre. Ce qui gouverne l'encodage est la *redirection*, pas la console.

La réponse retenue tient en trois branches ordonnées, et l'ordre compte :

1. **UTF-16LE d'abord**, parce qu'un octet nul est un UTF-8 parfaitement valide : la sortie de `sfc` passerait sinon le test suivant avec un nul entre chaque caractère. La déclaration du catalogue est **vérifiée sur les octets** avant d'être appliquée — une version de `sfc` qui changerait d'avis dégraderait vers du texte lisible plutôt que vers des idéogrammes.
2. **UTF-8 ensuite**, par auto-détection : une lettre accentuée CP850 ou CP1252 isolée (`0x82`, `0xE9`, `0x93`) n'est jamais le début d'une séquence multi-octets bien formée, donc du texte page-de-codes ne peut pratiquement pas passer pour de l'UTF-8. C'est ce qui garde la table par outil **minuscule** : `gpresult` et `dism` n'y ont aucune entrée et n'en auront jamais besoin.
3. **La page de codes déclarée en dernier** — la seule chose qui ne se détecte pas depuis les octets. `CP_OEMCP`/`CP_ACP` (pseudo-valeurs « ce que ce système est configuré pour »), jamais un 850 ou un 1252 en dur, qui seraient faux sur le premier parc non occidental.

Un seul outil a donc une entrée d'exception : `certutil`, en ANSI.

### Le filtrage de progression, plus simple que prévu

Le plan prévoyait de « filtrer les lignes de progression (`\r`) » de `dism`, ce qui appelait une heuristique par outil (chercher un `%`, un `[`…) et donc dépendante de la langue. La solution retenue est de **rejouer les retours chariot comme le ferait une console** : tout ce qui précède le dernier `\r` d'une ligne a été écrasé à l'écran, donc n'existe pas. C'est le rendu exact de ce qu'un opérateur aurait vu, ça ne dépend d'aucun format, et ça couvre `sfc` gratuitement — un cas que le plan n'avait pas relié à celui de `dism`. Piège rencontré : il faut normaliser `\r\n` → `\n` **avant**, faute de quoi la règle supprime chaque ligne terminée par un CRLF.

### Trois durcissements ajoutés

- **Chemins absolus sous `System32`** (§1). Absent du plan, et pourtant la conséquence directe de son propre modèle de sécurité : verrouiller ce que le serveur peut demander a peu d'intérêt si l'on laisse le `PATH` décider *quel binaire* répond, dans un processus `LocalSystem`.
- **Statuts que l'agent peut poster** restreints à `running`/`succeeded`/`failed` (§1), plus un plafonnement serveur du texte reçu. Même raisonnement : l'agent est la partie que le serveur ne contrôle pas.
- **`running` ignoré après un verdict.** Le plan décrivait la transition heureuse ; une livraison dupliquée ou rejouée aurait rouvert une commande close.

### Ce que le plan avait raison de prévoir

Deux prédictions se sont vérifiées telles quelles et méritent d'être notées, parce qu'elles justifient l'architecture de M3 : le backend n'a coûté **qu'une extension d'énumération, sans migration**, et le dispatch agent s'est réduit à **une consultation de table** au lieu des onze `case` annoncés — une douzième commande coûtera trois lignes de données réparties sur trois composants, et zéro ligne de logique.

### Reste à faire

La validation en `LocalSystem` des huit commandes qui exigent l'élévation (§5). Une seule porte un vrai risque résiduel : **`sfc_scan` est la dernière branche d'encodage du catalogue à n'avoir jamais vu d'octets réels** — son UTF-16 est documenté et testé sur fixture, mais pas mesuré comme les trois autres, et c'est précisément la mesure qui a démenti le plan pour les autres outils. Le repli est en place (`looksUTF16LE` vérifie avant de décoder, donc une surprise dégrade vers du texte lisible plutôt que vers des idéogrammes), mais la vérification reste à faire.

Pour le reste, ce sont les chemins nominaux de commandes dont le chemin d'échec, la livraison et la remontée sont déjà éprouvés.

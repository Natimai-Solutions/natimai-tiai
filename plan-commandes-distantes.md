# Catalogue de commandes de maintenance à distance : plan de travail

> Objectif : exécuter à distance un **catalogue fermé** de commandes de maintenance et de diagnostic Windows, avec remontée du résultat dans la console.
> Chantier indépendant de la Phase 2 (Windows Update, cf. `plan-phase2-windows-update.md`), mais qui partage deux briques avec elle (statut `running`, factorisation des actions UI) — voir §6 Séquencement.

---

## 1. Modèle de sécurité

- **Catalogue fixe, codé en dur dans le binaire de l'agent.** Le serveur ne transmet que l'identifiant du type (`{id, type}`, protocole inchangé) ; **aucun argument ne traverse le réseau**. Même un serveur compromis ne peut déclencher que le catalogue, jamais de code arbitraire.
- Pas d'exécuteur de scripts libre, pas de modification registre/fichiers/pare-feu/utilisateurs — exclusions de principe, à ne pas réintroduire au fil de l'eau.
- Autorisation : permission existante `command:execute` (admin seul). Audit : table `commands` existante (`created_by`, horodatages).
- Confirmation UI (`$q.dialog`) pour les commandes de maintenance ; les diagnostics en lecture seule partent sans confirmation.

## 2. Catalogue retenu (11 commandes)

| `CommandType` | Commande exécutée | Famille | Durée | Confirmation |
|---|---|---|---|---|
| `gpo_update` | `gpupdate /target:computer /force` | Maintenance AD | Courte | Non |
| `gpo_report` | `gpresult /r /scope:computer` | **Diagnostic** | Courte | Non |
| `flush_dns` | `ipconfig /flushdns` | Maintenance réseau | Courte | Non |
| `net_config` | `ipconfig /all` | **Diagnostic** | Courte | Non |
| `time_resync` | `w32tm /resync` | Maintenance AD | Courte | Non |
| `cert_pulse` | `certutil -pulse` | Maintenance AD (AC interne) | Courte | Non |
| `spooler_reset` | Arrêt spooler → purge file → redémarrage (natif Go, voir J2) | Maintenance | Courte | **Oui** |
| `sfc_scan` | `sfc /scannow` | Intégrité système | **Longue** (~10–20 min) | **Oui** |
| `dism_restore_health` | `dism /online /cleanup-image /restorehealth` | Intégrité système | **Longue** (jusqu'à ~1 h) | **Oui** |
| `dism_component_cleanup` | `dism /online /cleanup-image /startcomponentcleanup` | Maintenance disque | **Longue** | **Oui** |
| `chkdsk_scan` | `chkdsk /scan` | Intégrité disque | **Longue** | **Oui** |

Notes de périmètre :
- `gpupdate` en `/target:computer` : lancé par SYSTEM, seules les stratégies *ordinateur* s'appliquent — le type et son libellé UI l'assument explicitement.
- Écarté pour le moment : `netsh winsock reset` (exige un reboot derrière). Réintégrable plus tard comme simple nouveau type.
- Deux classes de timeout : **courte** (5 min) et **longue** (`sfc` 30 min, `dism_restore_health` 2 h, `dism_component_cleanup` / `chkdsk_scan` 1 h). Les longues postent le statut intermédiaire `running`.

## 3. Jalons

### J1 — Backend *(~0,5 j)*

Quasi rien à faire — c'est la récompense de l'architecture existante :
- `CommandType` ([command/models.py](backend/app/features/command/models.py)) += les 11 types (stockage `str` nu ⇒ **aucune migration**).
- Dépendance douce : l'acceptation de `status="running"` sur `POST /agent/commands/{id}/result` est spécifiée au plan Phase 2 (J1). Si ce chantier-ci démarre en premier, il l'implémente ; sinon il la réutilise.
- **Tests pytest** : création de chaque nouveau type (patron `test_command_result_flow` de [test_api_console.py](backend/tests/test_api_console.py)), refus pour `readonly`, cycle `running` → `succeeded` si implémenté ici.

### J2 — Agent : exécution *(~1,5–2 j)*

**Nouveau fichier `agent/internal/collector/maintenance.go` / `maintenance_windows.go` / `maintenance_other.go`** (patron Defender : logique pure dans le fichier neutre, exécution dans `_windows.go`, stubs `errUnsupported` ailleurs) :

- **Exécution directe des .exe** via `exec.CommandContext` (gpupdate, sfc, dism, chkdsk, ipconfig, w32tm, gpresult, certutil) — pas de wrapper PowerShell nécessaire pour ces binaires, ce qui évite une couche d'encodage. Table interne : type → `{chemin exe, args fixes, classe de timeout}`.
- **Cas `sfc_scan`** : sortie redirigée en **UTF-16LE entrelacée de nuls** → décodage dédié (fonction pure testée). Verdict = code retour + dernière ligne significative (« aucune violation », « réparé », « non réparables »).
- **Cas `dism`** : filtrer les lignes de progression (`\r`), interpréter le code retour (0 OK ; `0x800f081f` source introuvable → message actionnable « source WU/WSUS inaccessible »).
- **Cas `spooler_reset`** : **natif Go** plutôt que shell — arrêt/démarrage du service via `golang.org/x/sys/windows/svc/mgr` (déjà importé pour le service Tiai), purge de `C:\Windows\System32\spool\PRINTERS\*.spl|*.shd` entre les deux. Plus sûr et testable qu'un one-liner PowerShell.
- **Garde-fous communs** : troncature de `output` (max ~64 Kio) avant POST ; mapping code retour → `succeeded`/`failed` avec message lisible ; statut `running` posté au démarrage des 4 commandes longues (best-effort, pattern Phase 2 J3).
- **Dispatch** : 11 nouveaux `case` dans `execute` ([agent.go:239](agent/internal/agent/agent.go#L239)), signature `func(ctx) (string, error)` conservée.

**Tests Go (logique pure)** : décodage UTF-16 de `sfc`, filtrage progression `dism`, mapping codes retour → statut/message, table type → commande (exhaustivité : chaque `CommandType` du catalogue a une entrée).

### J3 — Console *(~1–1,5 j)*

- [commands.ts](frontend/src/services/commands.ts) : `CommandType` += 11 valeurs, et **catalogue d'actions factorisé** `{type, label, icône, groupe, confirmation}` — remplace les deux tableaux dupliqués de [MachineDetailPage.vue](frontend/src/pages/MachineDetailPage.vue) et [MachinesPage.vue](frontend/src/pages/MachinesPage.vue). (Même factorisation prévue au plan Phase 2 J4 : le premier chantier qui passe la fait.)
- **Organisation du menu** : avec Defender + WU + ce catalogue, le dropdown plat ne tient plus → sections avec en-têtes (`q-item-label header`) par groupe : Defender / Windows Update / Maintenance / Diagnostic.
- **Dialog « Résultat »** : la console n'affiche aujourd'hui que les *erreurs* de commande ; ajouter le pendant pour `result_output` (bouton loupe sur les commandes `succeeded`, même pattern que le dialog d'erreur existant, rendu `<pre>`). C'est là que `gpo_report` et `net_config` prennent leur valeur.
- **Actions de masse** ([MachinesPage.vue](frontend/src/pages/MachinesPage.vue)) : les commandes de maintenance y figurent avec confirmation indiquant le nombre de postes ; les deux **diagnostics** (`gpo_report`, `net_config`) restent sur la page détail uniquement — leur valeur est la lecture individuelle du résultat, et en masse ils ne produisent que du bruit.
- **Tests vitest** (pattern services) : nouveaux types, catalogue factorisé (chaque type a un libellé/groupe), service commands inchangé par ailleurs.

### J4 — Validation + documentation *(~0,5 j)*

Voir §5. Puis mise à jour de `plan-projet-tiai.md` (suivi) et du README agent.

## 4. Extensibilité

| Évolution future | Absorption |
|---|---|
| Nouvelle commande au catalogue | 1 valeur d'enum backend + 1 entrée de table agent + 1 entrée de catalogue UI — aucun changement de protocole ni migration |
| `netsh winsock reset` | Même mécanique, à coupler avec la commande `reboot` de la Phase 2 |
| Commandes paramétrées (ex. ping vers une cible) | Exigerait le champ `payload` évoqué au plan Phase 2 §4 — volontairement hors périmètre : le catalogue reste sans arguments |

## 5. Vérification

1. **Qualité locale** : suites existantes (ruff/mypy/pytest ; gofmt/vet/go test + build croisé ; prettier/vue-tsc/vitest) — CI inchangée.
2. **End-to-end simulé** : stack compose dev + agent simulé (curl) : création de chaque type depuis l'API, livraison au heartbeat, résultat `running` puis final, consultation du `result_output` dans la console via le nouveau dialog.
3. **Poste réel** (DoD) :
   - `net_config` et `gpo_report` → sortie complète et lisible (encodage correct) dans le dialog Résultat ;
   - `flush_dns`, `time_resync`, `cert_pulse`, `gpo_update` → `succeeded` en quelques secondes ;
   - `spooler_reset` → le service repart, la file est vide ;
   - `sfc_scan` → `running` visible pendant l'exécution, verdict final lisible (pas de texte UTF-16 corrompu) ;
   - `dism_restore_health` → succès, ou échec avec message actionnable si la source est inaccessible ;
   - une commande longue n'empêche pas le heartbeat de continuer (worker séquentiel : les autres commandes attendent, comportement assumé).

## 6. Séquencement avec la Phase 2

Les deux chantiers sont indépendants fonctionnellement mais partagent deux briques : le câblage `running`/`started_at` (spécifié en Phase 2 J1/J3) et la factorisation du catalogue d'actions UI (Phase 2 J4 / ici J3). **Recommandation : réaliser la Phase 2 J1 d'abord** (elle pose la brique backend `running`), puis les deux chantiers peuvent avancer dans n'importe quel ordre — celui qui passe en premier sur le frontend fait la factorisation.

## 7. Points d'attention

- **`sfc` piège d'encodage** : c'est le seul binaire du lot à sortir de l'UTF-16 entrelacé — sans décodage dédié, le résultat remonté est illisible. Test unitaire sur fixture réelle obligatoire.
- **`dism /restorehealth` dépend de la source WU/WSUS** du poste : sur un parc WSUS mal configuré il échoue — le message d'erreur doit orienter (« source de réparation inaccessible ») plutôt que recopier le charabia DISM.
- **`w32tm /resync`** échoue si le service de temps est arrêté → message actionnable.
- **Charge en masse** : `sfc`/`dism`/`chkdsk` sur tout le parc = pic d'I/O disque généralisé ; le polling étale naturellement (récupération au heartbeat), mais la confirmation de masse doit afficher le nombre de postes — et le TTL par défaut (60 min) borne l'étalement.
- **Volume des sorties** : troncature à ~64 Kio côté agent pour protéger la base et l'UI.

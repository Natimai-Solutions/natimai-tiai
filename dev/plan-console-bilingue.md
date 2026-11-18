# Console bilingue français / anglais — plan de travail

> **Statut : livré le 2026-11-18** (I1 à I6, §7 et §8). Phase 6 de `plan-projet-tiai.md`.
>
> Objectif : une console en français ou en anglais, au choix de chaque
> compte, et un backend qui ne rédige plus de phrases pour la console. Le
> backend renvoie des **codes, des paramètres et des valeurs brutes** ; la
> console compose les phrases dans la langue de l'utilisateur.
>
> **Contrainte de départ : une installation existante se met à jour sans
> rien changer à ce qu'elle voit.** Le français reste la langue par défaut et
> la langue de repli, l'anglais n'est proposé qu'une fois la console
> entièrement traduite, et toute modification de l'API ou de l'agent est
> additive.

---

## 1. Décisions

1. **Langues** : français et anglais.
2. **Choix** : par compte, enregistré côté serveur ; tant que le compte n'a
   rien choisi, la console suit la langue du navigateur. Les pages sans
   compte (connexion, mot de passe oublié) suivent le navigateur.
3. **Backend agnostique** pour tout ce qu'affiche la console : codes,
   paramètres et valeurs brutes. Les dates, nombres et tailles sont mis en
   forme par la console.
4. **Trois exceptions assumées**, où le serveur écrit lui-même :
   - les **e-mails**, qui partent sans navigateur : dans la langue du
     destinataire, sinon dans `DEFAULT_LANGUAGE` ;
   - les **exports CSV et Excel**, téléchargés directement : dans la langue
     que la console demande ;
   - le **`message`** du contrat d'erreurs, gardé comme texte de repli pour
     les journaux, les scripts qui appellent l'API et une console plus
     ancienne. La console ne l'affiche plus.
5. **Ce qui ne se traduit pas** : la sortie des outils Windows (dans la
   langue du poste) et ce que les utilisateurs saisissent (noms, notes,
   consignes).

## 2. Compatibilité des installations existantes

| Point | Garantie |
|---|---|
| Langue affichée | Tant que l'anglais n'est pas complet, la console reste en français, quel que soit le navigateur (`ENGLISH_AVAILABLE`, §4.1). Ensuite, un compte qui n'a rien choisi suit son navigateur : un navigateur en français garde la console en français. |
| Comptes existants | Colonne `users.language` nulle : « suivre le navigateur ». Aucune donnée à reprendre. |
| E-mails | `DEFAULT_LANGUAGE=fr` par défaut : rien ne change pour qui ne le règle pas. |
| API | Additive : les champs texte existants restent (`problems`, `install_blockers`, `message`…), les codes s'ajoutent à côté. |
| Données enregistrées | Les verdicts et textes déjà en base gardent leur texte français et s'affichent tels quels ; seuls les nouveaux portent un code. |
| Agents en place | Un ancien agent n'envoie pas de code : son texte s'affiche tel quel, comme aujourd'hui. |

## 3. Ce que le backend envoie aujourd'hui en français

Relevé du 2026-11-18 : environ 420 lignes dans 38 fichiers.

| Famille | Exemples | Traitement | Jalon |
|---|---|---|---|
| Erreurs de l'API | 117 codes, déjà traduits par la console | Catalogue fr/en ; les trois codes dont la console affiche le texte (`package.invalid`, `package.signature.invalid`, `package.file.name_invalid`) reçoivent des paramètres | I1, I2 |
| Diagnostics calculés | Problèmes et blocages d'un paquet, règle `msiexec`, relais de réveil | `{code, params}` à côté du texte | I2 |
| Libellés et valeurs mises en forme | Page Paramètres → serveur, descriptions des droits | Valeurs brutes et codes | I2 |
| Verdicts enregistrés | Commande perdue, paquet retiré, sortie tronquée | Colonnes `result_code`, `result_params` ; les anciennes lignes gardent leur texte | I3 |
| E-mails | Réinitialisation, résumé, alertes, e-mail de test | Gabarits par langue | I4 |
| Exports | En-têtes, états | Paramètre `lang` | I4 |
| Messages de l'agent | Réinitialisation Windows Update, maintenance | Champ facultatif `message_code` + `message_params` | I5 |

## 4. Console

### 4.1 Socle

- **Bibliothèque** : `vue-i18n` 11, en mode composition, compilation des
  messages sans `eval` (compatible avec la CSP de Caddy, `script-src 'self'`).
- **Catalogues par domaine** (`src/i18n/messages/<domaine>.ts`), chacun avec
  son français et son anglais côte à côte. L'anglais est typé d'après le
  français : une clé sans traduction ne compile pas.
- **`t()` importable** depuis `src/i18n`, utilisable dans les scripts, les
  utilitaires et les tests sans monter de plugin.
- **Langue courante** : préférence du compte, sinon premier choix du
  navigateur parmi les langues disponibles, sinon français.
  `ENGLISH_AVAILABLE` (faux tant que l'extraction n'est pas finie) réduit les
  langues disponibles au français.
- **Pack de langue Quasar** chargé selon la langue (pagination, sélecteurs).
- **Mise en forme** : `Intl` avec la langue courante (`fr-FR`, `en-GB` : le
  jour avant le mois, comme en français).
- **Choix de la langue** dans « Mon compte », visible dès que l'anglais est
  disponible.

### 4.2 Extraction

Environ 1 300 lignes de texte dans une centaine de fichiers. Par page ou par
composant, chaque texte passe dans le catalogue de son domaine avec sa
traduction. Les tests existants vérifient le français ; un test par page la
monte aussi en anglais et vérifie qu'aucun texte français connu n'y reste.

## 5. Backend

- `users.language` (`fr`, `en` ou nul), lu et écrit par `/auth/me`.
- `DEFAULT_LANGUAGE` (`fr`) : langue des e-mails d'un compte sans choix et
  des e-mails sans compte.
- Codes : même règle que les codes d'erreur (`domaine.sujet.cas`), stables,
  avec des paramètres nommés ; un test vérifie que chaque code émis a sa
  traduction dans les deux langues de la console.

### 5.1 Réalisé (I1 et I2, paquets)

- **Langue du compte** : `GET/PATCH /auth/me` lisent et écrivent `language`
  (`fr`, `en` ou `null`) ; une valeur stockée qui n'est pas une langue se lit
  `null`.
- **Diagnostics de paquets** : chaque problème (`problems`,
  `install_blocker_problems`) porte `params` à côté de son `code` ; les refus
  `package.invalid`, `package.file.name_invalid` et
  `package.signature.invalid` portent `details.cause` (`code`, `params`), et
  `package.not_ready` porte `details.causes`. Les textes français
  (`message`, `problems`, `install_blockers`, `details.reason`) restent.
- **Le français de la console est celui du serveur, mot pour mot** : le jeu
  de cas partagé `backend/tests/data/package_texts_fr.json` est vérifié des
  deux côtés (`test_package_texts.py`, `utils/packageText.spec.ts`).
- **Serveur plus ancien ou plus récent que la console** : un problème sans
  `params`, ou un code que la console ne connaît pas, s'affiche avec la
  phrase du serveur.
- **Noms et descriptions des groupes intégrés** : ce sont des données, que
  l'administrateur peut modifier. La console les traduit tant qu'ils gardent
  ceux donnés à l'installation (§8).

## 6. Agent

Champ facultatif `message_code` et `message_params` dans le résultat d'une
commande. Le texte reste envoyé : un serveur plus ancien l'affiche, un
serveur à jour traduit le code. Rien ne change pour un agent non mis à jour.

## 7. Jalons

| Jalon | Contenu | Statut |
|---|---|---|
| **I1 — Socle** | `vue-i18n`, catalogues, langue du compte (`users.language`, migration `0045`), langue du navigateur, pack Quasar, mise en forme, catalogue des erreurs en deux langues, test de complétude | fait |
| **I2 — Backend agnostique** | Diagnostics de paquets, page Paramètres → serveur, e-mail de test, refus de validation (422) : codes et valeurs brutes | fait |
| **I3 — Verdicts enregistrés** | `commands.result_code`, `result_params` (migration `0046`) ; journal des interventions et clôture des vérifications (migration `0047`) ; détail du réveil | fait |
| **I4 — E-mails et exports** | Gabarits par langue, langue du destinataire, `DEFAULT_LANGUAGE`, paramètre `lang` des exports | fait |
| **I5 — Agent** | `message_code` + `message_params` dans les résultats ; environ 90 codes (`agent/internal/msg`) | fait |
| **I6 — Extraction** | Toute la console dans les catalogues, traduction anglaise, `ENGLISH_AVAILABLE` passé à vrai | fait |

## 8. Réalisation (2026-11-18)

- **Découpage** : neuf lots traduits en parallèle, chacun propriétaire de ses
  fichiers et de son catalogue (`src/i18n/messages/<domaine>.ts`), fusionnés
  ensuite. Le garde-fou `src/i18n/noHardcodedFrench.spec.ts` (heuristique
  `scan.ts`) refuse tout texte d'interface français hors des catalogues ; sa
  liste `PENDING` est vide.
- **Le français de la console est celui d'avant, mot pour mot** : aucune
  attente française des tests existants n'a été modifiée (quelques tests ont
  reçu des assertions de plus). Là où le serveur écrivait la phrase, un jeu
  de cas partagé, écrit et vérifié par le backend, est relu par la console :
  `backend/tests/data/package_texts_fr.json`, `validation_texts_fr.json`,
  `settings_texts_fr.json`, `command_texts_fr.json`, `journal_texts_fr.json` ;
  côté agent, `agent/internal/msg/testdata/messages_fr.json`. Les e-mails, que
  seul le serveur écrit, ont le leur : `backend/tests/data/mail_texts.json`,
  qui fige leur français d'avant et leur anglais.
- **Changement de langue en direct** : aucun texte n'est traduit au chargement
  d'un module ; colonnes, listes d'options et titres d'onglet sont recalculés.
  Testé page par page, et de bout en bout (`frontend/e2e/language.spec.ts`).
- **Vérifié dans un navigateur**, derrière la CSP de Caddy : les seize pages,
  onglets compris, en anglais sur un banc peuplé, sans texte français restant
  ni erreur.
- **Choix faits en cours de route** :
  - les **groupes intégrés** sont nommés dans la langue du lecteur tant qu'ils
    gardent le nom et la description de l'installation (`builtin_key` sur les
    références de groupe, `utils/groupText.ts`) ;
  - le **CSV anglais** est séparé par des virgules, avec le point décimal,
    comme l'Excel d'un poste réglé en anglais le lit ; le CSV français garde
    `;` et la virgule décimale, octet pour octet. Un lecteur de la console
    anglaise sur un poste réglé en français prend le format par défaut, XLSX,
    qui n'a pas de séparateur à deviner (décision revue le 18 novembre) ;
  - les **refus propres à Pydantic** (champ manquant, longueur…) gardent leur
    message anglais, comme avant ;
  - restent en texte, sans code : la sortie des outils Windows (y compris
    citée dans un détail), le rapport détaillé d'installation des mises à
    jour Windows, les étapes de la réinitialisation de Windows Update, les
    échecs partiels du spouleur, le refus combiné « méthode B … ; méthode
    A … » et la phrase « Redémarrage requis… » ajoutée à la sortie de DISM ;
  - une cause elle-même codée, citée dans le détail d'un autre message de
    l'agent, transmet son code (`detail_code`, `detail_<nom>`) : la console
    l'écrit dans la langue du lecteur (vérification du 18 novembre).

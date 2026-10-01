# Tia'i — Frontend (console)

SPA Quasar / Vue 3 autonome (TypeScript). Sert la console de supervision.

## Dév

```bash
cd frontend
npm install          # exécute aussi `quasar prepare`
npm run dev          # http://localhost:9000 (proxy /api -> http://localhost:8000)
```

## Build

```bash
npm run build        # génère dist/spa, servi par nginx (cf. Dockerfile)
```

## Layout

```
src/
  boot/axios.ts             instance axios (baseURL = API_BASE_URL, défaut /api/v1)
  composables/              logique de page réutilisable (rafraîchissement auto,
                            listes de filtres du parc, actions de masse, colonnes)
  layouts/MainLayout.vue    coquille applicative
  pages/MachinesPage.vue    liste des postes : le câblage URL ⇄ serveur ⇄ composants
  pages/MachineDetailPage   fiche d'un poste (onglets, dont Historique : maintenance + journal)
  pages/RoomsPage.vue       salles et bâtiments ; RoomDetailPage : une salle et ses postes
  pages/TasksPage.vue       « Mes tâches » : vérifications affectées, maintenances à faire
  pages/GroupsPage.vue      groupes de droits (grille ressources × actions)
  pages/SettingsPage.vue    défauts du parc (maintenance)
  pages/AuditPage.vue       journal d'audit (permission audit:read) : filtres et page dans l'URL
  components/machines-list/ morceaux de la liste des postes : barre d'outils, filtres
                            (barre, panneau replié, puces), actions de masse, tableau
  components/machine/       cartes et dialogues de la fiche d'un poste
  components/check|maintenance|room   dialogues des chantiers d'exploitation
  components/audit/         filtres et détail d'une entrée du journal d'audit
  utils/permissions.ts      catalogue des permissions, miroir du backend ; auth.can()
  router/                   routes
  services/machines.ts      appels API typés
  utils/format.ts           libellés et couleurs partagés
  utils/machineQuery.ts     URL de la liste des postes → paramètres API (lue aussi par la fiche)
  utils/machineListFilters  filtres de la liste : URL ⇄ filtres → paramètres API, puces
  utils/machineListTable    colonnes de la liste, tri et page dans l'URL
  utils/auditLabels.ts      libellés des actions / ressources d'audit, résumé des détails
  utils/auditQuery.ts       état URL du journal ; période (jours locaux → since/until)
  test/                     outillage des tests de composants (Quasar, fixtures)
```

La logique qui ne dessine rien vit dans `utils/` en fonctions pures, testées
sans DOM ; les composants ne font que la brancher. L'URL reste la source de
vérité des filtres : un composant émet un nouvel état, la page l'écrit dans
l'URL, et c'est la relecture de l'URL qui recharge la liste.

L'interface est en français jusque dans les libellés internes de Quasar
(pagination des tableaux, sélecteurs de date) : `framework.lang: 'fr'` dans
`quasar.config.ts`. Une page ne surcharge un de ces libellés que lorsqu'elle
veut autre chose que le pack.

## Tests

```bash
npm test                 # toute la suite
npm run test:coverage    # avec la couverture et ses seuils
npx vitest run --project components   # seulement les tests de composants
```

Deux projets Vitest (`vitest.config.ts`) :

- **unit** — services, utils, composables, en environnement `node`. Un
  composable qui a besoin d'un DOM le dit en tête de son fichier
  (`// @vitest-environment jsdom`).
- **components** — tout `*.spec.ts` sous `src/components/` et `src/pages/`, en
  `jsdom`. Le fichier de mise en place (`src/test/setupComponents.ts`) installe
  Quasar comme l'application (mêmes plugins, pack de langue français) et
  remplace l'instance axios par un bouchon qui refuse tout appel : un test de
  composant ne parle à aucun serveur, et celui qui veut une réponse simule le
  service dont il a besoin.

Les balises `<q-…>` sont résolues à la compilation par le plugin Vite de Quasar,
comme dans le build : un composant monté rend les vrais composants Quasar, pas
des bouchons. On les retrouve avec `findComponent(QSelect)` et on les pilote en
émettant leurs événements (`vm.$emit('update:modelValue', …)`) ou en cliquant ;
un test lit ce que le composant émet, pas son état interne. Les données de poste
communes sont dans `src/test/fixtures.ts`.

La couverture mesure `composables/`, `services/`, `utils/` et les dossiers de
composants dont **chaque** composant a ses tests (aujourd'hui
`components/machines-list/`). Mesurer tout `src/components/` compterait une
trentaine de dialogues et de cartes encore sans test, et ferait des seuils un
compteur d'arriéré plutôt qu'un garde-fou ; un dossier rejoint le périmètre
quand ses composants sont tous couverts.

## Rafraîchissement automatique

Le tableau de bord et la fiche d'un poste se rafraîchissent seuls via
`composables/useAutoRefresh.ts`, toutes les **90 s** — un peu plus que le
heartbeat de l'agent (60 s). La console ne peut afficher que ce que le dernier
heartbeat a écrit : interroger plus vite que les postes ne remontent coûterait
des requêtes sans jamais rien montrer de neuf, et une période _égale_ battrait
avec la leur.

Trois garde-fous, chacun étant un bug qu'on aurait sinon livré :

- **rien pendant qu'un onglet est masqué** (une console laissée ouverte la nuit
  tirerait un millier de requêtes pour un écran que personne ne regarde), avec
  rattrapage immédiat au retour sur l'onglet ;
- **jamais deux rafraîchissements en vol** ;
- **les échecs sont avalés** — une notification toutes les 90 s sur un lien
  instable est pire qu'une donnée d'un cycle de retard. Le 401 fait exception et
  est traité là où il doit l'être, dans l'intercepteur axios.

Le **journal d'audit** ne se rafraîchit pas seul : il se lit comme une archive,
et des lignes qui glisseraient sous un lecteur en train d'en comparer deux
seraient pires qu'une vue d'un clic de retard. Seul « Actualiser » le recharge.

Les rafraîchissements automatiques n'allument **pas** le spinner : seul le
bouton « Actualiser » le fait. La fiche détail se met en pause tant qu'une
boîte de dialogue est ouverte au-dessus de ses tableaux.

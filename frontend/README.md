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
  composables/              logique de page réutilisable (rafraîchissement auto)
  layouts/MainLayout.vue    coquille applicative
  pages/MachinesPage.vue    liste des postes
  pages/MachineDetailPage   fiche d'un poste (onglets, dont Historique : maintenance + journal)
  pages/RoomsPage.vue       salles et bâtiments ; RoomDetailPage : une salle et ses postes
  pages/TasksPage.vue       « Mes tâches » : vérifications affectées, maintenances à faire
  pages/GroupsPage.vue      groupes de droits (grille ressources × actions)
  pages/SettingsPage.vue    défauts du parc (maintenance)
  pages/AuditPage.vue       journal d'audit (permission audit:read) : filtres et page dans l'URL
  components/check|maintenance|room   dialogues des chantiers d'exploitation
  components/audit/         filtres et détail d'une entrée du journal d'audit
  utils/permissions.ts      catalogue des permissions, miroir du backend ; auth.can()
  router/                   routes
  services/machines.ts      appels API typés
  utils/format.ts           libellés et couleurs partagés
  utils/auditLabels.ts      libellés des actions / ressources d'audit, résumé des détails
  utils/auditQuery.ts       état URL du journal ; période (jours locaux → since/until)
```

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

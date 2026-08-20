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
  router/                   routes
  services/machines.ts      appels API typés
  utils/format.ts           libellés et couleurs partagés
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

Les rafraîchissements automatiques n'allument **pas** le spinner : seul le
bouton « Actualiser » le fait. La fiche détail se met en pause tant qu'une
boîte de dialogue est ouverte au-dessus de ses tableaux.

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
  boot/axios.ts          instance axios (baseURL = API_BASE_URL, défaut /api/v1)
  layouts/MainLayout.vue  coquille applicative
  pages/MachinesPage.vue  liste des postes (M1)
  router/                 routes
  services/machines.ts    appels API typés
```

> Squelette M1 : liste des postes. Le dashboard KPI, la vue détail et les
> actions de masse arrivent en M4.

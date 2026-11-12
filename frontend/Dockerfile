# ── Build stage ──────────────────────────────────────────────────────────────
FROM node:22-alpine AS builder
WORKDIR /app

# --ignore-scripts : le postinstall (`quasar prepare`) a besoin des fichiers du
# projet, copiés seulement après — `quasar prepare` est rejoué avant le build.
COPY package.json package-lock.json ./
RUN npm ci --ignore-scripts

COPY . .
RUN npx quasar prepare && npm run build

# ── Production stage ─────────────────────────────────────────────────────────
FROM nginx:1.30-alpine AS runner
# Les correctifs de sécurité d'Alpine arrivent avant la reconstruction de
# l'image officielle (libxslt, relevé par Trivy) : comme le backend, l'image
# applique les mises à jour de sa distribution à chaque construction.
RUN apk upgrade --no-cache
COPY --from=builder /app/dist/spa /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]

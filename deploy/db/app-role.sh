#!/bin/sh
# Rôle applicatif PostgreSQL de Tia'i : propriétaire de la base et de ses
# tables, SANS superutilisateur. Le compte POSTGRES_USER, superutilisateur créé
# par l'image, ne sert plus qu'à l'administration (sauvegardes, ce script).
#
# Pourquoi : un superutilisateur peut lire et écrire n'importe quel fichier du
# conteneur et y lancer un programme (COPY … TO PROGRAM). Une injection SQL ou
# une dépendance compromise côté backend vaudrait alors la main sur le serveur
# de base ; avec ce rôle, elle s'arrête aux tables de Tia'i.
#
# Deux usages, un seul script (idempotent) :
#   - base neuve : monté dans /docker-entrypoint-initdb.d, l'image le lance à
#     la première initialisation du volume ;
#   - base existante : à lancer une fois, avant la montée de version —
#       docker compose exec db sh /docker-entrypoint-initdb.d/10-app-role.sh
#     Il crée le rôle, lui donne la base, le schéma public et toutes les tables
#     (leurs séquences suivent).
#
# Lu par l'image en `source` quand il n'est pas exécutable : ni `exit`, ni
# `set -e` qui survivrait au script.

: "${POSTGRES_APP_USER:=tiai_app}"
if [ -z "${POSTGRES_APP_PASSWORD:-}" ]; then
  echo "app-role.sh : POSTGRES_APP_PASSWORD est vide — rôle applicatif non créé" >&2
  return 1 2>/dev/null || exit 1
fi

psql -v ON_ERROR_STOP=1 \
  --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  -v app_user="$POSTGRES_APP_USER" -v app_password="$POSTGRES_APP_PASSWORD" <<'SQL'
SELECT format('CREATE ROLE %I LOGIN', :'app_user')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'app_user') \gexec
SELECT format(
  'ALTER ROLE %I WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD %L',
  :'app_user', :'app_password'
) \gexec
SELECT format('ALTER DATABASE %I OWNER TO %I', current_database(), :'app_user') \gexec
SELECT format('ALTER SCHEMA public OWNER TO %I', :'app_user') \gexec
SELECT format('ALTER TABLE public.%I OWNER TO %I', tablename, :'app_user')
FROM pg_tables WHERE schemaname = 'public' \gexec
SELECT format('ALTER VIEW public.%I OWNER TO %I', viewname, :'app_user')
FROM pg_views WHERE schemaname = 'public' \gexec
SQL
echo "app-role.sh : rôle « $POSTGRES_APP_USER » prêt (non superutilisateur, propriétaire de $POSTGRES_DB)"

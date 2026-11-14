#!/bin/sh
# Sauvegarde quotidienne de la base Tia'i — tourne dans le conteneur
# `db-backup` (même image que `db`, donc un pg_dump à la bonne version),
# écrit dans deploy/backups/ sur l'hôte via le montage /backups.
#
# Cycle : un dump au démarrage (donc juste après chaque `docker compose up`,
# y compris avant une montée de version), puis un par 24 h. Rétention pilotée
# par BACKUP_KEEP_DAYS — la purge n'a lieu QUE si le dump du jour a réussi :
# une base injoignable ne doit jamais faire disparaître les sauvegardes
# existantes.
set -eu

: "${POSTGRES_USER:?}"
: "${POSTGRES_PASSWORD:?}"
: "${POSTGRES_DB:?}"
KEEP_DAYS="${BACKUP_KEEP_DAYS:-14}"

export PGPASSWORD="$POSTGRES_PASSWORD"

# Lisibles du seul propriétaire (audit S27) : un dump contient les hachés des
# mots de passe, les jetons des postes en empreinte, tout le parc. Le dossier
# lui-même est fermé (créé par Docker, il naît en 755), et les dumps déjà là
# sont resserrés au passage : écrits avant ce réglage, ou à la main par un
# `docker compose exec … pg_dump` qui n'héritait pas de cet umask.
umask 077
chmod 700 /backups 2>/dev/null || true
chmod 600 /backups/tiai-*.dump 2>/dev/null || true
# Un .partial restant vient d'un dump interrompu (conteneur arrêté en cours
# d'écriture) : jamais une sauvegarde valide, et aucun dump ne tourne encore
# ici. Retiré, plutôt que laissé lisible et jamais purgé.
rm -f /backups/.tiai-*.dump.partial

while :; do
  stamp="$(date -u +%Y%m%d-%H%M%S)"
  tmp="/backups/.tiai-${stamp}.dump.partial"
  out="/backups/tiai-${stamp}.dump"
  # Format custom (-Fc) : compressé, et pg_restore sait en extraire une table
  # seule si besoin. Écrit d'abord en .partial puis renommé : un dump
  # interrompu ne peut jamais être pris pour une sauvegarde valide.
  if pg_dump -h db -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc -f "$tmp"; then
    mv "$tmp" "$out"
    echo "sauvegarde OK : $(basename "$out") ($(du -h "$out" | cut -f1))"
    find /backups -name 'tiai-*.dump' -mtime +"$KEEP_DAYS" -delete
  else
    rm -f "$tmp"
    echo "ECHEC de la sauvegarde $stamp — les dumps existants sont conservés" >&2
  fi
  sleep 86400
done

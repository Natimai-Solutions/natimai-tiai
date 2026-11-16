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
# Le chmod échoue là où root du conteneur n'est pas propriétaire du dossier sur
# l'hôte (Docker en userns-remap ou sans root, NFS en root squash). Dit dans le
# journal plutôt que tu : DEPLOYMENT.md annonce un dossier en 700, et c'est
# alors le `chmod 700 backups` fait sur l'hôte qui le ferme. Rien n'est dit si
# le dossier est déjà en 700.
if ! chmod 700 /backups 2>/dev/null \
  && [ "$(stat -c %a /backups 2>/dev/null)" != 700 ]; then
  echo "ATTENTION : /backups n'a pas pu être fermé (chmod 700 refusé) — sur l'hôte : chmod 700 deploy/backups" >&2
fi
chmod 600 /backups/tiai-*.dump 2>/dev/null || true

while :; do
  # Un .partial restant vient d'un dump interrompu (conteneur arrêté en cours
  # d'écriture) : jamais une sauvegarde valide. Retiré, plutôt que laissé
  # lisible et jamais purgé — mais seulement au-delà d'une heure sans
  # écriture : plus récent, ce peut être le dump en cours d'une autre instance
  # qui partage le dossier. `|| true` : un dossier en lecture seule ne doit
  # pas arrêter le script (set -e), donc relancer le conteneur en boucle.
  find /backups -maxdepth 1 -name '.tiai-*.dump.partial' -mmin +60 -delete 2>/dev/null || true

  stamp="$(date -u +%Y%m%d-%H%M%S)"
  tmp="/backups/.tiai-${stamp}.dump.partial"
  out="/backups/tiai-${stamp}.dump"
  # Format custom (-Fc) : compressé, et pg_restore sait en extraire une table
  # seule si besoin. Écrit d'abord en .partial puis renommé : un dump
  # interrompu ne peut jamais être pris pour une sauvegarde valide.
  if pg_dump -h db -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc -f "$tmp"; then
    mv "$tmp" "$out"
    echo "sauvegarde OK : $(basename "$out") ($(du -h "$out" | cut -f1))"
    # Une purge qui échoue (fichier non supprimable) est signalée sans arrêter
    # le script : sous set -e, le conteneur redémarrerait en boucle, avec un
    # dump de plus à chaque tour.
    # Seuls les dumps de ce script, à leur nom exact (tiai-AAAAMMJJ-HHMMSS.dump)
    # et à la racine du dossier : un dump manuel (tiai-avant-operation.dump,
    # cf. DEPLOYMENT.md) ou rangé dans un sous-dossier n'est jamais purgé.
    find /backups -maxdepth 1 -type f \
      -name 'tiai-[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]-[0-9][0-9][0-9][0-9][0-9][0-9].dump' \
      -mtime +"$KEEP_DAYS" -delete \
      || echo "ATTENTION : purge des dumps de plus de $KEEP_DAYS jours incomplète" >&2
  else
    rm -f "$tmp"
    echo "ECHEC de la sauvegarde $stamp — les dumps existants sont conservés" >&2
  fi
  sleep 86400
done

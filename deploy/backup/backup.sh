#!/bin/sh
# Sauvegarde quotidienne de la base Tia'i — tourne dans le conteneur
# `db-backup` (image de `db` plus `age`, cf. Dockerfile ; donc un pg_dump à la
# bonne version), écrit dans deploy/backups/ sur l'hôte via le montage /backups.
#
# Cycle : un dump au démarrage (donc juste après chaque `docker compose up`,
# y compris avant une montée de version), puis un par 24 h. Rétention pilotée
# par BACKUP_KEEP_DAYS — la purge n'a lieu QUE si le dump du jour a réussi :
# une base injoignable ne doit jamais faire disparaître les sauvegardes
# existantes.
#
# Chiffrement optionnel (audit S27) : si BACKUP_ENCRYPT_RECIPIENT porte une ou
# plusieurs clés publiques age (age1…, séparées par des espaces), chaque dump
# est chiffré pour elles AVANT d'arriver sur le disque (tiai-….dump.age) ; la
# clé privée n'est jamais sur le serveur. Vide : dumps en clair, comme avant.
#
# Pièces jointes du journal (C11) : après chaque dump réussi, les fichiers du
# volume `attachments` (monté en lecture seule sur /attachments) sont copiés
# dans attachments/ à côté des dumps — incrémental : un fichier par empreinte
# SHA-256, immuable, copié une fois puis seulement « touché » à chaque tour
# (chiffré en <sha>.age comme les dumps si BACKUP_ENCRYPT_RECIPIENT est posé).
# Une copie que le volume ne contient plus n'est plus touchée, et part après
# BACKUP_KEEP_DAYS jours : un dump de 14 jours retrouve ses photos. Volume
# vide : rien de purgé tant que la base référence des pièces jointes (volume
# perdu, ou base restaurée avant « Remettre les pièces jointes ») ou ne peut
# pas le dire ; si elle n'en référence aucune (la dernière a été supprimée),
# purge normale — une photo supprimée ne reste pas indéfiniment dans la copie.
set -eu

: "${POSTGRES_USER:?}"
: "${POSTGRES_PASSWORD:?}"
: "${POSTGRES_DB:?}"
KEEP_DAYS="${BACKUP_KEEP_DAYS:-14}"
RECIPIENTS="${BACKUP_ENCRYPT_RECIPIENT:-}"
# Le montage du compose. Variable pour les tests seulement
# (backend/tests/test_backup_script.py) : le compose ne la pose pas.
DIR="${BACKUP_DIR:-/backups}"
# Le volume des pièces jointes (compose : attachments:/attachments:ro), et leur
# copie. Variable pour les tests seulement, comme BACKUP_DIR.
ATTACHMENTS="${BACKUP_ATTACHMENTS_DIR:-/attachments}"
COPY="$DIR/attachments"

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
if ! chmod 700 "$DIR" 2>/dev/null \
  && [ "$(stat -c %a "$DIR" 2>/dev/null)" != 700 ]; then
  echo "ATTENTION : $DIR n'a pas pu être fermé (chmod 700 refusé) — sur l'hôte : chmod 700 deploy/backups" >&2
fi
chmod 600 "$DIR"/tiai-*.dump "$DIR"/tiai-*.dump.age 2>/dev/null || true

# Chiffrement demandé mais impossible : arrêt, code 1, AVANT tout dump. Jamais
# de repli en clair (la configuration dit le contraire), et pas de purge : les
# sauvegardes existantes restent. Le conteneur redémarre en boucle
# (« Restarting » dans `docker compose ps`) et répète la raison au journal.
refuse() {
  echo "ECHEC : $1 — aucun dump écrit, les sauvegardes existantes sont conservées" >&2
  exit 1
}
AGE_ARGS=""
if [ -n "$RECIPIENTS" ]; then
  set -f # pas de développement de chemins sur la valeur, avant contrôle
  for r in $RECIPIENTS; do
    case "$r" in
      AGE-SECRET-KEY-*)
        refuse "BACKUP_ENCRYPT_RECIPIENT contient une clé PRIVÉE age — elle n'a rien à faire sur le serveur : la retirer du .env, n'y mettre que la clé publique (age1…), et tenir la clé privée pour compromise" ;;
      age1*[!a-z0-9]* | age1) refuse "BACKUP_ENCRYPT_RECIPIENT : « $r » n'est pas une clé publique age (age1…)" ;;
      age1*) AGE_ARGS="$AGE_ARGS -r $r" ;;
      *) refuse "BACKUP_ENCRYPT_RECIPIENT : « $r » n'est pas une clé publique age (age1…)" ;;
    esac
  done
  set +f
  command -v age >/dev/null 2>&1 \
    || refuse "BACKUP_ENCRYPT_RECIPIENT est posé mais age est introuvable dans le conteneur — reconstruire l'image : docker compose build --pull db-backup && docker compose up -d --force-recreate db-backup"
  # Une clé à la somme de contrôle fausse passe le contrôle ci-dessus : c'est
  # age qui la refuse (son message suit au journal).
  # shellcheck disable=SC2086 # AGE_ARGS : des mots age1[a-z0-9]*, contrôlés
  printf 'tiai' | age $AGE_ARGS >/dev/null \
    || refuse "BACKUP_ENCRYPT_RECIPIENT refusé par age"
fi

# Écrit le dump dans le fichier $1 : en clair, ou chiffré au fil de l'eau —
# pg_dump écrit dans un tube, age chiffre, aucun octet en clair ne touche le
# disque. Réussit seulement si pg_dump ET age ont réussi.
#
# Le code de sortie d'un tube est celui de sa dernière commande (age), et
# `pipefail` n'est pas POSIX : celui de pg_dump revient par le descripteur 3,
# lu par la substitution de commande. Le dump n'est tenu pour bon que si ce
# code a été lu ET vaut 0 — rien de lu (sous-shell tué) vaut échec. Pas de
# fichier témoin : celui d'avant notait l'échec dans /tmp, et là où il ne
# pouvait pas être écrit (conteneur en lecture seule, disque de Docker plein —
# l'événement même qui coupe le dump), un dump tronqué passait pour bon.
dump() {
  if [ -z "$AGE_ARGS" ]; then
    pg_dump -h db -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc -f "$1"
    return
  fi
  age_status=0
  # shellcheck disable=SC2086
  pg_status="$(
    exec 3>&1
    {
      pg_dump -h db -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc 3>&-
      echo "$?" >&3
    } | age $AGE_ARGS -o "$1" >/dev/null 3>&-
  )" || age_status=1
  [ "$pg_status" = 0 ] && [ "$age_status" = 0 ]
}

# Le nombre de pièces jointes que la base référence, sur la sortie : échoue
# (code 1) si elle ne peut pas le dire — injoignable en dix secondes, table
# absente, réponse qui n'est pas un nombre. psql est dans l'image (celle de db).
attachment_rows() {
  rows="$(PGCONNECT_TIMEOUT=10 psql -h db -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
    -X -A -t -q -v ON_ERROR_STOP=1 \
    -c 'SELECT count(*) FROM intervention_attachments' 2>/dev/null)" || return 1
  case "$rows" in '' | *[!0-9]*) return 1 ;; esac
  echo "$rows"
}

# Copie incrémentale des pièces jointes (C11). Renvoie 1 si un fichier n'a pas
# pu être copié : la copie n'est alors pas purgée (même règle que les dumps).
# Volume absent (compose d'avant C11) : une ligne au journal, rien d'autre.
# Chaque fichier est écrit en <sha>.tmp (ou <sha>.age.tmp) puis renommé : une
# copie interrompue n'est jamais prise pour un fichier complet.
copy_attachments() {
  if [ ! -d "$ATTACHMENTS" ]; then
    echo "pièces jointes : $ATTACHMENTS absent (volume non monté) — non copiées"
    return 0
  fi
  if ! mkdir -p "$COPY"; then
    echo "ECHEC : dossier $COPY impossible à créer — pièces jointes non copiées" >&2
    return 1
  fi
  chmod 700 "$COPY" 2>/dev/null || true
  chmod 600 "$COPY"/* 2>/dev/null || true
  failed=0
  copied=0
  kept=0
  seen=0
  for f in "$ATTACHMENTS"/*; do
    [ -f "$f" ] || continue
    sha="$(basename "$f")"
    case "$sha" in *[!0-9a-f]*) continue ;; esac
    [ "${#sha}" -eq 64 ] || continue
    seen=$((seen + 1))
    if [ -n "$AGE_ARGS" ]; then
      if [ -e "$COPY/$sha.age" ]; then
        touch "$COPY/$sha.age" || failed=1
        # Une copie en clair restée d'avant le chiffrement : retirée.
        rm -f "$COPY/$sha" || failed=1
        kept=$((kept + 1))
        continue
      fi
      # shellcheck disable=SC2086 # AGE_ARGS : des mots age1[a-z0-9]*, contrôlés
      if age $AGE_ARGS -o "$COPY/$sha.age.tmp" "$f" \
        && mv "$COPY/$sha.age.tmp" "$COPY/$sha.age"; then
        chmod 600 "$COPY/$sha.age" 2>/dev/null || true
        # Passage au chiffrement : la copie en clair part une fois la copie
        # chiffrée écrite, pas avant.
        rm -f "$COPY/$sha" || failed=1
        copied=$((copied + 1))
      else
        rm -f "$COPY/$sha.age.tmp"
        failed=1
      fi
    else
      if [ -e "$COPY/$sha" ]; then
        touch "$COPY/$sha" || failed=1
        kept=$((kept + 1))
        continue
      fi
      if [ -e "$COPY/$sha.age" ]; then
        touch "$COPY/$sha.age" || failed=1
        kept=$((kept + 1))
        continue
      fi
      if cp "$f" "$COPY/$sha.tmp" && mv "$COPY/$sha.tmp" "$COPY/$sha"; then
        chmod 600 "$COPY/$sha" 2>/dev/null || true
        copied=$((copied + 1))
      else
        rm -f "$COPY/$sha.tmp"
        failed=1
      fi
    fi
  done
  if [ "$failed" != 0 ]; then
    echo "ECHEC de la copie des pièces jointes ($copied copiée(s)) — copie non purgée" >&2
    return 1
  fi
  # Volume vide : la base dit si c'est normal. Elle référence encore des
  # pièces jointes (volume perdu, base restaurée avant « Remettre les pièces
  # jointes ») : pas de purge, la copie est tout ce qui reste des fichiers.
  # Elle ne peut pas répondre (table pas encore créée par les migrations,
  # base injoignable) : pas de purge non plus, au tour suivant de trancher.
  # Elle n'en référence aucune (la dernière a été supprimée) : purge
  # normale, sans quoi les copies des photos supprimées — données
  # personnelles, EXIF compris — resteraient indéfiniment. Sur un serveur
  # reconstruit, la copie hors site se dépose donc à côté, dans un dossier
  # que ce script ne purge jamais (DEPLOYMENT.md) : la base neuve n'en
  # référence aucune.
  if [ "$seen" -eq 0 ]; then
    if ! refs="$(attachment_rows)"; then
      echo "pièces jointes : volume vide et base muette (table absente ou injoignable) — copie non purgée"
      return 0
    fi
    if [ "$refs" -gt 0 ]; then
      echo "pièces jointes : volume vide, $refs référencée(s) en base — copie conservée, non purgée"
      return 0
    fi
  fi
  # Ce que le volume ne contient plus n'est plus touché : parti après
  # KEEP_DAYS jours. Les .tmp d'une copie interrompue aussi.
  find "$COPY" -maxdepth 1 -type f -mtime +"$KEEP_DAYS" -exec rm -- {} + \
    || echo "ATTENTION : purge des pièces jointes de plus de $KEEP_DAYS jours incomplète" >&2
  echo "pièces jointes : $copied copiée(s), $kept déjà présente(s)"
  return 0
}

if [ -n "$AGE_ARGS" ]; then
  ext=dump.age
  how=", chiffrée"
else
  ext=dump
  how=""
fi

while :; do
  # Un .partial restant vient d'un dump interrompu (conteneur arrêté en cours
  # d'écriture) : jamais une sauvegarde valide. Retiré, plutôt que laissé
  # lisible et jamais purgé — mais seulement au-delà d'une heure sans
  # écriture : plus récent, ce peut être le dump en cours d'une autre instance
  # qui partage le dossier. `|| true` : un dossier en lecture seule ne doit
  # pas arrêter le script (set -e), donc relancer le conteneur en boucle.
  # `-exec rm`, pas `-delete` : une option que busybox find n'a pas dans
  # toutes ses compilations (celle d'Ubuntu, par exemple).
  find "$DIR" -maxdepth 1 -type f -name '.tiai-*.partial' -mmin +60 \
    -exec rm -- {} + 2>/dev/null || true

  stamp="$(date -u +%Y%m%d-%H%M%S)"
  tmp="$DIR/.tiai-${stamp}.${ext}.partial"
  out="$DIR/tiai-${stamp}.${ext}"
  # Format custom (-Fc) : compressé, et pg_restore sait en extraire une table
  # seule si besoin. Écrit d'abord en .partial puis renommé : un dump
  # interrompu ne peut jamais être pris pour une sauvegarde valide.
  if dump "$tmp"; then
    mv "$tmp" "$out"
    # Une purge qui échoue (fichier non supprimable) est signalée sans arrêter
    # le script : sous set -e, le conteneur redémarrerait en boucle, avec un
    # dump de plus à chaque tour.
    # Seuls les dumps de ce script, à leur nom exact
    # (tiai-AAAAMMJJ-HHMMSS.dump, ou .dump.age chiffré) et à la racine du
    # dossier : un dump manuel (tiai-avant-operation.dump, cf. DEPLOYMENT.md)
    # ou rangé dans un sous-dossier n'est jamais purgé. Les deux formes, quel
    # que soit le réglage du jour : les dumps en clair d'avant le chiffrement
    # partent à leur échéance. Un `find` par forme : pas de \( -o \).
    for daily in dump dump.age; do
      find "$DIR" -maxdepth 1 -type f \
        -name "tiai-[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]-[0-9][0-9][0-9][0-9][0-9][0-9].$daily" \
        -mtime +"$KEEP_DAYS" -exec rm -- {} + \
        || echo "ATTENTION : purge des dumps de plus de $KEEP_DAYS jours incomplète" >&2
    done
    # Après un dump réussi seulement. Un échec est dit au journal, sans
    # arrêter le script : le conteneur redémarrerait en boucle, avec un dump
    # de plus à chaque tour.
    copy_attachments || true
    # En dernier : la ligne qui clôt le tour (les tests l'attendent).
    echo "sauvegarde OK : $(basename "$out") ($(du -h "$out" | cut -f1)$how)"
  else
    rm -f "$tmp"
    echo "ECHEC de la sauvegarde $stamp — les dumps existants sont conservés" >&2
  fi
  sleep 86400
done

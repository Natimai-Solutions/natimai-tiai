# Image du service db-backup : celle du service `db` — même tag, donc un
# pg_dump de la même version que le serveur — plus `age`, l'outil du
# chiffrement optionnel des dumps (BACKUP_ENCRYPT_RECIPIENT, cf. backup.sh et
# DEPLOYMENT.md § « Sauvegardes et restauration »).
#
# Installé ici, une fois, depuis le dépôt signé d'Alpine — pas au démarrage du
# conteneur : la sauvegarde ne doit dépendre ni du réseau ni d'un miroir le
# jour où elle tourne. Construite par `docker compose up` (ou
# `docker compose build --pull db-backup`, qui rafraîchit aussi la base
# postgres:16-alpine, cf. DEPLOYMENT.md § « Mettre à jour le serveur »).
# Le script, lui, reste monté depuis l'hôte (backup.sh), comme avant.
FROM postgres:16-alpine
RUN apk add --no-cache age && age --version

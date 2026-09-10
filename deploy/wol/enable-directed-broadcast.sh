#!/bin/sh
# Autorise l'hôte Docker (Linux) à relayer vers le LAN le paquet magique
# Wake-on-LAN émis par le conteneur `backend` — cf. DEPLOYMENT.md
# § « Réveil des postes (Wake-on-LAN) », point 3.
#
# Pourquoi : le backend tourne sur un pont Docker (br-xxxx). Son datagramme,
# adressé à la diffusion du sous-réseau du poste (192.168.1.255 par exemple),
# arrive à l'hôte par ce pont — et Linux n'achemine pas une diffusion dirigée
# d'une interface vers une autre par défaut (RFC 2644). Le noyau ne la relaie
# que si `bc_forwarding` vaut 1 à la fois sur `all` ET sur l'interface PAR
# LAQUELLE LE PAQUET ENTRE, c'est-à-dire le pont Docker — pas l'interface LAN,
# qui n'est que la sortie. Un réglage posé sur la seule carte LAN ne fait rien.
#
# Ce script :
#   1. persiste `all` et `default` dans /etc/sysctl.d/ (survit au redémarrage ;
#      `default` fait hériter le réglage aux ponts que Docker créera ensuite,
#      y compris à la recréation du réseau par `docker compose down/up`) ;
#   2. l'applique aux ponts Docker déjà existants, créés avant ce `default`.
#
# Usage : sudo sh deploy/wol/enable-directed-broadcast.sh
# Idempotent — peut être relancé sans risque.
set -eu

if [ "$(id -u)" -ne 0 ]; then
    echo "Ce script modifie des sysctl : le lancer avec sudo." >&2
    exit 1
fi
if [ ! -d /proc/sys/net/ipv4/conf ]; then
    echo "Pas de pile IPv4 Linux ici : ce réglage ne s'applique qu'à un hôte Docker Linux" >&2
    echo "(sur Docker Desktop Windows/macOS, voir DEPLOYMENT.md — le relais n'est pas possible)." >&2
    exit 1
fi

CONF=/etc/sysctl.d/99-tiai-wol.conf
cat > "$CONF" <<'SYSCTL'
# Tia'i — relais des diffusions dirigées (Wake-on-LAN émis depuis le conteneur
# backend vers le LAN). Le noyau exige `all` ET l'interface d'entrée (le pont
# Docker) ; `default` couvre les ponts créés après ce réglage.
net.ipv4.conf.all.bc_forwarding = 1
net.ipv4.conf.default.bc_forwarding = 1
SYSCTL
sysctl -q -p "$CONF"

# Les ponts déjà présents ont hérité de l'ancien `default` (0) à leur création.
applied=""
for f in /proc/sys/net/ipv4/conf/docker0/bc_forwarding \
         /proc/sys/net/ipv4/conf/br-*/bc_forwarding; do
    [ -e "$f" ] || continue
    echo 1 > "$f"
    applied="$applied $(basename "$(dirname "$f")")"
done

echo "bc_forwarding = 1 sur all, default${applied:+ et sur les ponts Docker :$applied}."
echo "Persisté dans $CONF."
echo
echo "Vérifier : sudo tcpdump -ni <interface LAN> udp port 9, pendant un clic sur « Réveiller »."

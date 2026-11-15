# Tia'i v1.2.1

Cette version corrige les écarts trouvés par les deux passes de vérification de l'audit 2026-11 (13 et 14 novembre 2026). Elle contient une régression de la v1.2.0 corrigée (fichiers de paquet supprimés pendant un dépôt), des constats nouveaux sur l'agent, et des compléments à la plupart des tâches de l'audit. Le détail est dans `dev/plan-audit-2026-11.md` §6.1 et §6.3.

Elle contient quatre migrations de base (`0032` à `0035`).

---

## À faire avant de mettre à jour

### Serveur

1. **Suivre la procédure de `DEPLOYMENT.md` § « Mettre à jour le serveur », qui a changé.** Une version, ce sont les images *et* les fichiers de `deploy/` : le `Caddyfile` et `backup/backup.sh` sont lus sur l'hôte, pas dans les images. Changer `TIAI_VERSION` puis `docker compose pull` et `up -d` ne suffit donc pas. Il faut aussi :
   - mettre les fichiers de `deploy/` à la version v1.2.1 (`git checkout v1.2.1`, ou l'archive de la release) ;
   - recréer les deux services qui les lisent : `docker compose up -d --force-recreate caddy db-backup` ;
   - poser les droits, y compris sur un serveur déjà installé : `chmod 600 .env` et `chmod 700 backups`.

   Sans cela, la limite de taille de Caddy et le durcissement des sauvegardes de cette version ne s'appliquent pas.
2. **Faire un dump de la base** avant la mise à jour (étape 1 de la même procédure). La commande documentée écrit désormais un dump lisible par son seul propriétaire.
3. **Paramètres e-mail.** Si la console a changé le serveur SMTP (hôte, port, sécurité, vérification du certificat) ou le domaine ou l'URL Mailgun, alors que le mot de passe ou la clé viennent du `.env`, ce secret n'est plus envoyé : il était tapé pour le serveur du `.env`, pas pour celui de la console. La carte **Paramètres → Envoi des e-mails** l'indique (« il manque le mot de passe SMTP »). Y ressaisir le secret, puis envoyer un e-mail de test.
4. **Paquets de fichiers déposés sous la v1.2.0.** Un défaut de la v1.2.0 pouvait supprimer du stockage un fichier tout juste déposé. Ouvrir la page **Paquets** : un paquet concerné affiche le problème « Fichier absent du stockage du serveur » et ne peut plus être déployé. Déposer de nouveau le fichier le rétablit.
5. **`WOL_ALLOWED_NETWORKS`.** Une entrée qui n'est pas un réseau IPv4 lisible empêche désormais le backend de démarrer, en la nommant. Vérifier la valeur avant la mise à jour si elle est renseignée.
6. **`PASSWORD_RESET_EXPIRE_MINUTES`** est borné de 5 à 10 080 minutes ; une valeur hors bornes empêche le démarrage.

### Agent : mettre à jour le parc

Les correctifs de l'agent n'agissent qu'après la mise à jour par GPO.

- **Script GPO.** `Install-TiaiAgent.ps1` n'est pas un fichier de la release : le recopier à la main sur le partage. Il accepte désormais `-AllowInsecureHttp` (`true` ou `false`), et le MSI la propriété `ALLOWINSECUREHTTP` (`1` ou `0`).
- **Ordre à respecter.** Copier le nouveau script **avant** d'ajouter `-AllowInsecureHttp` aux arguments de la GPO. L'ancien script refuse ce paramètre inconnu sans rien journaliser, et plus aucun poste n'est installé ni mis à jour.
- **Onglets ouverts.** Les onglets de la console ouverts avant cette mise à jour doivent être rechargés à la main, une fois. Le rechargement automatique n'existe qu'à partir de cette version.

---

## Changements de comportement à annoncer aux utilisateurs

- **Verrouillage de compte.**
  - Un échec de connexion de plus de 15 minutes (`LOGIN_LOCKOUT_MINUTES`) ne compte plus : quelques fautes de frappe étalées dans la semaine ne verrouillent plus.
  - Dès que 10 adresses distinctes (`LOGIN_SIEGE_ADDRESSES`) ont échoué sur un compte pendant un verrou, seules ses adresses habituelles restent admises : celles qui l'ont ouvert dans les 30 derniers jours (`LOGIN_KNOWN_ADDRESS_DAYS`), ou sur lesquelles une session est restée en usage.
  - Ces adresses sont gardées en base : un redémarrage du serveur ne lève plus un verrou et n'oublie plus les postes habituels.
  - Un titulaire refusé depuis une adresse jamais vue, pendant de tels essais, passe par « Mot de passe oublié » depuis ce poste : le lien utilisé rend l'adresse habituelle.
  - Un changement de mot de passe efface les adresses habituelles de l'ancien, sauf celle d'où le nouveau vient d'être choisi.
- **Mot de passe oublié.** Une nouvelle demande n'annule plus le lien déjà reçu. Au plus un courriel par compte toutes les 5 minutes et 3 liens valides à la fois (`PASSWORD_RESET_COOLDOWN_MINUTES`, `PASSWORD_RESET_MAX_LIVE_LINKS`). Utiliser l'un des liens annule les autres.
- **Paramètres e-mail.**
  - Remettre le mot de passe SMTP ou la clé Mailgun à la valeur du `.env` est refusé tant que la console pointe vers un autre serveur que celui du `.env`.
  - Un secret devenu illisible (clé `SECRET_KEY` changée) doit être ressaisi avant de changer de serveur.
- **Déploiement logiciel.**
  - Retirer un paquet annule aussitôt ses installations encore en attente. Celles déjà transmises aux postes vont à leur terme ; les désinstallations ne sont pas touchées.
  - Une désinstallation n'est refusée que pour ce que l'agent refuserait. L'absence d'étape d'installation ne la bloque plus ; `msiexec /x {code produit}` reste accepté sans signature.
  - Un paquet non signé de plus de 8 Gio au total est refusé à la mise en file, avec la consigne de le signer (`PACKAGE_METHOD_A_MAX_GB`, à garder égal à la valeur `DeployMethodAMaxGB` des postes).
  - Déposer un fichier dont le nom ne diffère que par la casse d'un fichier existant (`SETUP.EXE` sur `setup.exe`) le remplace. Les postes refusaient un paquet contenant les deux.
  - Refusés en plus à côté de l'exécutable en méthode A : `.bpl`, `.pyd`, `.xll`, `.node`, `.rll`, `.wsc`, `.sct`.
  - Un nom, une version, un fichier à lancer ou des arguments contenant un caractère invisible ou qui réordonne l'affichage sont refusés. Le script de signature refuse le même ensemble.
  - La console lit la taille maximale d'un fichier auprès du serveur (`PACKAGE_MAX_BYTES`) au lieu d'une limite fixe de 2 Gio.
- **Maintenance.**
  - Le responsable de maintenance d'un poste ou d'une salle doit pouvoir lire et enregistrer les maintenances, et voir le poste ou la salle. Le responsable par défaut doit le pouvoir sur tout le parc. Code `maintenance.owner.out_of_reach`, message : « Ce compte ne peut pas suivre cette maintenance (droits de maintenance ou périmètre insuffisants) : choisissez quelqu’un dont le périmètre couvre ces postes ».
  - Les listes de choix d'un responsable ne proposent plus que les comptes que le serveur acceptera.
  - Un responsable qui n'atteint plus un poste (droits retirés, poste déplacé hors de son périmètre) est ignoré comme un compte désactivé : le niveau suivant s'applique, et il ne reçoit plus de rappel pour ce poste. Rien n'est modifié en base. Dans **Paramètres**, un responsable par défaut dans ce cas apparaît vide : en choisir un autre.
  - Une vérification ne peut plus être close à une date future, et une ligne du journal datée dans le futur ne peut plus devenir une maintenance.
- **Salles en mode annuaire.**
  - La resynchronisation n'adopte une salle créée à la main que pour l'OU déclarée par la majorité des postes de ce nom. Les postes révoqués ou à vérifier ne votent pas.
  - Faute de majorité, les postes restent où ils sont. Le résultat de la resynchronisation les compte à part et nomme les salles concernées.
  - Un poste dont l'OU ne contient pas le DN n'est plus rangé par la resynchronisation.
- **Réveil (Wake-on-LAN).**
  - Sans `WOL_ALLOWED_NETWORKS`, le réveil direct ne vise que les plages RFC 1918 (10/8, 172.16/12, 192.168/16). Renseignée, la liste remplace ces plages. Le sous-réseau déduit de l'adresse et du masque d'un poste doit tenir entièrement dans un réseau autorisé ; le message de refus dit lequel de ces cas s'applique.
  - Un agent qui ne déclare pas de version lisible ne sert plus de relais, et la console ne compte que les relais habilités.
  - Un relais qui a laissé un réveil sans réponse ne le reçoit plus tant qu'un autre relais peut le prendre.
- **Fréquence des contacts.** Un poste est limité à 12 contacts par minute (30 auparavant ; `AGENT_HEARTBEAT_MAX_PER_MINUTE`). L'agent en fait un par minute par défaut.
- **Catalogue logiciel.**
  - Un poste ne peut ajouter que 2 000 logiciels nouveaux au catalogue par 24 heures (`SOFTWARE_NEW_ENTRIES_PER_DAY`), et tout le parc 50 000 (`SOFTWARE_NEW_ENTRIES_PER_DAY_FLEET`). Les logiciels déjà connus ne comptent pas.
  - Un relevé coupé par ces budgets est signalé sur la fiche du poste (« Relevé partiel »). Le serveur le redemande à l'agent une heure plus tard au plus tôt, quand les budgets ont de nouveau de la place. Un agent antérieur à la v1.2.1 le complète à son prochain redémarrage ou changement d'inventaire.
- **Console.**
  - Liste des postes : les colonnes d'inventaire (domaine, emplacement, bâtiment, IP, OS, version de l'agent, modèle, disque) sont de nouveau affichées par défaut ; seule « Utilisation » reste à ajouter depuis « Colonnes ». La colonne « Agent » s'appelle « Version de l'agent ».
  - Liste des postes : la sélection est vidée dès que la liste change (filtre, page, lien « Postes » du menu, retour).
  - Fiche : la navigation précédent/suivant ne répète plus un poste et n'affiche plus de rang ou de voisins faux.
  - Après une mise à jour du serveur, un onglet ouvert sous cette version se recharge une fois de lui-même. Hors connexion, la console reste affichée et propose de réessayer.

---

## Agent

- Une commande dont l'identifiant n'est pas un UUID est refusée. Cet identifiant nommait un fichier de la file locale : un serveur compromis pouvait écrire hors du dossier.
- Le manifeste d'un paquet est refusé s'il contient une clé en double, inconnue, ou écrite avec une autre casse ou un caractère Unicode voisin (« inſtall »). L'agent exécute donc exactement ce que le script de signature a montré.
- En méthode A, un manifeste qui annonce plus de 8 Gio est refusé avant tout téléchargement. La valeur de registre `DeployMethodAMaxGB` (`REG_DWORD`, en Gio, sous `HKLM\SOFTWARE\Tiai`) la remplace ; une valeur inutilisable est signalée dans le journal.
- En méthode A, un refus qu'une relance ne lèverait pas supprime le dossier du paquet, et les dossiers de paquet non modifiés depuis 7 jours sont retirés.
- Un jeton refusé par le serveur et resté sur le disque n'est plus relu en boucle : l'agent se réenrôle.
- Un verdict de commande n'est retiré de la file locale que si le serveur le refuse définitivement (422). Une réponse d'erreur d'un proxy ne vide plus la file.
- L'agent renvoie son inventaire logiciel quand le serveur le lui demande.
- Un agent configuré en `http://` sans `AllowInsecureHTTP` ne s'arrête pas : le service reste lancé, ne contacte pas le serveur et l'écrit dans son journal toutes les 1 à 15 minutes.

---

## Nouvelles variables d'environnement

Toutes facultatives : leur valeur par défaut est celle décrite plus haut.

| Variable | Défaut | Rôle |
|---|---|---|
| `LOGIN_SIEGE_ADDRESSES` | `10` | Nombre d'adresses en échec à partir duquel un verrou n'admet plus que les adresses habituelles |
| `LOGIN_KNOWN_ADDRESS_DAYS` | `30` | Durée pendant laquelle une adresse qui a ouvert un compte reste habituelle |
| `PASSWORD_RESET_COOLDOWN_MINUTES` | `5` | Délai minimal entre deux courriels de réinitialisation d'un compte |
| `PASSWORD_RESET_MAX_LIVE_LINKS` | `3` | Liens de réinitialisation valides à la fois pour un compte |
| `AGENT_HEARTBEAT_MAX_PER_MINUTE` | `12` | Heartbeats acceptés par poste et par minute |
| `SOFTWARE_NEW_ENTRIES_PER_DAY` | `2000` | Nouveaux logiciels qu'un poste peut ajouter au catalogue par 24 h |
| `SOFTWARE_NEW_ENTRIES_PER_DAY_FLEET` | `50000` | Nouveaux logiciels que tout le parc peut ajouter au catalogue par 24 h |
| `PACKAGE_METHOD_A_MAX_GB` | `8` | Taille totale, en Gio, d'un paquet non signé ; à garder égale à `DeployMethodAMaxGB` |

Clé de registre de l'agent : `DeployMethodAMaxGB` (`REG_DWORD`), voir plus haut.

## Écarts connus

- Les sauvegardes ne sont toujours pas chiffrées sur le serveur : la copie hors serveur doit l'être (`DEPLOYMENT.md` § « Sauvegardes et restauration »).
- Les autres limites acceptées sont listées dans `dev/plan-audit-2026-11.md` §6.4.

## Migrations

| Migration | Contenu |
|---|---|
| `0032` | Date du dernier échec de connexion (`users.last_failed_login_at`) ; compteurs d'échecs remis à zéro |
| `0033` | Relais libérés d'un réveil (`commands.released_relay_ids`) |
| `0034` | Adresses de connexion par compte (`user_login_addresses`), initialisées avec celles des sessions ouvertes |
| `0035` | Relevé logiciel partiel (`machines.software_truncated_at`) |

Le backend applique les migrations à son démarrage.

# Tia'i v1.2.1

Cette version corrige les écarts trouvés par la seconde passe de vérification de l'audit 2026-11 (13 novembre 2026). Elle contient une régression corrigée (fichiers de paquet supprimés pendant un dépôt), deux constats nouveaux sur l'agent, et des compléments à 25 tâches de l'audit. Le détail est dans `dev/plan-audit-2026-11.md` §6.1.

Elle contient deux migrations de base (`0032` et `0033`).

---

## À faire avant de mettre à jour

### Serveur

1. **Faire un dump de la base**, comme décrit dans `DEPLOYMENT.md` § « Mettre à jour le serveur ». La commande documentée écrit désormais le dump en lecture seule pour son propriétaire.
2. **Paramètres e-mail.** Si la console a changé le serveur SMTP (hôte, port, sécurité, vérification du certificat) ou le domaine ou l'URL Mailgun, alors que le mot de passe ou la clé viennent du `.env`, ce secret n'est plus envoyé : il était tapé pour le serveur du `.env`, pas pour celui de la console. Ressaisir le secret dans **Paramètres → Envoi des e-mails**, puis envoyer un e-mail de test.

### Agent : mettre à jour le parc

Les correctifs de l'agent (file locale, jeton refusé, manifeste strict, extensions refusées) n'agissent qu'après la mise à jour par GPO. Le script `Install-TiaiAgent.ps1` accepte désormais `-AllowInsecureHttp` et le MSI la propriété `ALLOWINSECUREHTTP` : un parc en `http://` peut recevoir l'option avec l'installation.

---

## Changements de comportement à annoncer aux utilisateurs

- **Verrouillage de compte.**
  - Un échec de connexion de plus de 15 minutes (`LOGIN_LOCKOUT_MINUTES`) ne compte plus : quelques fautes de frappe étalées dans la semaine ne verrouillent plus.
  - Si les essais viennent de 10 adresses ou plus pendant un verrou (`LOGIN_SIEGE_ADDRESSES`), seules les adresses qui ont ouvert ce compte dans les 30 derniers jours (`LOGIN_KNOWN_ADDRESS_DAYS`) restent admises. Un titulaire qui se connecte de son poste habituel n'est pas gêné.
- **Mot de passe oublié.** Une nouvelle demande n'annule plus le lien déjà reçu. Au plus un courriel par compte toutes les 5 minutes et 3 liens valides à la fois (`PASSWORD_RESET_COOLDOWN_MINUTES`, `PASSWORD_RESET_MAX_LIVE_LINKS`). Utiliser l'un des liens annule les autres.
- **Paramètres e-mail.** Remettre le mot de passe SMTP ou la clé Mailgun à la valeur du `.env` est refusé tant que la console pointe vers un autre serveur que celui du `.env`.
- **Déploiement logiciel.**
  - Une installation dont le paquet a été retiré après la mise en file passe en échec au lieu de partir. Une désinstallation part toujours.
  - Une désinstallation qu'aucun poste n'exécuterait est refusée (`package.not_ready`), comme l'installation. `msiexec /x {code produit}` reste accepté sans signature.
  - Refusés en plus à côté de l'exécutable en méthode A : `.bpl`, `.pyd`, `.xll`, `.node`, `.rll`, `.wsc`, `.sct`.
  - Un nom de fichier, une version ou des arguments contenant un caractère de contrôle bidirectionnel ou un séparateur de ligne Unicode sont refusés.
- **Maintenance.**
  - Le responsable de maintenance d'un poste ou d'une salle doit pouvoir lire et enregistrer les maintenances, et voir le poste ou la salle. Code `maintenance.owner.out_of_reach`, message : « Ce compte ne peut pas suivre cette maintenance (droits de maintenance ou périmètre insuffisants) : choisissez quelqu’un dont le périmètre couvre ces postes ». Un responsable déjà en place n'est pas revérifié tant qu'on ne le change pas.
  - Une vérification ne peut plus être close à une date future.
- **Salles en mode annuaire.** La resynchronisation n'adopte une salle créée à la main que pour l'OU déclarée par la majorité des postes de ce nom. En cas d'égalité, rien n'est adopté et le journal du serveur le signale.
- **Réveil (Wake-on-LAN).**
  - Sans `WOL_ALLOWED_NETWORKS`, le réveil direct ne vise que les plages RFC 1918 (10/8, 172.16/12, 192.168/16). Le sous-réseau déduit de l'adresse et du masque d'un poste doit tenir entièrement dans un réseau autorisé ; sinon le préfixe par défaut est essayé, sinon le poste n'a pas de destination.
  - Un agent qui ne déclare pas de version lisible ne sert plus de relais, et la console ne compte que les relais de confiance.
  - Un relais qui a laissé expirer un réveil ne le reçoit plus.
- **Fréquence des contacts.** Un poste est limité à 12 contacts par minute (30 auparavant ; `AGENT_HEARTBEAT_MAX_PER_MINUTE`). L'agent en fait un par minute par défaut.
- **Catalogue logiciel.** Un poste ne peut ajouter que 2 000 logiciels nouveaux au catalogue par 24 heures (`SOFTWARE_NEW_ENTRIES_PER_DAY`). Un premier inventaire complet tient dans ce budget ; les logiciels déjà connus ne comptent pas.
- **Console.**
  - Liste des postes : la sélection est vidée dès que la liste change (filtre, page, lien « Postes » du menu, retour).
  - Fiche : la navigation précédent/suivant ne répète plus un poste et n'affiche plus de voisins faux.
  - Après une mise à jour du serveur, un onglet ouvert auparavant se recharge une fois de lui-même au lieu d'afficher une erreur.

---

## Agent

- Une commande dont l'identifiant n'est pas un UUID est refusée. Cet identifiant nommait un fichier de la file locale : un serveur compromis pouvait écrire hors du dossier.
- Le manifeste d'un paquet est refusé s'il contient une clé en double, inconnue, ou écrite avec une autre casse ou un caractère Unicode voisin (« inſtall »). L'agent exécute donc exactement ce que le script de signature a montré.
- En méthode A, un manifeste qui annonce plus de 8 Gio est refusé avant tout téléchargement. La valeur de registre `DeployMethodAMaxGB` (`REG_DWORD`, en Gio, sous `HKLM\SOFTWARE\Tiai`) la remplace.
- Un jeton refusé par le serveur et resté sur le disque n'est plus relu en boucle : l'agent se réenrôle.
- Un verdict de commande refusé définitivement par le serveur ne bloque plus ceux qui suivent dans la file locale.

---

## Nouvelles variables d'environnement

Toutes facultatives : leur valeur par défaut est celle décrite plus haut.

| Variable | Défaut | Rôle |
|---|---|---|
| `LOGIN_SIEGE_ADDRESSES` | `10` | Adresses en échec au-delà desquelles un verrou s'étend à toutes les adresses non habituelles |
| `LOGIN_KNOWN_ADDRESS_DAYS` | `30` | Durée pendant laquelle une adresse qui a ouvert un compte reste admise pendant un tel verrou |
| `PASSWORD_RESET_COOLDOWN_MINUTES` | `5` | Délai minimal entre deux courriels de réinitialisation d'un compte |
| `PASSWORD_RESET_MAX_LIVE_LINKS` | `3` | Liens de réinitialisation valides à la fois pour un compte |
| `AGENT_HEARTBEAT_MAX_PER_MINUTE` | `12` | Heartbeats acceptés par poste et par minute |
| `SOFTWARE_NEW_ENTRIES_PER_DAY` | `2000` | Nouveaux logiciels qu'un poste peut ajouter au catalogue par 24 h |

Clé de registre de l'agent : `DeployMethodAMaxGB` (`REG_DWORD`), voir plus haut.

## Écart connu

Les sauvegardes ne sont toujours pas chiffrées sur le serveur : la copie hors serveur doit l'être (`DEPLOYMENT.md` § Sauvegardes). Les autres limites acceptées sont listées dans `dev/plan-audit-2026-11.md` §6.2.

## Migrations

| Migration | Contenu |
|---|---|
| `0032` | Date du dernier échec de connexion (`users.last_failed_login_at`) ; compteurs d'échecs remis à zéro |
| `0033` | Relais libérés d'un réveil (`commands.released_relay_ids`) |

Le backend applique les migrations à son démarrage.

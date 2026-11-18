# Tia'i v1.2.1

Cette version corrige les écarts trouvés par les deux passes de vérification de l'audit 2026-11 (13 et 14 novembre 2026). Elle contient une régression de la v1.2.0 corrigée (fichiers de paquet supprimés pendant un dépôt), des constats nouveaux sur l'agent, et des compléments à la plupart des tâches de l'audit. Le détail est dans `dev/plan-audit-2026-11.md` §6.1 et §6.3.

Elle corrige aussi les défauts relevés par la recette de solidité du 16 novembre 2026 : sept recetteurs ont éprouvé les fonctionnalités existantes sur un banc complet (serveur, console, agent Go réel), avec des requêtes concurrentes, des pannes de réseau et de messagerie, des comptes aux droits réduits et des volumes de parc réalistes. Ces corrections sont décrites au § « Recette de solidité ».

Enfin, elle reprend les limites que l'audit avait acceptées (§6.6 de `dev/plan-audit-2026-11.md`) : sauvegardes chiffrables, verrouillage des essais lents, budgets de sécurité par adresse et par session, état partagé entre processus API, navigation de la fiche calculée par le serveur. Voir § « Limites de l'audit reprises ».

Une vérification indépendante de l'ensemble (17 novembre 2026) a ensuite cherché à prendre ces corrections en défaut : sept relecteurs, par reproduction sur le banc, et en retirant les corrections une à une pour voir si un test échouait. Elle a trouvé onze défauts moyens, dont sept introduits par les corrections elles-mêmes, et une quarantaine de défauts mineurs ; tous sont corrigés ici. Voir § « Vérification du 17 novembre ».

Elle rend enfin la console bilingue, français et anglais, au choix de chaque compte (`dev/plan-console-bilingue.md`). Voir § « Console bilingue ».

Elle contient seize migrations de base (`0032` à `0047`).

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
7. **Autres bornes du `.env`.** Les valeurs suivantes sont désormais contrôlées au démarrage, avec les bornes de la page Paramètres ; une valeur hors bornes empêche le backend de démarrer, en la nommant : `WOL_PORT` (1 à 65 535), `WOL_PACKET_COUNT` (1 à 20), `WOL_SUBNET_PREFIXLEN` (8 à 30), `LOW_DISK_FREE_PERCENT` (1 à 99), `INACTIVE_AFTER_DAYS` (1 à 3 650), `SIGNATURE_MAX_AGE_DAYS` (0 à 365), `SMTP_TIMEOUT_SECONDS` (1 à 120), `EMAIL_MAX_ATTEMPTS` (au moins 1), `EMAIL_OUTBOX_RETENTION_DAYS` (au moins 0), `NOTIFICATION_MAX_ITEMS` (au moins 1), `POSTGRES_POOL_SIZE` (au moins 1), `POSTGRES_MAX_OVERFLOW` (au moins 0). `EMAIL_FROM_EMAIL` doit être une adresse valide et `CONSOLE_BASE_URL` une URL `http(s)` ; vides, elles restent « non renseignées ».
8. **Groupes homonymes à la casse près.** Les noms de groupe deviennent uniques sans tenir compte de la casse. La migration `0037` renomme les doublons existants en « Nom (2) », « Nom (3) »… ; le groupe le plus ancien et les groupes intégrés gardent leur nom. Vérifier la page **Groupes** après la mise à jour.
9. **Image de sauvegarde construite sur place.** Le service `db-backup` est désormais construit depuis `deploy/backup/` (`postgres:16-alpine` + `age`) : à chaque mise à jour, lancer `docker compose build --pull db-backup` avant `docker compose up -d` (`DEPLOYMENT.md` § « Mettre à jour le serveur »). La première construction a besoin du registre Docker et de `dl-cdn.alpinelinux.org`.
10. **`TRUSTED_PROXIES`.** Une entrée plus large qu'un /24 (IPv4) ou qu'un /64 (IPv6) empêche le backend de démarrer. Ne lister que les proxys ; sinon, poser `TRUSTED_PROXIES_ALLOW_WIDE=true` en connaissance de cause.
11. **Python 3.15 dans l'image du backend.** L'image passe de Python 3.12 à 3.15, qui lit les certificats plus strictement. L'envoi par SMTP garde la vérification de la v1.2.0 (chaîne et nom du serveur) : un relais derrière une autorité de certification interne reste accepté. Un seul cas change : **Mailgun à travers un proxy qui déchiffre le TLS** avec une AC privée non conforme à la RFC 5280 est refusé (`CERTIFICATE_VERIFY_FAILED`) ; réémettre l'AC. Dans tous les cas, envoyer l'e-mail de test (**Paramètres → Envoi des e-mails**) après la mise à jour.
12. **Salles et bâtiments homonymes à la casse près.** Les noms de salle (dans un bâtiment, et parmi les salles sans bâtiment) et de bâtiment (dans un site) deviennent uniques sans tenir compte de la casse. La migration `0043` renomme les doublons existants en « Nom (2) », « Nom (3) »… ; le plus ancien garde son nom. Vérifier la page **Salles** après la mise à jour.
13. **`max_connections` de PostgreSQL.** Un processus d'API peut ouvrir jusqu'à deux fois son pool en connexions (60 avec les valeurs par défaut), plus 30 pour le worker : la valeur par défaut de PostgreSQL (100) suffit pour une API et un worker, pas au-delà (`DEPLOYMENT.md`, ligne `POSTGRES_POOL_SIZE`).
14. **Script de signature.** `Sign-TiaiPackage.ps1` est à remplacer par celui de cette version : il applique la nouvelle règle sur `msiexec` (voir plus bas).
15. **Postes enrôlés dans l'heure qui précède la mise à jour.** Un poste dont la réponse d'enrôlement s'est perdue juste avant la mise à jour demandera une approbation au lieu d'être servi de nouveau.
16. **Langue de la console.** Un compte qui n'a pas choisi de langue suit celle de son navigateur : un navigateur réglé en anglais affiche désormais la console en anglais. Pour garder le français, choisir **Français** dans **Mon compte → Langue**. Les e-mails d'un compte sans choix partent dans `DEFAULT_LANGUAGE` (`fr` par défaut, donc comme avant).
17. **Sauvegardes manuelles.** La purge de `backup.sh` ne retire plus que les dumps quotidiens (`tiai-AAAAMMJJ-HHMMSS.dump`). Les dumps manuels déjà présents dans `deploy/backups/` sous un autre nom sont désormais gardés indéfiniment : les supprimer à la main quand ils ne servent plus.

### Agent : mettre à jour le parc

Les correctifs de l'agent n'agissent qu'après la mise à jour par GPO.

- **Script GPO.** `Install-TiaiAgent.ps1` n'est pas un fichier de la release : le recopier à la main sur le partage. Il accepte désormais `-AllowInsecureHttp` (`true` ou `false`), et le MSI la propriété `ALLOWINSECUREHTTP` (`1` ou `0`).
- **Ordre à respecter.** Copier le nouveau script **avant** d'ajouter `-AllowInsecureHttp` aux arguments de la GPO. L'ancien script refuse ce paramètre inconnu sans rien journaliser, et plus aucun poste n'est installé ni mis à jour.
- **Messages de l'agent.** Un agent de cette version envoie un code avec ses propres messages (refus, délais dépassés, réveil relayé, déploiements) : la console les affiche dans la langue du lecteur. Un agent plus ancien continue d'envoyer son texte français, affiché tel quel.
- **Onglets ouverts.** Les onglets de la console ouverts avant cette mise à jour doivent être rechargés à la main, une fois. Le rechargement automatique n'existe qu'à partir de cette version.

---

## Changements de comportement à annoncer aux utilisateurs

- **Langue.** La console existe en français et en anglais. Chaque compte choisit dans **Mon compte → Langue** : français, anglais, ou celle du navigateur (le choix par défaut). Le changement s'applique tout de suite, sans recharger la page, et suit le compte d'un poste à l'autre. Les e-mails partent dans la langue du compte, l'e-mail de test dans celle de l'administrateur qui l'envoie, et les exports Excel et CSV dans la langue de la console.
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
- Un poste en attente d'approbation (ré-enrôlement) ou dont le jeton est révoqué réessaie après 1, 2, 4, 8 puis 15 minutes (chaque palier tiré entre sa moitié et sa valeur), au lieu d'un palier de 15 à 30 minutes : un poste approuvé reprend en quelques minutes. Un poste que personne n'approuve coûte environ cinq tentatives par heure. Seul un succès termine l'attente : un 429 ou une panne ne ramène pas au premier palier. L'agent respecte le `Retry-After` d'un 429 (borné à 15 minutes) ; au plafond, un 429 fait passer le poste à un palier de 30 minutes jusqu'à son enrôlement, pour qu'une salle entière en attente derrière une même adresse (NAT, proxy) ne sature pas le limiteur d'enrôlement. Au-delà d'environ 130 postes en attente derrière une seule adresse, ce limiteur (30 enrôlements par 5 minutes et par adresse) se remplit de nouveau.
- Les caractères de contrôle (tous sauf tabulation, saut de ligne et retour chariot ; NUL notamment) sont retirés de toute requête de l'agent avant l'envoi au serveur, qui refusait par exemple tout un verdict de commande.
- Quand les deux méthodes de déploiement refusent un paquet, le verdict donne le motif de la méthode B en plus de celui de la méthode A.

---

## Recette de solidité (16 novembre 2026)

Chaque correction a un test qui échoue sans elle. La vérification du 17 novembre a montré que ce n'était pas vrai pour une trentaine de corrections, dont le test ne couvrait pas le chemin réel ; les tests manquants ont été ajoutés (§ « Vérification du 17 novembre »).

### Postes, enrôlement et commandes

- Un poste dont la réponse d'enrôlement s'est perdue termine son enrôlement en réessayant, sans approbation, tant que le jeton émis n'a authentifié aucune requête (moins d'une heure, même empreinte). L'ancien jeton est invalidé et la reprise est tracée dans le journal.
- Le bandeau « Identité à confirmer » peut être levé sans fusion, par le bouton « Confirmer l'identité » (droit de modification des postes, tracé dans le journal).
- Les ré-enrôlements en attente et les jetons révoqués sont visibles dans la liste des postes (filtre « Enrôlement », icônes) et au tableau de bord ; les ré-enrôlements en attente peuvent être autorisés en lot.
- Une commande n'est plus envoyée à un poste dont le jeton est révoqué : refus explicite pour un poste seul, poste écarté et compté dans un envoi groupé. Les messages d'envoi disent si la commande est déjà en attente, transmise ou en cours sur ce poste.
- Lors d'une fusion, les commandes encore ouvertes du poste absorbé sont closes (« Poste fusionné : commande annulée ») au lieu d'être transmises une seconde fois au poste conservé.
- Le verdict d'une commande remonté par le poste est définitif : une réponse rejouée ne déplace plus « Terminée le » et ne remplace plus le résultat. Un verdict tardif l'emporte toujours sur une clôture faite par le serveur (expiration, sans réponse).
- Un caractère nul envoyé par un poste (nom, logiciel, menace, résultat de commande…) est retiré au lieu de faire échouer toute la remontée ; dans la console, il est refusé avec « Caractère nul refusé » au lieu d'une erreur serveur.
- Des enrôlements simultanés d'un même poste, ou deux fusions croisées, ne provoquent plus d'erreur serveur. Un identifiant de poste vide est refusé, les espaces autour sont ignorés.
- Des demandes de reprise de téléchargement invalides (plage hors fichier) ne bloquent plus les déploiements avec « Too many downloads in progress ».
- Le message « réveil déjà en attente » indique depuis combien de temps (« depuis 12 min ») au lieu d'une heure UTC.
- Un poste resté silencieux ne reste plus « Antivirus à jour » : l'âge des signatures vieillit avec le temps, de la même façon dans la liste, la fiche, les filtres, le tableau de bord, le résumé quotidien et l'export. Changer le seuil d'âge ne transforme plus un antivirus « inconnu » en « périmé ».
- Une valeur choisie dans les listes de choix des filtres d'inventaire (antivirus, OS, constructeur, modèle, processeur) filtre sur cette valeur exacte : « OptiPlex 7010 (12) » liste ces 12 postes, et plus aussi les « OptiPlex 7010 AIO ». L'API garde la recherche par sous-chaîne quand le paramètre `exact` n'est pas donné.
- La carte « À renouveler » du tableau de bord ouvre la liste des postes concernés (filtre `hardware_aging`).
- L'export Excel du parc est construit en un temps proportionnel au nombre de lignes (il en prenait le carré : 89 s pour 1 500 postes avec toutes les colonnes) et hors de la boucle de l'API, qui continue de répondre pendant ce temps. L'export CSV écrit les décimales avec une virgule.

### Paquets logiciels

- Redéployer un paquet modifié remplace les installations encore en attente de l'ancienne version (« Remplacée par un nouveau déploiement ») au lieu de ne rien envoyer. Les envois déjà reçus par les postes ne sont pas touchés. Plusieurs déploiements identiques lancés en même temps ne créent plus qu'une installation par poste.
- Une signature refusée indique pourquoi : manifeste modifié depuis la signature, autre certificat, algorithme inadapté à la clé, certificat illisible ou base64 invalide.
- Retirer un paquet demande confirmation en indiquant combien d'installations en attente seront annulées ; le remettre au catalogue ne les relance pas, et la console le dit.
- Un paquet qu'aucun poste n'exécuterait (exécutable non signé, DLL à côté d'un installateur d'éditeur…) n'est plus affiché « Prêt » : la liste, la fiche et la fenêtre de déploiement disent pourquoi en nommant le fichier en cause.
- Un nom de fichier refusé est cité avec la raison précise ; lors d'un dépôt de plusieurs fichiers, la console dit lesquels ont été gardés et lesquels n'ont pas été envoyés.
- La fiche d'un paquet demande confirmation avant de quitter pendant un dépôt ou avec des modifications non enregistrées, et propose « Enregistrer puis déployer » au lieu de déployer l'ancienne définition.
- Un fichier remplacé est supprimé du serveur dès que le dernier déploiement qui le gardait se termine, même par expiration ou refus à la livraison ; un nettoyage horaire couvre les serveurs inactifs.
- Finitions : puces d'état qui filtrent le tableau sur le dernier déploiement de chaque poste, noms longs qui passent à la ligne, fichiers triés à la française, identifiant winget accepté avec espaces, paquets homonymes distingués, messages de longueur et tailles au format français.

### Salles, vérifications et maintenance

- L'observation générale d'une séance de maintenance se consulte depuis l'historique du poste (« Voir la séance ») et depuis la fiche de la salle, où toutes les séances sont listées, avec les postes non faits et leur motif.
- Une séance enregistrée par erreur peut être supprimée (avec confirmation) ; ses lignes d'historique disparaissent et la dernière maintenance des postes revient à la précédente.
- « Resynchroniser depuis l'annuaire » affiche d'abord ce qu'elle va faire (postes qui changent de salle, salles créées) et demande confirmation. Un poste sans aucune information d'annuaire reste dans sa salle ; une salle créée à la main dans un bâtiment est reprise par son nom au lieu d'être doublée.
- La fenêtre « à échéance » est limitée à la moitié du cycle : un poste au cycle court redevient « À jour » après sa maintenance.
- Enregistrer les Paramètres n'efface plus le responsable de maintenance par défaut quand son compte a été désactivé ; il s'affiche « Compte désactivé : <nom> ». Un responsable ou un destinataire désactivé est affiché par son nom suivi de « (désactivé) », jamais par un identifiant.
- Un compte qui ne gère que la maintenance a le menu « Mes tâches ». La page affiche toutes les vérifications ouvertes (plus de coupure à 200), et les postes qui ont leur propre responsable ou cycle y forment un groupe à part.
- Une vérification dont l'affecté ne voit plus le poste (déplacé, droits retirés, compte désactivé) redevient « à prendre » partout (Mes tâches, liste des postes, export, fiche) et n'est plus envoyée par e-mail ; la fiche et Mes tâches disent à qui elle était affectée. Seuls les comptes pouvant clore une vérification sont proposés pour la prendre.
- La clôture d'une vérification peut être antidatée, mais jamais avant la demande. Une séance de maintenance d'une salle refuse les postes d'une autre salle et les nomme. Le texte saisi dans « Demander une vérification » est retrouvé par le même compte si la session prend fin avant l'envoi ; il est oublié à la déconnexion et dès qu'un autre compte se connecte dans l'onglet.
- Un nom de salle ou de bâtiment vide est refusé, et deux salles d'un même bâtiment (ou deux salles sans bâtiment, ou deux bâtiments d'un même site) ne peuvent plus porter le même nom à la casse près, y compris créées au même instant (migration `0043`). Un nom fait uniquement de caractères invisibles est refusé comme un nom vide. Une salle ou un bâtiment cité dans le périmètre d'un groupe ne peut plus être supprimé.
- L'historique n'affiche plus « Vérification — Vérification » ni « Maintenance — Maintenance — A101 ».

### Comptes, sessions et e-mails

- Plusieurs onglets rafraîchis en même temps ne ferment plus la session, même si l'un d'eux répond lentement. Un jeton réutilisé hors de la fenêtre de grâce reste traité comme un vol.
- Deux derniers administrateurs qui se désactivent l'un l'autre au même instant ne peuvent plus laisser la console sans administrateur.
- Créer ou renommer en même temps plusieurs comptes ou groupes avec la même adresse ou le même nom renvoie « déjà utilisé » au lieu d'une erreur interne.
- Les noms de compte et de groupe sont nettoyés de leurs espaces et bornés ; un mot de passe de plus de 72 octets est refusé avec un message clair, ainsi qu'un nouveau mot de passe identique à l'actuel.
- Des préférences enregistrées en même temps par plusieurs pages ne s'écrasent plus.
- Le groupe intégré « Techniciens » reçoit la lecture des paquets sur les installations antérieures.
- Seuls les comptes qui lisent les postes reçoivent l'état du parc par e-mail ; les autres ne reçoivent que leurs tâches. Les dates des e-mails indiquent « (UTC) », les consignes sur plusieurs lignes restent alignées, le pied de message vient en dernier et le bloc « Vos tâches » n'est plus reçu deux fois le matin du rappel.
- Un serveur de messagerie muet ne bloque plus le worker ; un résumé dont l'envoi échoue est retenté le jour même ; résumé et rappel ne partent jamais deux fois pour la même journée ou semaine, même après un redémarrage. Un worker démarré après l'heure du résumé l'envoie aussitôt s'il n'est pas déjà parti ce jour-là, au lieu d'attendre le lendemain.
- Dans le bloc « Vos tâches » des e-mails, une salle dont les postes suivent deux cycles différents n'apparaît plus qu'une fois.
- L'e-mail de test dit clairement qu'un serveur muet n'a pas répondu dans le délai, et qu'un serveur exigeant une authentification attend un compte.
- La page Paramètres affiche aussi les réglages des paquets, de la file d'e-mails, du pool de base de données, de Mailgun (le proxy par son seul hôte) et le nom du serveur.

### Console

- Quand une partie de la fiche ne peut pas être chargée (menaces, commandes, utilisation, historique, maintenance), la carte le dit et propose « Réessayer » ; la fiche n'affiche plus « Aucune alerte » sur des données manquantes. Un chargement initial en échec affiche un bandeau permanent (Utilisateurs, Groupes, Paramètres, Mon compte, profil). Un poste inexistant affiche « Poste introuvable », sans bouton d'action.
- La console ne propose plus que ce que le compte peut consulter : menu et page d'accueil adaptés, cases à cocher et actions groupées masquées sans droit d'action, actions sur les comptes et groupes plus puissants désactivées. Cocher un droit de modification coche sa consultation. Des droits modifiés par un administrateur sont pris en compte sans recharger la page.
- Un double clic sur une action de la fiche n'envoie plus la commande deux fois. Sélectionner du texte dans un tableau n'ouvre plus la ligne. Dans les tableaux (postes, salles, postes d'une salle, Mes tâches, paquets), la fiche s'ouvre par le nom, souligné ; le reste de la ligne est du texte que l'on sélectionne et copie, double-clic compris. Dans le journal d'audit, le détail s'ouvre par le bouton en bout de ligne.
- Après un clic hors connexion, la page demandée se recharge d'elle-même au retour du réseau. Quand la session prend fin, la page de connexion l'indique.
- Filtres des postes : tout type de poste est accepté, la mémoire garde son opérateur, la recherche ignore les espaces, un domaine passé dans l'adresse a sa puce.
- Le seuil « disque presque plein » réglé dans Paramètres s'applique à la fiche et aux barres de la liste ; le tableau de bord montre les postes à renouveler.
- Nombres au format français partout (« 2,3 Gio »), « — » pour les cases vides, « (sans nom) » pour une menace sans nom. La réinitialisation d'un mot de passe lève aussitôt le badge « Verrouillé ».
- La fiche garde le nom du poste dans l'onglet du navigateur, et les noms très longs ne débordent plus. Icône d'onglet, lien « Aller au contenu », graphique d'utilisation lisible au lecteur d'écran, confirmation avant de quitter Paramètres sans enregistrer, impression de la liste des postes.

---

## Limites de l'audit reprises (16 novembre 2026)

- **Sauvegardes chiffrables.** Les dumps quotidiens peuvent être chiffrés pour une ou plusieurs clés publiques `age` (`BACKUP_ENCRYPT_RECIPIENT`, fichiers `tiai-….dump.age`). La clé privée ne va jamais sur le serveur : la perdre, c'est perdre les sauvegardes chiffrées. Génération des clés, restauration et vérification : `DEPLOYMENT.md` § « Chiffrer les sauvegardes ». Sans la variable, rien ne change.
- **Mot de passe oublié.** La réponse arrive après le même délai quel que soit le compte. Le budget de demandes est compté par adresse : un tiers qui épuise le sien n'empêche plus le titulaire de recevoir un lien depuis son poste. Un plafond par compte (`PASSWORD_RESET_ACCOUNT_MAX_LIVE_LINKS`) borne les liens venus de nombreuses adresses, sauf depuis une adresse habituelle.
- **Essais lents.** Des échecs de connexion espacés (20 en 24 h par défaut) posent un second verrou, pour 24 h, qui figure au journal d'audit. Il ferme le compte aux **adresses qui ont échoué pendant cette fenêtre** ; à partir de `LOGIN_SIEGE_ADDRESSES` adresses en échec, seules les adresses habituelles restent admises. Le bon mot de passe saisi depuis une adresse qui n'a pas échoué ouvre la session, habituelle ou non. Une connexion réussie ne lève pas ce verrou et ne rend pas de budget à qui devine ; seul un nouveau mot de passe l'efface, et la page Utilisateurs affiche « Verrouillé » jusqu'à sa fin. Pendant ce verrou, le plafond de liens « Mot de passe oublié » par compte ne s'applique pas : le titulaire peut toujours en demander un.
- **Changer mon mot de passe.** Le budget de 5 essais du mot de passe actuel est propre à chaque session : une session qui l'épuise est fermée (journal d'audit), les autres sessions du titulaire ne sont plus touchées.
- **Proxy de confiance.** Le serveur refuse de démarrer si `TRUSTED_PROXIES` liste un réseau plus large qu'un /24 ou un /64, sauf `TRUSTED_PROXIES_ALLOW_WIDE=true`.
- **Plusieurs processus API.** Les fichiers d'un dépôt de paquet en cours et les budgets du catalogue logiciel sont tenus dans PostgreSQL et non plus en mémoire : ils valent pour plusieurs processus de l'API, et un redémarrage ne remet plus les budgets à zéro. Si la réservation d'un budget n'aboutit pas en quelques secondes, le battement répond quand même : le relevé logiciel est marqué partiel puis redemandé, et le journal du backend le signale (`budgets unreachable`).
- **Méthode A et msiexec.** Une installation qui lance `msiexec /x` ou `/uninstall`, ou qui porte `REMOVE=` (`msiexec /i {code} REMOVE=ALL`), est refusée par la console, le script de signature et l'agent, y compris quand la forme est cachée au milieu d'un argument ou entre guillemets ; la désinstallation par code produit reste possible. Revers : un fichier dont le nom contient une espace suivie de `-x…` (« mon appli -x64.msi ») fait refuser l'installation ; le renommer. Un paquet enregistré avant cette règle garde sa désinstallation, et son installation est signalée comme bloquée.
- **Place des paquets sur les postes.** L'agent borne la place des téléchargements interrompus ou refusés (`DeployCacheMaxGB`, 16 Gio par défaut) : au démarrage du service et avant chaque téléchargement, il retire les plus anciens au-delà du plafond, jamais le paquet en cours, et note chaque retrait dans `agent.log`.
- **Comptes limités à certains sites.**
  - Une séance de maintenance vue à travers l'un de leurs postes ne montre plus l'observation générale, ni la salle dans la séance elle-même, et ne peut plus être supprimée si elle déborde du périmètre. Le nom de la salle reste lisible là où le compte voit déjà son poste (fiche, titres de l'historique, liste des maintenances à faire). Une séance dont la salle a été supprimée reste partielle pour un compte restreint.
  - Dans le journal d'audit, une fusion dont la fiche absorbée était ailleurs s'affiche « a absorbé une fiche hors de votre périmètre », y compris pour les fusions antérieures.
- **Séances de maintenance.** Une séance où aucun poste n'a été fait s'enregistre si elle dit pourquoi (observation générale de la salle ou note d'un poste non fait), sans toucher aux échéances. Une salle de plus de 1 000 postes s'enregistre en une seule séance, envoyée par parts, avec reprise de l'envoi en cas de coupure, première part comprise : une réponse perdue ne crée pas de seconde séance. Un poste sorti de la salle pendant l'envoi est nommé et peut être retiré pour envoyer le reste.
- **Téléphone.** La page Salles, la fiche d'une salle et les dialogues de séance s'affichent en cartes et en plein écran, sans défilement horizontal.
- **Précédent / suivant sur la fiche.** Les flèches sont calculées par le serveur sur l'ordre exact de la liste (mêmes filtres, tri et périmètre) : plus de poste sauté ni de limite de 2 000 lignes, et le rang « Poste n sur N » est toujours juste.

Reste acceptée l'**origine déclarative de l'emplacement et de l'OU** d'un poste (S19, S20) : la lecture de l'annuaire par le serveur est planifiée dans `dev/plan-lecture-annuaire.md`.

---

## Vérification du 17 novembre 2026

Sept relecteurs indépendants ont cherché à prendre en défaut tout ce qui précède. Chaque défaut ci-dessous a d'abord été reproduit par un test, puis corrigé ; les corrections déjà reportées plus haut (verrou des essais lents, règle `msiexec`, reprise d'une séance, noms uniques) ne sont pas répétées.

### Postes, enrôlement et commandes

- **Sécurité.** La reprise d'un enrôlement dont la réponse s'est perdue confondait un jeton tout juste renouvelé avec un jeton jamais utilisé : pendant une heure au plus, un tiers détenant le secret d'enrôlement, l'identifiant et l'empreinte d'un poste éteint pouvait se ré-enrôler à sa place sans approbation. « Jamais utilisé » est désormais un fait enregistré, effacé par toute requête authentifiée du poste (migration `0041`). `DEPLOYMENT.md` décrit cette seule exception à la règle d'approbation.
- Un âge de signatures aberrant remonté par un poste (négatif, ou au-delà de 36 500 jours) est enregistré comme inconnu ; il faisait échouer le tableau de bord, les filtres « à jour / périmé », les commandes ciblées par état et le résumé quotidien de tout le parc.
- Un corps JSON très imbriqué contenant un caractère de contrôle ne provoque plus d'erreur serveur. La page de connexion refuse un caractère nul quel que soit l'encodage du formulaire. Un demi-caractère UTF-16 isolé envoyé par un poste est retiré comme un caractère nul, au lieu de faire échouer toute la remontée.
- Un curseur de navigation précédent/suivant modifié à la main est ignoré au lieu de provoquer une erreur serveur. Le filtre `hardware_aging=false` inclut les postes dont la date de BIOS est inconnue.

### Paquets logiciels

- Une liste d'arguments ou de codes de sortie `null` est refusée à l'enregistrement d'un paquet ; un paquet qui en contenait déjà une ne bloque plus la page Paquets.

### Salles et maintenance

- La suppression d'une séance et l'ajout de postes à cette séance ne peuvent plus se croiser : aucune ligne de maintenance ne survit à sa séance, et l'ajout tardif répond « séance introuvable » au lieu d'une erreur serveur.
- « Annuler » est désactivé pendant l'envoi d'une séance ; l'abandon n'est proposé qu'une fois l'envoi interrompu, en disant ce qui reste enregistré.
- Une resynchronisation depuis l'annuaire lancée pendant que les postes remontent leur annuaire ne se termine plus par une erreur ; des postes qui déclarent ensemble une nouvelle OU sont tous rangés dans la salle créée.
- Pour un compte restreint, la liste des séances d'un poste hors de son périmètre est vide.

### Comptes et sessions

- `LOGIN_SLOW_MAX_FAILED_ATTEMPTS` et `LOGIN_SLOW_WINDOW_HOURS`, non définies, suivent le verrou rapide : un `.env` qui ne règle que `LOGIN_MAX_FAILED_ATTEMPTS` ou `LOGIN_LOCKOUT_MINUTES` démarre toujours. Seule une contradiction écrite dans le `.env` empêche le démarrage.
- Les cinq essais du mot de passe actuel par session tiennent même avec `RATE_LIMIT_ENABLED=false`.
- La vérification d'un lien de réinitialisation ne fait plus passer le jeton par l'adresse de la requête : il n'apparaît plus dans le journal d'accès du backend.
- Une préférence imbriquée sur plus de 8 niveaux, ou contenant une valeur non représentable, est refusée ; un profil qui en contenait déjà une se charge de nouveau.
- La migration `0037` reconnaît les groupes homonymes comme PostgreSQL les compare ; elle n'échoue plus sur certains noms (grec, turc).
- La page Paramètres n'affiche plus aucun fragment d'une URL de proxy mal formée.
- Plusieurs interblocages rares sont supprimés (réinitialisation par un administrateur pendant une connexion, un rafraîchissement ou un changement de mot de passe), ainsi que deux erreurs serveur (modifier un compte pendant sa suppression, renommer plusieurs groupes vers le même nom).

### Worker, e-mails et sauvegardes

- À l'arrêt du worker, l'e-mail en cours d'envoi est terminé et aucun autre n'est commencé : un e-mail n'est plus envoyé une seconde fois au redémarrage. Un serveur de messagerie muet ne retarde plus l'arrêt au-delà de 10 secondes.
- Le jour de la mise à jour, le résumé déjà envoyé par la version précédente n'est pas renvoyé, ni le rappel de la semaine (migration `0042`). Deux workers lancés par erreur sur la même base n'envoient le résumé qu'une fois.
- Un résumé en échec au moment où l'on déplace son heure, ou jusqu'à minuit avec une heure de 0, ne fait plus sauter celui du lendemain. Déplacer l'heure vers une heure déjà passée envoie le résumé du jour s'il n'est pas parti.
- Un échec du résumé du parc n'empêche plus le rappel hebdomadaire des maintenances.
- L'e-mail de test dit de passer en STARTTLS quand le serveur l'exige, et donne le bon délai quand un serveur ne répond pas, y compris en TLS implicite.
- Une sauvegarde chiffrée n'est gardée que si `pg_dump` a réussi, même quand `/tmp` du conteneur n'est pas inscriptible ; un échec passait pour un succès dans ce cas.
- `DEPLOYMENT.md` : le retour en arrière ne reconstruit plus le backend et la console ; le cas d'un hôte qui ne joint pas le miroir Alpine est décrit ; un dump déposé avant restauration doit être renommé pour ne pas être purgé.

### Console

- Un onglet de la console laissé en arrière-plan n'envoie plus aucune requête : une session inutilisée se ferme bien après `REFRESH_TOKEN_EXPIRE_DAYS` (7 jours), et non plus après 30.
- Paramètres : la confirmation avant de quitter couvre aussi la carte Maintenance.
- Fiche d'un poste : l'onglet « Historique » n'est proposé qu'aux comptes qui peuvent consulter les interventions ou la maintenance.
- Liste des postes : une valeur de filtre saisie à la main dans l'adresse et absente du parc est signalée (« valeur exacte — aucune correspondance dans le parc »).
- Un compte limité à la maintenance voit sa pastille de postes en retard sur « Mes tâches ». Le bandeau « Impossible de charger votre profil… » s'affiche quelle que soit la panne.
- Une commande confirmée deux fois dans le même instant n'est envoyée qu'une fois (fiche et sélection).

### Agent

Ces corrections n'agissent qu'après la diffusion du nouvel agent.

- Une réponse 429 du serveur remettait l'attente d'approbation à son premier palier : à partir d'environ 25 postes en attente derrière une même adresse, le limiteur d'enrôlement restait saturé, un poste approuvé pouvait attendre plus d'un quart d'heure et un poste neuf ne s'enrôlait plus sans retard. Voir § « Agent » plus haut pour le nouveau comportement.
- La règle `msiexec` de l'agent est exactement celle du serveur et du script de signature (mêmes cas d'essai).
- Le journal de l'agent ne signale plus à tort « no poll has completed » après une remise à l'heure ou une sortie de veille.

### Restent connus après cette vérification

- Un e-mail en cours d'envoi qui dépasse les 8 secondes de grâce à l'arrêt du worker est abandonné « en attente » ; si le serveur de messagerie l'accepte quand même, il repart au démarrage suivant.
- Pendant un verrou des essais lents, une adresse non habituelle qui se trompe une fois est refusée jusqu'à la fin du verrou ; l'issue est « Mot de passe oublié ».
- La construction de l'image `db-backup` se fait sur l'hôte et demande le miroir Alpine ; l'image n'est pas publiée avec la release.
- Non exécutés ici : les commandes Docker de la documentation, le script de signature, le MSI et ce qui demande Windows. Le script GPO, les commandes à distance et l'installation des mises à jour Windows sont validés sur le parc (retour du 18 novembre 2026).

---

## Console bilingue (Phase 6)

Plan : `dev/plan-console-bilingue.md`. Le backend ne rédige plus de phrases pour la console : il envoie des codes, des paramètres et des valeurs brutes, à côté de son texte français d'avant, et la console écrit la phrase dans la langue du lecteur.

- **Toute la console** est traduite : menus, pages, fiches, dialogues, confirmations, notifications, titres d'onglet, pack Quasar (pagination, sélecteurs de date), dates et nombres (`fr-FR` ou `en-GB`). Le français est inchangé, mot pour mot : les tests existants n'ont pas été modifiés.
- **Textes écrits par le serveur** : diagnostics et refus des paquets, refus de validation des formulaires, variables de la page **Paramètres → serveur**, résultat de l'e-mail de test, verdicts enregistrés des commandes (commande perdue, poste fusionné, paquet retiré, réveil), ligne « Maintenance non faite » et note de clôture par fusion. Les lignes enregistrées avant la mise à jour gardent leur texte français.
- **Groupes intégrés** : nommés dans la langue du lecteur tant qu'ils gardent le nom et la description donnés à l'installation ; renommés, ils s'affichent tels que saisis.
- **E-mails** : réinitialisation, résumé quotidien, alertes de menace, vérification affectée, rappel des maintenances, e-mail de test, dans la langue du destinataire ; le français est inchangé.
- **Exports** Excel et CSV des postes et des logiciels : en-têtes, valeurs, nom de la feuille et du fichier dans la langue de la console (`lang=en`). Sans ce paramètre, le fichier est identique à celui d'avant. Le CSV anglais garde le séparateur `;` et la virgule décimale.
- **Ne se traduit pas** : la sortie des outils Windows (dans la langue du poste), ce que les utilisateurs saisissent (noms, notes, consignes), et quelques textes de l'agent sans code (rapport détaillé d'installation des mises à jour Windows, étapes de la réinitialisation de Windows Update, échecs partiels du spouleur), affichés tels qu'envoyés.
- **API** : uniquement des ajouts. `users.language` (`/auth/me`), `params` et `install_blocker_problems` sur les paquets, `details.cause` / `details.causes` sur les refus de paquet, `type` `tiai_<code>` et `params` dans les refus 422 (le `msg` est inchangé), `code`/`raw`/`format`/`params` sur l'environnement du serveur, `code`/`params` sur l'e-mail de test, `result_code`/`result_params` sur les commandes, `detail_code`/`detail_params` sur le réveil, `title_code`/`title_params` sur les interventions, `closing_note_code` sur les vérifications, `builtin_key` sur les groupes d'un compte, paramètre `lang` des exports. L'agent ajoute `message_code`/`message_params` à ses résultats.

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
| `PASSWORD_RESET_ACCOUNT_MAX_LIVE_LINKS` | `10` | Liens de réinitialisation valides à la fois pour un compte, toutes adresses confondues (hors adresses habituelles) |
| `LOGIN_SLOW_MAX_FAILED_ATTEMPTS` | `20` | Échecs de connexion sur la fenêtre longue qui verrouillent le compte. Non définie : 20, ou quatre fois `LOGIN_MAX_FAILED_ATTEMPTS` si c'est davantage |
| `LOGIN_SLOW_WINDOW_HOURS` | `24` | Fenêtre longue des échecs, et durée du verrou qu'elle déclenche. Non définie : 24, ou le double de `LOGIN_LOCKOUT_MINUTES` si c'est davantage |
| `TRUSTED_PROXIES_ALLOW_WIDE` | `false` | Accepte dans `TRUSTED_PROXIES` une plage plus large qu'un /24 ou un /64 |
| `BACKUP_ENCRYPT_RECIPIENT` | vide | Clés publiques `age` pour chiffrer les sauvegardes ; vide = dumps en clair |
| `DEFAULT_LANGUAGE` | `fr` | Langue des e-mails d'un compte qui n'a pas choisi la sienne (`fr` ou `en`) |

Clés de registre de l'agent : `DeployMethodAMaxGB` et `DeployCacheMaxGB` (`REG_DWORD`), voir plus haut.

`PASSWORD_RESET_COOLDOWN_MINUTES` et `PASSWORD_RESET_MAX_LIVE_LINKS` s'appliquent désormais par compte **et par adresse d'origine**.

## Écarts connus

- Le chiffrement des sauvegardes est facultatif : sans `BACKUP_ENCRYPT_RECIPIENT`, les dumps restent en clair sur le serveur, et la copie hors serveur doit alors être chiffrée (`DEPLOYMENT.md` § « Sauvegardes et restauration »).
- L'emplacement et l'OU d'un poste restent déclarés par l'agent (S19, S20) ; les autres limites acceptées sont listées dans `dev/plan-audit-2026-11.md` §6.4.

## Migrations

| Migration | Contenu |
|---|---|
| `0032` | Date du dernier échec de connexion (`users.last_failed_login_at`) ; compteurs d'échecs remis à zéro |
| `0033` | Relais libérés d'un réveil (`commands.released_relay_ids`) |
| `0034` | Adresses de connexion par compte (`user_login_addresses`), initialisées avec celles des sessions ouvertes |
| `0035` | Relevé logiciel partiel (`machines.software_truncated_at`) |
| `0036` | Verdict d'une commande remonté par le poste (`commands.agent_verdict_at`) ; date du relevé de l'âge des signatures (`machines.signature_reported_at`), initialisée avec le dernier contact |
| `0037` | Noms de groupe uniques à la casse près (doublons renommés « (2) »…) ; lecture des paquets pour le groupe intégré « Techniciens » |
| `0038` | Lignes « non fait » d'une séance de maintenance reliées à leur séance ; titres d'historique sans le type répété |
| `0039` | Essais de connexion lents (`users.slow_failed_login_attempts`, `slow_window_started_at`, `lock_admits_known_only`) ; adresse d'origine des liens de réinitialisation (`password_reset_tokens.requested_ip`) ; essais du changement de mot de passe par session (`auth_sessions.password_failures`) |
| `0040` | Compteurs partagés entre processus (`shared_counter`) : budgets du catalogue logiciel |
| `0041` | Jeton d'enrôlement jamais utilisé (`machines.enrollment_token_unused`), faux pour tous les postes existants |
| `0042` | Période du résumé et du rappel déjà servie le jour de la mise à jour (`app_settings`, `worker.last_run.*`) ; rien sur une installation neuve |
| `0043` | Noms de salle et de bâtiment uniques à la casse près (doublons renommés « (2) »…) |
| `0044` | Fin du verrou des essais lents (`users.slow_locked_until`) ; `users.lock_admits_known_only` supprimée |
| `0045` | Langue du compte (`users.language`), nulle pour les comptes existants : « celle du navigateur » |
| `0046` | Code des verdicts de commande (`commands.result_code`, `result_params`), nul pour les commandes existantes |
| `0047` | Code des textes écrits par le serveur dans le journal des interventions (`interventions.title_code`, `title_params`) et à la clôture d'une vérification (`machine_checks.closing_note_code`) |

Le backend applique les migrations à son démarrage.

# Tia'i v1.2.0

Cette version réunit tout ce qui a été fusionné depuis la v1.1.0 (2 octobre 2026) :

- le déploiement logiciel ;
- les groupes limités par emplacement ;
- le premier audit de sécurité ;
- les corrections de l'audit 2026-11, qui portait sur la sécurité, les bugs et l'interface (43 tâches).

Elle contient six migrations de base (`0026` à `0031`). **Plusieurs étapes sont obligatoires avant de mettre à jour : lisez la première section.**

---

## À faire avant de mettre à jour

### Serveur

1. **Faire un dump de la base**, comme décrit dans `DEPLOYMENT.md` § « Mettre à jour le serveur ». La migration `0031` recalcule la date de dernière maintenance de tout le parc. Pour revenir en arrière, il faut restaurer ce dump.
2. **Créer le rôle applicatif PostgreSQL.**
   - Ajouter `POSTGRES_APP_PASSWORD` au `.env` ; sans lui, `docker compose up` s'arrête.
   - Sur une base existante, **avant** de changer `TIAI_VERSION`, lancer :
     `docker compose up -d db && docker compose exec db sh /docker-entrypoint-initdb.d/10-app-role.sh`.
     Sans ce rôle, le backend refuse de démarrer, car il ne tourne plus en superutilisateur.
3. **Vérifier la longueur des secrets.** Hors environnement `local`, le serveur refuse de démarrer si l'un de ces secrets est trop court :

   | Secret | Longueur minimale |
   |---|---|
   | `SECRET_KEY` | 32 caractères |
   | `ENROLLMENT_SECRET` | 16 caractères |
   | `FIRST_ADMIN_PASSWORD` | 12 caractères (`PASSWORD_MIN_LENGTH`) |

   `ENVIRONMENT` vaut désormais `production` par défaut.
4. **Reverse proxy.** L'API ne croit plus l'en-tête `X-Forwarded-For` que s'il vient d'un proxy de confiance : Caddy par défaut (`TRUSTED_PROXY_HOSTS=caddy`). Avec un autre proxy devant l'API, renseigner son adresse dans `TRUSTED_PROXIES`. Sinon, toutes les requêtes semblent venir du proxy : journal d'audit faux et limites de débit partagées.
5. **Volume des paquets.** Le nouveau volume Docker `packages` n'est pas inclus dans le dump PostgreSQL : il faut le sauvegarder à part.
6. **Conteneurs sans root.** Le backend et le worker tournent désormais sous le compte `tiai`, sans capacité. Au premier démarrage, le backend attribue le volume `packages` à ce compte. Rien n'est à faire avec le `docker-compose.yml` fourni. Une stack personnalisée doit garder les capacités `CHOWN`, `SETUID` et `SETGID`, utilisées au démarrage seulement.

### Agent : mettre à jour le parc

Les protections côté poste (T01, T02, T10, T37) n'agissent **qu'après la mise à jour de l'agent**. Il faut donc diffuser le MSI de cette release par GPO. Cette version embarque aussi Go 1.27.4, qui corrige une faille du client HTTP.

> ⚠️ **Parc installé en `http://` (mode A sans certificat)** : l'agent refuse désormais une adresse `http://`.
> **Avant** de diffuser la mise à jour, poser `AllowInsecureHTTP` (`REG_DWORD` = 1) sous `HKLM\SOFTWARE\Tiai` par GPO, ou `allow_insecure_http: true` dans le YAML.
> Sans cela, les postes mis à jour cessent de contacter le serveur. Un avertissement est écrit dans le journal de l'agent à chaque démarrage tant que l'option est active.

En attendant que tout le parc soit à jour, **n'activez pas `DeployPublishers`** (méthode A du déploiement) sur de nouveaux postes.

---

## Nouveautés

### Déploiement logiciel

Le bouton « Installer un logiciel » est disponible sur un poste, une sélection, un site ou tout le parc. Chacune des trois méthodes reste **coupée tant qu'une GPO ne l'ouvre pas** (`HKLM\SOFTWARE\Tiai`) :

| Méthode | Clé GPO |
|---|---|
| winget | `DeployWinget`, et `DeployWingetAllow` en option |
| Paquet signé par l'administrateur (méthode B) | `DeploySigners` |
| Exécutable d'un éditeur approuvé (méthode A, repli) | `DeployPublishers` |

- Nouvelle page Paquets. La fiche d'un paquet regroupe ses fichiers, sa signature, ses règles de confiance et le suivi de ses déploiements, avec un bilan par statut et un tableau paginé.
- Le script `deploy/packages/Sign-TiaiPackage.ps1` signe le manifeste hors du serveur ; le guide est dans `deploy/packages/README.md`.
- Un paquet installé est figé au moment de la mise en file. S'il est modifié entre-temps, la commande échoue et invite à relancer.
- Une installation que ni la signature ni l'éditeur ne couvre est refusée dès la console. « Tout le parc » et les désinstallations demandent une confirmation qui annonce le nombre de postes.
- Les dépôts de fichiers sont acceptés jusqu'à 2 Gio, avec barre de progression et bouton d'annulation.

### Groupes limités par emplacement

- Un groupe peut être restreint à des sites, bâtiments ou salles. Un compte voit l'union des périmètres de ses groupes.
- Un groupe sans restriction voit tout le parc : les groupes existants sont inchangés.
- Le périmètre s'applique partout : postes, exports, commandes, menaces, tableau de bord, logiciels, salles, vérifications, maintenance, réveil, courriels et journal d'audit.

### Ré-enrôlement soumis à approbation

- Un poste déjà enrôlé qui redemande un jeton, par exemple après une réinstallation, attend désormais l'approbation d'un administrateur. Sa fiche affiche un bandeau avec le bouton « Autoriser ».
- `ENROLLMENT_SECRET_PREVIOUS` permet de changer le secret d'enrôlement sans couper les enrôlements en cours.

### Console

- La liste des postes s'ouvre avec moins de colonnes : Nom, Salle, Maintenance, Antivirus, MAJ Windows, Session et Vu le. Les autres restent disponibles dans « Colonnes ». La case de sélection et le nom restent visibles quand on fait défiler la liste horizontalement.
- Page Logiciels :
  - la recherche, le tri et la page sont conservés dans l'URL, donc au retour arrière ;
  - le filtre « Logiciel » de la liste des postes nomme le programme.
- Thème sombre automatique et nombreuses améliorations d'accessibilité : navigation au clavier, libellés pour les lecteurs d'écran, confirmations qui nomment leur action (« Révoquer », « Redémarrer 12 postes »).
- Mes tâches et séance de maintenance :
  - seuls les postes réellement dus sont présélectionnés ;
  - « Me l'affecter » et « Transmettre » sont disponibles ;
  - le badge distingue les vérifications et les postes en retard.
- Une saisie en cours n'est plus perdue :
  - fiche paquet et paramètres : signalement des modifications non enregistrées et confirmation en quittant la page ;
  - séance de maintenance : confirmation avant d'annuler une saisie.
- Les erreurs de chargement sont signalées par un bandeau au lieu de laisser des données périmées ou une liste vide trompeuse.

---

## Changements de comportement à annoncer aux utilisateurs

- **Verrouillage de compte.**
  - Après 5 échecs (`LOGIN_MAX_FAILED_ATTEMPTS`), le compte est verrouillé 15 minutes (`LOGIN_LOCKOUT_MINUTES`), mais **seulement pour les adresses qui ont échoué**. Le titulaire qui se connecte d'ailleurs avec le bon mot de passe entre normalement, et cela lève le verrou. Un attaquant ne peut donc plus bloquer un compte à distance.
  - Le verrou répond comme un mot de passe faux, sans message distinct.
  - Une réinitialisation de mot de passe lève aussi le verrou. La page Utilisateurs affiche « Verrouillé ».
- **Changement de mot de passe.**
  - Il est limité à 5 essais par 15 minutes.
  - Un mauvais mot de passe actuel compte comme un échec de connexion. S'il verrouille le compte, toutes ses sessions sont fermées.
- **Mot de passe oublié.** Redemander un lien moins de 5 minutes après le précédent n'envoie pas de nouveau courriel ; le lien déjà reçu reste valable.
- **Administrateurs délégués (comptes à périmètre restreint)** : certaines opérations jusqu'ici permises sont refusées, avec un message explicite.
  - Modifier les permissions ou le périmètre d'un groupe dont on n'a pas soi-même les droits.
  - Déplacer un bâtiment ou une salle vers un site hors de son périmètre (`auth.scope.restricted`).
  - Affecter une vérification à un compte qui ne voit pas le poste (`check.assignee.out_of_reach`).
  - Le journal d'audit n'affiche plus que les entrées sur les postes du périmètre et ses propres actions.
- **Paramètres e-mail.** Changer l'hôte, le port, l'utilisateur ou le domaine d'envoi impose de ressaisir le mot de passe SMTP ou la clé Mailgun. Le secret enregistré n'est plus envoyé vers une nouvelle destination. Désactiver la vérification du certificat SMTP compte aussi comme un changement de destination.
- **Commandes sans réponse.** Une commande remise ou en cours depuis plus de 24 heures (`COMMAND_UNANSWERED_HOURS`) passe en échec « sans réponse du poste ». Un verdict tardif du poste l'emporte.
- **Maintenance.**
  - La date de dernière maintenance est désormais recalculée à partir du journal ; la migration `0031` la corrige une fois pour tout le parc.
  - Une date d'intervention dans le futur est refusée.
  - Un responsable désactivé ne bloque plus la maintenance : il est sauté.
- **Salles créées automatiquement (mode annuaire).**
  - Un poste n'adopte plus une salle créée à la main du même nom : il reste sans salle jusqu'à la resynchronisation lancée par un administrateur.
  - En mode `ad_ou`, un poste n'est rangé que si l'OU qu'il rapporte contient bien son DN.
  - La création automatique est plafonnée à 200 salles par heure.
- **Suppression d'un bâtiment.** Une salle dont le nom existe déjà ailleurs est renommée, par exemple « Salle 101 (Bâtiment B) », et le renommage est noté au journal d'audit.
- **Réveil (Wake-on-LAN).**
  - Un poste ne sert de relais qu'une fois enrôlé depuis au moins 60 minutes, avec un jeton valide et une identité confirmée.
  - Le réveil direct ne vise que des adresses privées, ou les réseaux listés dans `WOL_ALLOWED_NETWORKS`.
- **Fréquence des contacts.** Un poste est limité à 30 contacts par minute ; au-delà, le serveur répond 429. L'agent en fait un par minute par défaut, la marge est donc large.
- **Documentation de l'API.** L'interface OpenAPI (`/docs`) est désactivée hors environnement `local`. `EXPOSE_OPENAPI=true` la rétablit.

---

## Sécurité

L'audit 2026-11 a retenu 102 constats ; tous sont corrigés dans cette version. Les principaux :

- **Agent** :
  - un identifiant de paquet qui n'est pas un UUID est refusé ;
  - en méthode A, plus aucun fichier chargeable non signé ne peut accompagner l'exécutable ;
  - aucune redirection HTTP n'est suivie, ce qui évite de renvoyer le secret d'enrôlement ;
  - les téléchargements sont bornés à la taille annoncée ;
  - le journal tourne pendant que le service fonctionne ;
  - `http://` n'est accepté que sur option explicite.
- **Serveur** :
  - escalade de périmètre par les groupes fermée ;
  - séance de maintenance et journal d'audit filtrés par périmètre ;
  - caractères de contrôle refusés dans les paquets ;
  - jokers SQL neutralisés dans toutes les recherches ;
  - exports CSV et Excel protégés contre les formules et les caractères invalides.
- **Infrastructure** :
  - conteneurs sans root ni capacité ;
  - base de données utilisée sans superutilisateur ;
  - sauvegardes lisibles du seul propriétaire ;
  - nginx 1.30 avec les mises à jour Alpine appliquées à chaque construction ;
  - actions GitHub épinglées par empreinte ;
  - nouveau workflow de sécurité : gitleaks, pip-audit, npm audit, govulncheck, Semgrep, et Trivy sur les deux images.

> **Écart connu** : les sauvegardes ne sont pas chiffrées dans le conteneur, dont l'image n'a pas d'outil de chiffrement. La copie stockée hors du serveur doit l'être ; voir `DEPLOYMENT.md` § « Sauvegardes et restauration ».

---

## Nouvelles variables d'environnement

| Variable | Défaut | Rôle |
|---|---|---|
| `POSTGRES_APP_PASSWORD` | — (obligatoire) | Mot de passe du rôle applicatif PostgreSQL |
| `ENROLLMENT_SECRET_PREVIOUS` | vide | Ancien secret d'enrôlement, accepté pendant une rotation |
| `TRUSTED_PROXIES` | vide | Adresses ou réseaux de proxys de confiance en plus de Caddy |
| `TRUSTED_PROXY_HOSTS` | `caddy` | Noms d'hôte des proxys de confiance |
| `EXPOSE_OPENAPI` | `false` | Expose `/docs` hors environnement `local` |
| `COMMAND_UNANSWERED_HOURS` | `24` | Délai avant qu'une commande sans réponse passe en échec |
| `WOL_RELAY_MIN_AGE_MINUTES` | `60` | Ancienneté minimale d'un poste relais |
| `WOL_RELAY_MIN_AGENT_VERSION` | `1.0.0` | Version minimale de l'agent relais |
| `WOL_RELAY_CLAIM_TIMEOUT_SECONDS` | `180` | Délai avant qu'un réveil pris sans réponse revienne en file |
| `WOL_ALLOWED_NETWORKS` | vide | Réseaux publics autorisés pour le réveil direct |
| `PACKAGE_MAX_BYTES` | 2 Gio | Taille maximale d'un fichier de paquet |
| `PACKAGE_MAX_CONCURRENT_DOWNLOADS` | `20` | Téléchargements simultanés de paquets |
| `TIAI_DEV_BACKEND_BIND` | `127.0.0.1` | Stack de développement seulement : adresse du port de l'API |

Clé de registre de l'agent : `AllowInsecureHTTP` (`REG_DWORD`), voir plus haut.

## Migrations

| Migration | Contenu |
|---|---|
| `0026` | Index uniques sur les jetons des postes |
| `0027` | Verrouillage de compte, demandes de ré-enrôlement, adresse IP dans le journal d'audit |
| `0028` | Périmètres de groupe (`group_scopes`) |
| `0029` | Paquets et fichiers de paquet |
| `0030` | Contenu du paquet figé sur la commande |
| `0031` | Recalcul unique de la dernière maintenance de chaque poste |

Le backend applique les migrations à son démarrage.

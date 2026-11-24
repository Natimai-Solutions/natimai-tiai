# Lecture de l'annuaire par le serveur — plan de travail

> **Statut : mode `relay` livré avec C5** (L1 pour le modèle, L2, L3 ; le
> 2026-11-21, §10). Restent le mode `ldap` (client LDAP du serveur) et L4
> (relais Wake-on-LAN vérifiés), côté serveur seulement. Rédigé le 2026-11-16,
> décisions du 2026-11-18 au §9. Répond aux constats S19 et S20 de l'audit 2026-11, acceptés en limite
> au §6.4 de `plan-audit-2026-11.md` (« Emplacement et annuaire déclaratifs »).
>
> Objectif : que l'emplacement d'un poste, son OU et l'attribut *Emplacement*
> de son objet ordinateur ne soient plus **crus sur parole** quand ils décident
> de quelque chose : la salle où le poste est rangé (et donc qui le voit), et
> les réveils qu'il relaie.

---

## 1. Le problème

Trois valeurs déclarées par l'agent pèsent aujourd'hui sur des décisions du
serveur :

| Valeur déclarée | Ce qu'elle décide | Constat |
|---|---|---|
| `location` (emplacement, YAML ou registre posé par GPO) et `ip_address` / `ip_prefix_length` | Quels postes peuvent relayer un réveil d'un site (`wol/relay.py`, `shares_wire`) | S19 |
| `directory.distinguished_name`, `directory.ou`, `directory.ad_location` | La salle du poste en mode `ROOM_SOURCE=ad_ou` ou `ad_location`, donc le périmètre des comptes limités à cette salle et les alertes qu'ils reçoivent | S20 |

Les corrections de l'audit ont réduit l'exposition sans la supprimer :
- relais exigeant une version d'agent récente, une ancienneté minimale et
  libéré s'il ne répond pas ;
- DN qui doit nommer le poste ;
- salle manuelle reprise seulement à la majorité, après aperçu et
  confirmation ;
- budgets de création.

Il reste qu'un poste forgé (enrôlé avec le secret du parc) peut encore
annoncer l'emplacement d'un autre site ou un DN cohérent, et que la majorité
se gagne avec un poste forgé de plus que de postes honnêtes.

La seule source qui fait foi est l'annuaire lui-même. Le serveur doit donc le
lire, ou le faire lire par quelqu'un en qui il a confiance.

## 2. Contrainte de départ : où est le serveur ?

`plan-projet-tiai.md` §8 décrit un serveur **interne**, sans exposition
Internet. `plan-salles-maintenance-interventions.md` §3 écartait pourtant la
lecture LDAP côté serveur « pour un serveur hébergé hors site », cas pour
lequel le relais Wake-on-LAN existe. Les deux déploiements doivent être
couverts :

- **Serveur avec une route vers un contrôleur de domaine** (même réseau, VPN
  site à site) : lecture LDAP directe, §3.1. **Un seul domaine** dans ce cas.
- **Serveur sans route** (hébergé dans le cloud, plusieurs établissements
  gérés) : lecture déléguée à des postes désignés, §3.2. **Plusieurs
  domaines** peuvent cohabiter sur le même serveur, et la plupart des sites
  n'ont **pas d'adresse de sortie fixe**.

## 3. Deux modes de lecture, un seul modèle

### 3.1 Mode `ldap` — le serveur interroge l'annuaire

- **Bibliothèque** : `ldap3` (Python pur, pas de dépendance système), appelée
  dans un thread pour ne pas bloquer la boucle de l'API, et en pratique depuis
  le **worker**, pas depuis les requêtes.
- **Connexion** : LDAPS (636) ou StartTLS, certificat vérifié (AC de
  l'établissement fournie par fichier). Le LDAP en clair est refusé au
  démarrage, sauf option explicite comme `AllowInsecureHTTP` côté agent.
- **Un seul domaine** : une connexion, une base. Plusieurs domaines relèvent
  du mode `relay`.
- **Compte** : un compte de service AD en **lecture seule**, sans aucun droit
  au-delà de la lecture des objets ordinateurs, des OU et de la configuration
  des sites. **Bind simple sur LDAPS** (décision du 2026-11-18) ; Kerberos
  n'est pas prévu pour l'instant. Mot de passe
  dans le `.env`, jamais affiché par la page Paramètres (même règle que les
  secrets SMTP).
- **Ce qui est lu**, par recherche paginée, sur toute la base des ordinateurs
  à intervalle fixe (`DIRECTORY_SYNC_MINUTES`, 60 par défaut) puis en
  incrémental sur `uSNChanged` ou `whenChanged` :
  - `sAMAccountName` (`PC-B12-03$`), `dNSHostName`, `objectGUID` ;
  - `distinguishedName` (donc l'OU parente) ;
  - `location` (onglet « Emplacement ») ;
  - `userAccountControl`, pour reconnaître un compte ordinateur désactivé.
- **Sites AD** : `CN=Subnets,CN=Sites,CN=Configuration,…` donne la
  correspondance sous-réseau → site. Elle sert au §4.2.
- **Volume** : quelques milliers d'objets, une recherche paginée de quelques
  secondes par heure. Négligeable.

### 3.2 Mode `relay` — des postes désignés lisent pour les autres

Pour un serveur sans route vers un DC. Même idée que le relais Wake-on-LAN,
avec une confiance **explicite** au lieu d'une confiance par emplacement.

**Désignation**
- Un administrateur **désigne** dans la console un ou plusieurs postes
  « lecteurs d'annuaire » : un serveur membre ou un poste d'administration
  toujours allumé, jamais un poste élève. Droit `settings:write`, action
  journalisée, révocable.
- La désignation porte sur le poste enrôlé (son identifiant), pas sur son
  nom. Elle **tombe d'elle-même** si le poste est ré-enrôlé, si son token est
  révoqué ou s'il passe en « Identité à confirmer ».

**Lecture**
- L'agent du lecteur interroge l'annuaire en ADSI (déjà utilisé pour
  l'attribut `location`, §3 du plan salles) avec le **compte machine** du
  poste : ni compte de service, ni mot de passe à stocker.
- Le serveur lui confie une commande `directory_read` avec la liste des noms
  des postes enrôlés qui déclarent son domaine. Le lecteur renvoie les mêmes
  attributs que le §3.1, plus l'identité de son domaine (nom DNS et SID) et
  la table sous-réseaux → sites.
- Seuls les lecteurs ont besoin du nouvel agent.

**Plusieurs domaines sur un même serveur**
- Un lecteur ne lit et ne répond **que pour son propre domaine**. Chaque
  domaine a donc besoin d'au moins un lecteur ; un domaine sans lecteur reste
  dans le comportement actuel, et la page Paramètres le dit.
- Un domaine est identifié par son **SID**, pas par son nom DNS : deux
  établissements peuvent avoir le même nom de domaine (`ecole.local`).
- Si deux domaines de même nom ont chacun un poste du même nom, le poste
  enrôlé ne peut pas être rattaché à l'un plutôt qu'à l'autre : il reste
  `unknown` et est signalé, jusqu'à ce qu'un administrateur tranche.

**Garde-fous contre un lecteur qui ment**
- **Limite** : un lecteur désigné compromis ment pour tout son domaine.
- Quand un domaine a deux lecteurs, leurs réponses sont comparées. En cas de
  désaccord, rien ne change et une alerte est levée.
- Une lecture qui déplacerait plus de `DIRECTORY_CONFIRM_MOVES` postes d'un
  coup attend la confirmation d'un administrateur, avec l'aperçu déjà utilisé
  pour la resynchronisation des salles.
- Chaque changement de salle issu d'une lecture nomme le lecteur au journal.

### 3.3 Le modèle commun

Une table `directory_records`, une ligne par objet ordinateur vu dans
l'annuaire :

| Colonne | Rôle |
|---|---|
| `object_guid` | Clé stable (un poste renommé garde son GUID) |
| `domain_sid`, `domain` | Le domaine lu : son SID l'identifie, son nom DNS l'affiche |
| `sam_account_name`, `dns_host_name` | Pour rapprocher l'objet du poste |
| `distinguished_name`, `ou`, `location` | Ce que l'annuaire dit |
| `disabled` | Compte ordinateur désactivé dans AD |
| `source` | `ldap` ou `relay:<machine_id>` |
| `read_at` | Date de la lecture |

Sur `machines`, deux colonnes :
- `directory_object_guid` : le rapprochement retenu ;
- `directory_status` : `verified`, `mismatch`, `unknown` ou `stale`.

**Rapprochement d'un poste et d'un objet** : même domaine, et
`sAMAccountName = hostname + '$'` (ou `dNSHostName` = FQDN déclaré).
- Un objet que deux postes réclament n'est attribué à aucun et signale les
  deux postes en « Identité à confirmer », comme une empreinte suspecte.
- Un poste déjà rapproché qui change de nom garde son GUID et le serveur
  relit l'objet.

**Limite du rapprochement, dans les deux modes.** Lire l'annuaire prouve ce
que l'annuaire dit d'un nom, pas que le poste *est* ce nom : le nom vient de
l'agent. Un poste forgé peut donc encore prendre le nom d'un poste réel pas
encore enrôlé, et être rangé à sa place. Les protections de l'enrôlement
(empreinte, ré-enrôlement soumis à approbation) couvrent les postes déjà
enrôlés. Fermer complètement ce trou demande une preuve d'identité du compte
machine (Kerberos) ; elle n'est pas dans ce plan, et sa faisabilité côté
agent n'a pas été vérifiée.

## 4. Ce que la lecture change

### 4.1 Salles (S20)

Avec `DIRECTORY_VERIFY=ldap` ou `relay` et `ROOM_SOURCE=ad_*` :
- **le serveur range le poste d'après l'enregistrement d'annuaire**, plus
  d'après le bloc `directory` du heartbeat. Le bloc envoyé par l'agent reste
  stocké et affiché, comme indice ;
- un écart entre les deux passe le poste en `mismatch` : badge sur la fiche,
  filtre dans la liste, ligne au journal d'audit. L'écart est **signalé, pas
  bloquant** (décision du 2026-11-18) : un poste déplacé dans AD et pas encore
  redémarré a un DN local en retard ;
- un poste sans enregistrement (`unknown`) reste où il est et ne crée pas de
  salle. Les salles ne se créent plus qu'à partir de l'annuaire lu ;
- le vote à la majorité de T36 devient inutile dans ce mode : le DN de l'OU
  lue est la clé de la salle ;
- avec plusieurs domaines, **la clé d'une salle inclut le domaine** (son SID).
  Aujourd'hui `rooms.ad_key` est unique sur tout le serveur : en mode
  `ad_location`, deux établissements qui ont chacun une « Salle 101 »
  partageraient la même salle. Les clés existantes sont réécrites à la
  première lecture vérifiée de leur domaine.

### 4.2 Relais Wake-on-LAN (S19)

La question est : ce poste est-il réellement sur le site de la cible ? Son
emplacement et son adresse sont déclarés ; le serveur les confronte à ce
qu'il **observe lui-même**, l'adresse source de la connexion (`client_ip`).

- **Mode `ldap`** (serveur sur le réseau des postes ou relié par VPN) :
  l'adresse source est l'adresse du poste. Elle doit être égale à l'adresse
  déclarée ; son sous-réseau donne le site AD (table sous-réseaux → sites).
- **Mode `relay`** (serveur dans le cloud) : le serveur ne voit que l'adresse
  de sortie Internet du site, et la plupart des sites n'en ont pas de fixe
  (décision du 2026-11-18 : pas de liste d'adresses à tenir à jour). Le
  serveur l'**apprend du lecteur d'annuaire** : un poste dont l'adresse
  source est celle d'un lecteur de son domaine, vue dans les
  `DIRECTORY_SITE_WINDOW_MINUTES` dernières minutes, est « sur site ». Une
  adresse qui change est suivie sans intervention.
- **Relais** : les postes `verified` et sur le site vérifié de la cible
  passent en premier. Les autres **passent après** (décision du 2026-11-18),
  comme les postes d'un autre sous-réseau aujourd'hui : ils attendent un
  délai, puis prennent le réveil si aucun relais vérifié ne l'a pris. Le
  résultat du réveil dit alors qu'il a été relayé par un poste non vérifié.
  `WOL_RELAY_VERIFIED_ONLY=true` les écarte au lieu de les faire attendre.
- L'emplacement déclaré par l'agent reste l'emplacement affiché et filtrable.
- **Sans vérification possible** (mode désactivé, annuaire injoignable, aucun
  lecteur en ligne) : le comportement actuel est conservé et la page
  Paramètres dit que les relais reposent sur l'emplacement déclaré.

Limites de l'adresse apprise :
- un site qui sort par plusieurs accès Internet ne reconnaît que les postes
  qui sortent par le même accès qu'un lecteur ;
- une adresse de sortie partagée entre plusieurs abonnés (CGNAT) fait
  reconnaître « sur site » un poste d'un autre abonné du même opérateur ;
- le serveur doit garder la dernière adresse source de chaque poste, qu'il
  ne stocke pas aujourd'hui.

### 4.3 Comptes désactivés et postes supprimés de l'annuaire

Un objet ordinateur désactivé ou supprimé de l'annuaire passe le poste en
`stale` : signalé, exclu des relais, sans révocation automatique du token. La
révocation reste une décision humaine, proposée en un clic depuis le filtre.

## 5. Configuration

| Variable | Défaut | Rôle |
|---|---|---|
| `DIRECTORY_VERIFY` | `off` | `off`, `ldap` ou `relay` |
| `LDAP_URL` | — | `ldaps://dc1.lycee.local` ; plusieurs URL du **même domaine** séparées par des virgules, essayées dans l'ordre |
| `LDAP_BIND_DN`, `LDAP_BIND_PASSWORD` | — | Compte de service en lecture seule |
| `LDAP_BASE_DN` | — | Racine des objets ordinateurs, par exemple `OU=Postes,DC=lycee,DC=local` |
| `LDAP_CA_FILE` | — | AC qui a signé le certificat du DC |
| `LDAP_ALLOW_PLAINTEXT` | `false` | Refusé sans cette option : `ldap://` sans StartTLS |
| `DIRECTORY_SYNC_MINUTES` | `60` | Intervalle des lectures complètes |
| `DIRECTORY_STALE_HOURS` | `72` | Au-delà, un enregistrement non relu est `stale` et ne vérifie plus rien |
| `DIRECTORY_CONFIRM_MOVES` | `20` | Mode `relay` : au-delà de ce nombre de postes déplacés par une lecture, confirmation d'un administrateur (§3.2) |
| `DIRECTORY_SITE_WINDOW_MINUTES` | `30` | Mode `relay` : durée pendant laquelle l'adresse source d'un lecteur désigne son site (§4.2) |
| `WOL_RELAY_VERIFIED_ONLY` | `false` | `false` : un relais non vérifié passe après les relais vérifiés ; `true` : il est écarté (§4.2) |

Ces valeurs sont contrôlées au démarrage, avec les mêmes bornes que le reste
du `.env`. La page Paramètres les affiche, sans le mot de passe.

## 6. Console

- **Paramètres → Annuaire** :
  - mode, dernière lecture réussie, nombre d'objets lus, erreurs ;
  - bouton « Tester la connexion » (comme l'e-mail de test), avec un message
    distinct pour : DC injoignable, certificat refusé, identifiants refusés,
    base introuvable.
- **Fiche** : bloc « Annuaire » qui montre côte à côte ce que l'agent déclare
  et ce que l'annuaire dit, avec le statut et la date de lecture.
- **Liste des postes** : filtre « Annuaire : vérifié / écart / inconnu /
  périmé ».
- **Mode `relay`** : action « Désigner comme lecteur d'annuaire » sur la fiche
  (droit `settings:write`). Paramètres liste les domaines connus, leurs
  lecteurs, la dernière lecture de chacun et les domaines sans lecteur.

## 7. Sécurité

- Compte de service en lecture seule, documenté avec la délégation minimale
  dans `DEPLOYMENT.md`. Aucune écriture dans l'annuaire, jamais.
- TLS obligatoire et certificat vérifié.
- Le mot de passe du compte ne quitte jamais le serveur : pas d'API qui le
  renvoie, pas de journal qui l'écrit, et une erreur LDAP est réécrite avant
  d'être journalisée.
- Lecture bornée en temps et en volume (pagination, délai par requête). Un
  annuaire lent retarde la synchronisation, jamais l'API.
- Mode `relay` : désignation auditée, réponses limitées au domaine du lecteur,
  et commande `directory_read` refusée par tout poste non désigné (côté
  serveur ; l'agent n'a pas à le savoir).

## 8. Jalons

| Jalon | Contenu | Estimation |
|---|---|---|
| **L1 — Modèle et lecture LDAP** | Table, colonnes et migration ; client `ldap3` ; lecture complète et incrémentale dans le worker ; rapprochement ; « Tester la connexion ». Tests contre un annuaire de test (`slapd` avec un schéma réduit imitant AD sur le banc) et tests unitaires du rapprochement. | 3 j |
| **L2 — Salles vérifiées** | Placement d'après l'enregistrement, statut `mismatch`, fiche et filtre, aperçu de resynchronisation qui montre les écarts, clé de salle par domaine. | 2 j |
| **L3 — Mode `relay`** | Désignation et sa révocation automatique, commande `directory_read`, lecture ADSI côté agent, domaines identifiés par SID, comparaison de deux lecteurs, confirmation des déplacements en masse. | 4 j + validation sur un domaine réel (comme le bind ADSI de J3) |
| **L4 — Relais vérifiés** | Adresse source gardée par poste, sous-réseaux et sites (mode `ldap`), adresse apprise du lecteur (mode `relay`), ordre des relais. | 2 j |
| **L5 — Documentation et recette** | `DEPLOYMENT.md` (compte de service, AC, choix des lecteurs, dépannage), notes de version, recette sur le banc et sur un domaine réel. | 1 j |

Les deux déploiements sont à couvrir. L1 et L2 suffisent à ranger les salles
d'un serveur qui voit un DC ; L3 apporte la même chose à un serveur hébergé
ailleurs, et L4 dépend de L3 pour ce cas.

## 9. Décisions du 2026-11-18

1. **Les deux déploiements sont pris en charge** : serveur qui voit un DC
   (mode `ldap`) et serveur sans route (mode `relay`).
2. **Domaines** : un seul en mode `ldap` ; plusieurs possibles en mode
   `relay` (serveur dans le cloud qui gère plusieurs établissements).
3. **Compte de service** (mode `ldap`) : bind simple sur LDAPS. Pas de
   Kerberos pour l'instant.
4. **Adresses de sortie** : la plupart des sites n'en ont pas de fixe. La
   liste `WOL_SITE_EGRESS` envisagée est abandonnée au profit de l'adresse
   apprise du lecteur (§4.2).
5. **Écart annuaire / agent** : signalé, pas bloquant.
6. **Relais non vérifiés** : passés après les relais vérifiés, pas écartés.
   L'adresse apprise est un signal qui peut manquer (lecteur éteint, adresse
   qui vient de changer, site à plusieurs accès), et un site ne doit pas
   perdre ses réveils pour autant. Le risque qui reste est celui de S19 : un
   poste forgé apprend l'adresse MAC de la cible et ne la réveille pas.
   `WOL_RELAY_VERIFIED_ONLY=true` permet de les écarter.

## 10. Livré le 2026-11-21 (mode `relay`, avec C5)

Livré avec la version d'agent de C5, comme le demandait
`plan-evolutions-itil.md` §7, pour ne redéployer qu'une fois.

- **Modèle** (`0053_directory`) : `directory_domains` (clé : SID ; nom DNS et
  **nom NetBIOS**, ajouté au plan : c'est ce que les agents déclarent comme
  domaine, `NetGetJoinInformation`, donc ce par quoi un poste est rattaché à
  un domaine), `directory_records` (clé : lecteur × `objectGUID`, pour
  comparer deux lecteurs), et sur `machines` l'objet rapproché, le statut, la
  lecture (`dir_*`) et la désignation.
- **Lecteurs** : désignation et retrait depuis la fiche (onglet Identité),
  journalisés ; la désignation tombe au ré-enrôlement, à la révocation du
  jeton ou au passage en « Identité à confirmer » (vérifié par le worker, et
  à l'enrôlement).
- **Commande `directory_read`** : mise en file par la tâche `sync_directory`
  du worker (une à la fois par lecteur, toutes les `DIRECTORY_SYNC_MINUTES`),
  refusée par `POST /commands` et par les planifications. Les noms à lire
  sont calculés à la remise, pas stockés. La lecture revient sur
  `POST /agent/directory/{commande}`, puis le résultat de la commande comme
  pour toute autre.
- **Agent** : PowerShell `System.DirectoryServices` (ce qu'est
  `[adsisearcher]`), plutôt qu'ADSI par COM comme pour l'attribut `location` :
  une recherche paginée de quelques milliers d'objets s'écrit en quelques
  lignes et passe par le même lanceur que Windows Update. Filtres par lots de
  200 noms, noms limités à `[A-Za-z0-9-]` avant d'entrer dans un filtre LDAP,
  5 minutes au plus. **À valider sur un domaine réel**, comme le bind ADSI de J3.
- **Comparaison de deux lecteurs** : un désaccord sur un seul objet gèle
  tout le domaine (pas seulement l'objet), un lecteur menteur pouvant choisir
  ses objets.
- **Salles** : en mode `relay`, la clé d'une salle est `SID|DN de l'OU` (ou
  `SID|emplacement`), hachée au-delà de 500 caractères ; une salle de
  l'ancienne clé est reprise à la première lecture. Le heartbeat ne range plus
  rien d'après la déclaration de l'agent : il ne fait que réévaluer le statut.
- **Déplacements en masse** : retenus au-delà de `DIRECTORY_CONFIRM_MOVES`,
  appliqués ou écartés depuis Paramètres → Annuaire. Écarter ne les annule
  que jusqu'à la lecture suivante, qui les retient de nouveau si l'annuaire
  le dit toujours.
- **Non fait** : mode `ldap` et « Tester la connexion » (L1, serveur seul),
  relais Wake-on-LAN vérifiés et adresse source gardée par poste (L4, serveur
  seul), proposition de révocation du jeton en un clic depuis le filtre
  « périmé » (le filtre existe, la révocation reste sur la fiche).

## 11. Durcissement après relecture (2026-11-24)

Une relecture indépendante a montré, tests à l'appui, que plusieurs garde-fous
du §3.2 se contournaient. Corrigé, avec un test par point
(`backend/tests/test_directory.py`) :

- **Un lecteur est lié à son domaine et à son SID.** La désignation retient
  le domaine déclaré à ce moment-là et le SID de la première lecture. Un
  lecteur qui se met à déclarer un autre domaine perd sa désignation ; une
  lecture sous un autre SID est refusée.
- **Un nom NetBIOS désigne un seul domaine** (index unique). **Écart au
  §3.2** : deux domaines de même nom NetBIOS sur un même serveur ne sont
  plus pris en charge. Les agents ne déclarent que ce nom ; rien ne permet
  de dire à quel domaine appartient un poste, et un lecteur qui inventait
  un second SID faisait repasser « inconnus » les postes du premier. Un
  domaine reconstruit sous un autre SID se retire depuis Paramètres →
  Annuaire (« Oublier ce domaine »).
- **Un nom réclamé par deux postes** : statut « contesté » pour les deux,
  journalisé, sans les passer en « Identité à confirmer ». Un poste forgé
  qui prenait le nom d'un lecteur lui faisait perdre sa désignation, et
  bloquait n'importe quel poste pas encore rapproché. Un poste au jeton
  révoqué ne réclame plus rien. Le rapprochement se fait par le nom, le
  GUID ne servant qu'à un poste renommé : le premier arrivé ne garde plus
  un objet contre un second réclamant.
- **Une commande, une lecture.** La lecture fait passer la commande « en
  cours » ; une seconde réponse à la même commande est refusée, comme une
  réponse à une commande remise depuis plus de 30 minutes. Le seuil
  `DIRECTORY_CONFIRM_MOVES` ne se franchit plus par petites lectures.
- **Comparaison de deux lecteurs** : désaccord aussi quand un même nom est
  lu sous deux GUID, ou trouvé par l'un et pas par l'autre. Seuls les
  lecteurs désignés comptent, et, quand plusieurs ont lu dans les deux
  derniers intervalles, seulement ceux-là : un lecteur éteint le week-end ne
  gèle plus le domaine sur sa lecture du vendredi. Conséquence acceptée : un
  poste enrôlé entre les lectures de deux lecteurs gèle le domaine jusqu'à
  la lecture suivante.
- **Lecteur retiré** : ses enregistrements sont supprimés avec sa
  désignation (retrait, chute, ré-enrôlement), et ceux d'un lecteur fusionné
  ou supprimé à la passe suivante du worker.
- **Salles** : une lecture n'adopte plus une salle créée à la main (elle
  reste à la resynchronisation, qui demande confirmation) ; l'ancienne clé
  d'une salle n'est reprise que si la salle est vide ou tient en majorité
  des postes lus dans ce domaine. Les postes laissés en place pour cette
  raison sont comptés « indécis », plus « déplacés ».
- **Confirmation** : elle porte sur les déplacements affichés (date et
  nombre) ; une lecture arrivée entre-temps la fait redemander. Refusée
  quand la lecture de l'annuaire est désactivée.
- **Portée** : désigner un lecteur, confirmer, écarter ou oublier un domaine
  est réservé aux comptes sans limite de lieu, comme la resynchronisation
  des salles ; un compte limité ne voit pas l'état de l'annuaire.
- **Verrous** : la ligne du domaine est verrouillée en premier par la
  lecture comme par la confirmation.
- **Ré-enrôlement** : le rapprochement du poste est oublié.
- **Agent** : les filtres LDAP passent par l'entrée standard de PowerShell
  et non par la ligne de commande, plafonnée à 32 767 caractères (une
  lecture échouait au-delà d'environ mille postes). Dix mille noms au plus
  par lecture, côté agent comme côté serveur.
- **Heartbeat** : il ne range plus de poste en mode relais (un déplacement
  retenu était appliqué par le heartbeat suivant) ; une lecture restée sans
  réponse ne bloque plus les suivantes au-delà de 30 minutes.

Limites qui restent, inchangées : un lecteur compromis ment pour son
domaine ; un poste forgé qui prend le nom d'un poste réel pas encore enrôlé
est rangé à sa place.

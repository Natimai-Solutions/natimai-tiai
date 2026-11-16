# Lecture de l'annuaire par le serveur — plan de travail

> **Statut : à cadrer** (rédigé le 2026-11-16, non codé). Répond aux constats
> S19 et S20 de l'audit 2026-11, acceptés en limite au §6.4 de
> `plan-audit-2026-11.md` (« Emplacement et annuaire déclaratifs »). Les
> questions du §9 sont à trancher avant le premier jalon.
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
  site à site) : lecture LDAP directe, §3.1.
- **Serveur sans route** (hébergé ailleurs, plusieurs domaines) : lecture
  déléguée à des postes désignés, §3.2.

## 3. Deux modes de lecture, un seul modèle

### 3.1 Mode `ldap` — le serveur interroge l'annuaire

- **Bibliothèque** : `ldap3` (Python pur, pas de dépendance système), appelée
  dans un thread pour ne pas bloquer la boucle de l'API, et en pratique depuis
  le **worker**, pas depuis les requêtes.
- **Connexion** : LDAPS (636) ou StartTLS, certificat vérifié (AC de
  l'établissement fournie par fichier). Le LDAP en clair est refusé au
  démarrage, sauf option explicite comme `AllowInsecureHTTP` côté agent.
- **Compte** : un compte de service AD en **lecture seule**, sans aucun droit
  au-delà de la lecture des objets ordinateurs, des OU et de la configuration
  des sites. Bind simple sur TLS ; Kerberos plus tard si demandé. Mot de passe
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
avec une confiance **explicite** au lieu d'une confiance par emplacement :

- un administrateur **désigne** dans la console un ou plusieurs postes
  « lecteurs d'annuaire » (typiquement un serveur membre du site, jamais un
  poste élève). La désignation est auditée et révocable ;
- le serveur leur confie une commande `directory_read`, avec la liste des noms
  de postes à lire. L'agent interroge l'annuaire en ADSI (déjà utilisé pour
  l'attribut `location`, §3 du plan salles) avec son compte machine, et
  renvoie les mêmes attributs que le §3.1 ;
- **gain de sécurité** : un poste quelconque, forgé ou compromis, ne décide
  plus de rien pour les autres. Seuls les postes désignés par un
  administrateur le peuvent, et le journal dit lesquels ont parlé ;
- **limite** : un lecteur désigné compromis ment pour tout son domaine. On le
  borne en exigeant qu'un lecteur ne réponde que pour son propre domaine
  (`dNSHostName` du suffixe attendu), et en comparant deux lecteurs quand il y
  en a deux.

### 3.3 Le modèle commun

Une table `directory_records`, une ligne par objet ordinateur vu dans
l'annuaire :

| Colonne | Rôle |
|---|---|
| `object_guid` | Clé stable (un poste renommé garde son GUID) |
| `domain`, `sam_account_name`, `dns_host_name` | Pour rapprocher l'objet du poste |
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

## 4. Ce que la lecture change

### 4.1 Salles (S20)

Avec `DIRECTORY_VERIFY=ldap` ou `relay` et `ROOM_SOURCE=ad_*` :
- **le serveur range le poste d'après l'enregistrement d'annuaire**, plus
  d'après le bloc `directory` du heartbeat. Le bloc envoyé par l'agent reste
  stocké et affiché, comme indice ;
- un écart entre les deux passe le poste en `mismatch` : badge sur la fiche,
  filtre dans la liste, ligne au journal d'audit. Ce n'est pas un refus : un
  poste déplacé dans AD et pas encore redémarré a un DN local en retard ;
- un poste sans enregistrement (`unknown`) reste où il est et ne crée pas de
  salle. Les salles ne se créent plus qu'à partir de l'annuaire lu ;
- le vote à la majorité de T36 devient inutile dans ce mode : le DN de l'OU
  lue est la clé de la salle.

### 4.2 Relais Wake-on-LAN (S19)

- **Site d'un poste** : le site AD de l'objet est déduit du sous-réseau de son
  adresse. Pour ne pas croire l'adresse déclarée, le serveur la compare à
  l'**adresse source** de la connexion (`client_ip`) quand le poste est sur
  le même réseau que le serveur. Sinon, il la compare à une liste
  d'**adresses de sortie par site** (`WOL_SITE_EGRESS`, facultative), qui
  rattache l'IP publique d'un établissement à son site.
- **Relais** : un poste ne relaie que pour les cibles du même site
  **vérifié**, et seulement s'il est lui-même `verified`. L'emplacement
  déclaré par l'agent ne suffit plus ; il reste l'emplacement affiché et
  filtrable.
- **Sans vérification possible** (mode désactivé ou annuaire injoignable) : le
  comportement actuel est conservé et la page Paramètres dit que les relais
  reposent sur l'emplacement déclaré.

### 4.3 Comptes désactivés et postes supprimés de l'annuaire

Un objet ordinateur désactivé ou supprimé de l'annuaire passe le poste en
`stale` : signalé, exclu des relais, sans révocation automatique du token. La
révocation reste une décision humaine, proposée en un clic depuis le filtre.

## 5. Configuration

| Variable | Défaut | Rôle |
|---|---|---|
| `DIRECTORY_VERIFY` | `off` | `off`, `ldap` ou `relay` |
| `LDAP_URL` | — | `ldaps://dc1.lycee.local` ; plusieurs URL séparées par des virgules, essayées dans l'ordre |
| `LDAP_BIND_DN`, `LDAP_BIND_PASSWORD` | — | Compte de service en lecture seule |
| `LDAP_BASE_DN` | — | Racine des objets ordinateurs, par exemple `OU=Postes,DC=lycee,DC=local` |
| `LDAP_CA_FILE` | — | AC qui a signé le certificat du DC |
| `LDAP_ALLOW_PLAINTEXT` | `false` | Refusé sans cette option : `ldap://` sans StartTLS |
| `DIRECTORY_SYNC_MINUTES` | `60` | Intervalle des lectures complètes |
| `DIRECTORY_STALE_HOURS` | `72` | Au-delà, un enregistrement non relu est `stale` et ne vérifie plus rien |
| `WOL_SITE_EGRESS` | — | `Site=203.0.113.4,198.51.100.0/28;…` (§4.2) |

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
  (droit `settings:write`), liste des lecteurs dans Paramètres.

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
| **L2 — Salles vérifiées** | Placement d'après l'enregistrement, statut `mismatch`, fiche et filtre, aperçu de resynchronisation qui montre les écarts. | 2 j |
| **L3 — Relais vérifiés** | Sous-réseaux et sites, `client_ip` et `WOL_SITE_EGRESS`, éligibilité des relais. | 2 j |
| **L4 — Mode `relay`** | Désignation, commande `directory_read`, lecture ADSI côté agent (Windows : à valider sur un domaine réel, comme le bind ADSI de J3), comparaison de deux lecteurs. | 3 j + validation sur site |
| **L5 — Documentation et recette** | `DEPLOYMENT.md` (compte de service, AC, dépannage), notes de version, recette sur le banc et sur un domaine réel. | 1 j |

L1 à L3 suffisent pour un serveur qui voit un DC ; L4 n'est utile que pour un
serveur hébergé ailleurs.

## 9. Questions à trancher

1. **Le serveur de production voit-il un contrôleur de domaine** (même réseau
   ou VPN) ? Si oui, L4 peut attendre.
2. **Un ou plusieurs domaines** sur le parc ? Le §3.1 suppose une base par
   domaine ; plusieurs domaines demandent une liste de connexions.
3. **Qui crée le compte de service**, et l'établissement accepte-t-il un bind
   simple sur LDAPS, ou exige-t-il Kerberos ?
4. **Adresses de sortie par site** : sont-elles fixes et connues, pour
   `WOL_SITE_EGRESS` ?
5. **Écart annuaire / agent** : signaler seulement (proposé), ou bloquer le
   placement du poste tant que l'écart dure ?

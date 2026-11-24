import type { Translation } from './types';

/** La conformité des postes et les mises à jour tierces (plan `dev/plan-evolutions-itil.md`, C5). */
const fr = {
  card: {
    title: 'Conformité',
    caption:
      'Une liste fermée de contrôles, calculée à l’ouverture de la fiche. Un contrôle non relevé ne compte ni pour ni contre.',
    summary: '{passed} sur {total}',
    none: 'Aucun contrôle relevé pour l’instant.',
  },
  checks: {
    encryption: 'Volume système chiffré',
    secure_boot: 'Démarrage sécurisé',
    tpm: 'TPM 2.0',
    antivirus: 'Antivirus actif et à jour',
    patches: 'Correctifs critiques et importants installés',
    reboot: 'Pas de redémarrage en retard',
    os_supported: 'Windows encore pris en charge',
    agent_current: 'Agent à jour',
    firewall: 'Pare-feu actif (3 profils)',
    local_admins: 'Administrateurs locaux maîtrisés',
  },
  state: {
    pass: 'Conforme',
    fail: 'Non conforme',
    unknown: 'Non relevé',
    not_applicable: 'Non requis',
  },
  detail: {
    encryption: 'État BitLocker : {status}',
    tpm: 'Version {version}',
    tpmAbsent: 'Aucun TPM relevé sur ce poste',
    patches: '{count} en attente, en retard depuis plus de {days} j : {updates}',
    reboot: 'Demandé le {since}',
    os_supported: 'Fin de support : {date}',
    agent_current: 'Version {version}',
    firewall: 'Désactivé : {profiles}',
    local_admins: 'En trop : {names}',
    notApplicable: 'Requis seulement pour les portables et tablettes (Paramètres)',
  },
  profiles: { domain: 'domaine', private: 'privé', public: 'public' },
  admins: {
    title: 'Administrateurs locaux',
    hint: 'Membres du groupe Administrateurs du poste, remontés seulement si l’agent y est autorisé (ReportLocalAdmins).',
  },
  winget: {
    title: 'Logiciels connus de winget',
    hint: 'Remontés seulement si l’agent y est autorisé (ReportWingetPackages). Relevé le {date}.',
    available: 'Disponible : {version}',
    upToDate: 'À jour',
    none: 'Aucun logiciel connu de winget sur ce poste.',
    columns: { name: 'Logiciel', version: 'Version', available: 'Mise à jour' },
  },
  dashboard: {
    title: 'Conformité',
    compliant: 'Postes conformes',
    compliantCaption: '{count} conforme(s)',
    noncompliant: 'Postes non conformes',
    byCheck: 'Contrôles en échec',
    none: 'Aucun contrôle en échec.',
  },
  chips: {
    failing: 'Non conformes',
    passing: 'Conformes',
    unknown: 'Conformité non relevée',
    check: 'En échec : {check}',
    winget: 'Mise à jour winget en attente : {id}',
  },
  column: 'Conformité',
  updates: {
    tab: 'Mises à jour tierces',
    caption:
      'Par logiciel connu de winget : combien de postes ont une version plus récente disponible. Sur {reporting} poste(s) qui remontent leurs paquets winget.',
    noneReporting:
      'Aucun poste ne remonte ses paquets winget. La collecte s’active sur l’agent (valeur de registre ReportWingetPackages à 1), après validation sur un poste réel.',
    outdatedOnly: 'Seulement ceux à mettre à jour',
    search: 'Rechercher un logiciel',
    empty: 'Aucun logiciel.',
    columns: {
      name: 'Logiciel',
      installed: 'Postes',
      outdated: 'À mettre à jour',
      available: 'Dernière version',
      rate: 'À jour',
    },
    seeMachines: 'Voir ces postes',
    loadFailed: 'Les mises à jour n’ont pas pu être chargées.',
  },
  settings: {
    title: 'Conformité des postes',
    caption:
      'Les contrôles « redémarrage » et « chiffrement » reprennent les réglages des alertes. Le résumé de la liste et du tableau de bord est recalculé toutes les 10 minutes.',
    patchGrace:
      'Délai avant qu’un poste en retard d’un correctif critique ou important soit non conforme (jours)',
    patchGraceHint: 'Valeur initiale du serveur : {days} j',
    admins: 'Administrateurs locaux acceptés',
    adminsHint:
      'Comptes ou groupes acceptés en plus de l’Administrateur intégré, des Admins du domaine et des Administrateurs de l’entreprise : « DOMAINE\\nom » ou « nom ». Entrée pour ajouter.',
  },
};

const en: Translation<typeof fr> = {
  card: {
    title: 'Compliance',
    caption:
      'A closed list of checks, computed when the page opens. A check not read counts neither for nor against.',
    summary: '{passed} of {total}',
    none: 'No check read yet.',
  },
  checks: {
    encryption: 'System volume encrypted',
    secure_boot: 'Secure Boot',
    tpm: 'TPM 2.0',
    antivirus: 'Antivirus on and up to date',
    patches: 'Critical and important updates installed',
    reboot: 'No overdue restart',
    os_supported: 'Windows still supported',
    agent_current: 'Agent up to date',
    firewall: 'Firewall on (3 profiles)',
    local_admins: 'Local administrators under control',
  },
  state: {
    pass: 'Compliant',
    fail: 'Not compliant',
    unknown: 'Not read',
    not_applicable: 'Not required',
  },
  detail: {
    encryption: 'BitLocker status: {status}',
    tpm: 'Version {version}',
    tpmAbsent: 'No TPM found on this computer',
    patches: '{count} pending, behind for more than {days} days: {updates}',
    reboot: 'Requested on {since}',
    os_supported: 'End of support: {date}',
    agent_current: 'Version {version}',
    firewall: 'Off: {profiles}',
    local_admins: 'Extra: {names}',
    notApplicable: 'Required only for laptops and tablets (Settings)',
  },
  profiles: { domain: 'domain', private: 'private', public: 'public' },
  admins: {
    title: 'Local administrators',
    hint: 'Members of the computer’s Administrators group, reported only when the agent is allowed to (ReportLocalAdmins).',
  },
  winget: {
    title: 'Programs winget knows',
    hint: 'Reported only when the agent is allowed to (ReportWingetPackages). Read on {date}.',
    available: 'Available: {version}',
    upToDate: 'Up to date',
    none: 'No program winget knows on this computer.',
    columns: { name: 'Program', version: 'Version', available: 'Update' },
  },
  dashboard: {
    title: 'Compliance',
    compliant: 'Compliant computers',
    compliantCaption: '{count} compliant',
    noncompliant: 'Computers not compliant',
    byCheck: 'Failed checks',
    none: 'No failed check.',
  },
  chips: {
    failing: 'Not compliant',
    passing: 'Compliant',
    unknown: 'Compliance not read',
    check: 'Failing: {check}',
    winget: 'winget update pending: {id}',
  },
  column: 'Compliance',
  updates: {
    tab: 'Third-party updates',
    caption:
      'For each program winget knows: how many computers have a newer version available. Out of {reporting} computer(s) reporting their winget packages.',
    noneReporting:
      'No computer reports its winget packages. The collection is turned on in the agent (registry value ReportWingetPackages set to 1), once validated on a real computer.',
    outdatedOnly: 'Only those to update',
    search: 'Search a program',
    empty: 'No program.',
    columns: {
      name: 'Program',
      installed: 'Computers',
      outdated: 'To update',
      available: 'Latest version',
      rate: 'Up to date',
    },
    seeMachines: 'See these computers',
    loadFailed: 'The updates could not be loaded.',
  },
  settings: {
    title: 'Computer compliance',
    caption:
      'The “restart” and “encryption” checks use the alerts’ settings. The list’s and the dashboard’s summary is recomputed every 10 minutes.',
    patchGrace:
      'Delay before a computer behind on a critical or important update fails the check (days)',
    patchGraceHint: 'Server’s initial value: {days} days',
    admins: 'Accepted local administrators',
    adminsHint:
      'Accounts or groups accepted besides the built-in Administrator, Domain Admins and Enterprise Admins: “DOMAIN\\name” or “name”. Enter to add.',
  },
};

export default { fr, en };

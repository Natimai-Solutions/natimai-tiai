import type { Translation } from './types';

/** Connexion, mot de passe oublié, nouveau mot de passe (lot E1 du plan console bilingue). */
const fr = {
  required: 'Requis',
  email: 'E-mail',
  backToLogin: 'Retour à la connexion',
  login: {
    subtitle: 'Supervision du parc',
    sessionEnded: 'Votre session a pris fin : reconnectez-vous pour reprendre où vous en étiez.',
    password: 'Mot de passe',
    submit: 'Se connecter',
    forgot: 'Mot de passe oublié ?',
    failed: 'Identifiants invalides',
  },
  forgot: {
    title: 'Mot de passe oublié',
    intro: "Indiquez l'adresse de votre compte : un lien de réinitialisation vous sera envoyé.",
    submit: 'Envoyer le lien',
    /** Around the address, shown in bold between the two. */
    sentBefore: 'Si un compte existe pour',
    sentAfter: ", un lien de réinitialisation vient d'être envoyé. Il expire dans {expiry}.",
    failed: 'Envoi impossible',
  },
  reset: {
    title: 'Nouveau mot de passe',
    noToken: 'Lien incomplet : il ne contient pas de jeton de réinitialisation.',
    checking: 'Vérification du lien',
    invalid:
      "Ce lien n'est plus valable : il a expiré, a déjà servi, ou a été coupé en route. Demandez-en un nouveau.",
    forgot: 'Mot de passe oublié',
    password: 'Nouveau mot de passe',
    minLength: '{min} caractères minimum',
    confirm: 'Confirmer le mot de passe',
    mismatch: 'Les mots de passe ne correspondent pas',
    submit: 'Définir le mot de passe',
    done: 'Mot de passe défini. Vous pouvez vous connecter.',
    failed: 'Réinitialisation impossible',
  },
};

const en: Translation<typeof fr> = {
  required: 'Required',
  email: 'E-mail',
  backToLogin: 'Back to sign-in',
  login: {
    subtitle: 'Fleet monitoring',
    sessionEnded: 'Your session has ended: sign in again to pick up where you left off.',
    password: 'Password',
    submit: 'Sign in',
    forgot: 'Forgotten your password?',
    failed: 'Invalid credentials',
  },
  forgot: {
    title: 'Forgotten password',
    intro: 'Enter your account’s address: a reset link will be sent to you.',
    submit: 'Send the link',
    sentBefore: 'If an account exists for',
    sentAfter: ', a reset link has just been sent. It expires in {expiry}.',
    failed: 'Could not send',
  },
  reset: {
    title: 'New password',
    noToken: 'Incomplete link: it holds no reset token.',
    checking: 'Checking the link',
    invalid:
      'This link is no longer valid: it has expired, has already been used, or was cut off on the way. Ask for a new one.',
    forgot: 'Forgotten password',
    password: 'New password',
    minLength: '{min} characters minimum',
    confirm: 'Confirm the password',
    mismatch: 'The passwords do not match',
    submit: 'Set the password',
    done: 'Password set. You can now sign in.',
    failed: 'Could not reset the password',
  },
};

export default { fr, en };

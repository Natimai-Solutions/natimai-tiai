import type { AxiosError } from 'axios';

/** Standard API error envelope (mirrors the backend, plan §2.14). */
export interface ApiErrorBody {
  error: {
    code: string;
    message?: string;
    details?: Record<string, unknown>;
  };
}

/**
 * Code → localized message. The backend catalog (app/core/errors.py,
 * ErrorCode) is the source of truth; keep this table in sync. The console maps
 * the stable `code` — never the backend text — so messages stay localizable.
 */
export const ERROR_MESSAGES: Record<string, string> = {
  'auth.credentials.invalid': 'Identifiants invalides',
  'auth.required': 'Authentification requise',
  'auth.permission.denied': "Vous n'avez pas la permission requise",
  'auth.token.missing': 'Jeton manquant',
  'auth.token.invalid': 'Jeton invalide',
  'auth.token.revoked': 'Jeton révoqué',
  'auth.enrollment_secret.invalid': "Secret d'enrôlement invalide",
  'password.current.invalid': 'Mot de passe actuel incorrect',
  'password.reset_token.invalid': 'Ce lien de réinitialisation est invalide ou a expiré',
  'machine.not_found': 'Poste introuvable',
  'machine.merge.self': 'Un poste ne peut pas être fusionné avec lui-même',
  'user.not_found': 'Compte introuvable',
  'user.email.taken': 'Cette adresse e-mail est déjà utilisée',
  'user.self.forbidden': 'Vous ne pouvez pas appliquer cette action à votre propre compte',
  'request.validation_error': 'Requête invalide',
  'http.not_found': 'Ressource introuvable',
  'http.error': 'Erreur',
  'internal.server_error': 'Erreur interne du serveur',
};

/** Extract the stable error code from an API error, if present. */
export function apiErrorCode(err: unknown): string | null {
  const body = (err as AxiosError<ApiErrorBody>)?.response?.data;
  return body?.error?.code ?? null;
}

/**
 * Resolve a user-facing message for an API error: the localized message for the
 * code, else the backend-provided message, else the caller's fallback.
 */
export function apiErrorMessage(err: unknown, fallback = 'Une erreur est survenue'): string {
  const body = (err as AxiosError<ApiErrorBody>)?.response?.data;
  const code = body?.error?.code;
  if (code && ERROR_MESSAGES[code]) {
    return ERROR_MESSAGES[code];
  }
  return body?.error?.message ?? fallback;
}

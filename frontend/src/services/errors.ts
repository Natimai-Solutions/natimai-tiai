import type { AxiosError } from 'axios';
import { errorCodeMessage, t } from 'src/i18n';
import {
  invalidText,
  problemText,
  refusedNameText,
  signatureText,
  type Cause,
} from 'src/utils/packageText';

/** Standard API error envelope (mirrors the backend, plan §2.14). */
export interface ApiErrorBody {
  error: {
    code: string;
    message?: string;
    details?: Record<string, unknown>;
  };
}

/**
 * The messages themselves live in the catalogues, in each language of the
 * console: `src/i18n/messages/errorCodes.ts` for the codes (the backend's
 * `ErrorCode`, which `backend/tests/test_errors_unit.py` checks against it),
 * `src/i18n/messages/errors.ts` for the words around a detail.
 */

/** Extract the stable error code from an API error, if present. */
export function apiErrorCode(err: unknown): string | null {
  const body = (err as AxiosError<ApiErrorBody>)?.response?.data;
  return body?.error?.code ?? null;
}

/**
 * Codes whose detail says what to correct: shown after the label rather than
 * dropped (audit U03). Worded by the console from `details.cause` (plan
 * console bilingue, I2); a server older than that, or a cause the console
 * does not know, gives its French `message` instead.
 */
const CAUSE_WORDING: Record<string, (cause: Cause) => string | null> = {
  'package.invalid': invalidText,
  // Why a signature was refused — a manifest changed since, another
  // certificate, an algorithm that does not fit the key…
  'package.signature.invalid': signatureText,
};

function causeOf(details: Record<string, unknown> | undefined): Cause | null {
  const cause = details?.cause as Cause | undefined;
  return cause && typeof cause.code === 'string' ? cause : null;
}

/** A request field as the forms call it, or its own name when no form does. */
function fieldLabel(field: string): string {
  const key = `errors.fields.${field}`;
  const label = t(key);
  return label === key ? field : label;
}

interface ValidationItem {
  loc?: (string | number)[];
  msg?: string;
}

/** « champ — raison » for the first field a 422 names, in the console's words. */
function validationDetail(details: Record<string, unknown> | undefined): string | null {
  const errors = details?.errors;
  if (!Array.isArray(errors) || errors.length === 0) return null;
  const first = errors[0] as ValidationItem;
  // The location starts with where the field was (body, query); the last
  // name in it is the field, past any list index.
  const names = (first.loc ?? []).filter(
    (p): p is string => typeof p === 'string' && !['body', 'query', 'path'].includes(p),
  );
  const field = names[names.length - 1];
  const label = field ? fieldLabel(field) : null;
  // A ValueError raised by the backend reads « Value error, … ».
  const reason = (first.msg ?? '').replace(/^Value error, /, '');
  const more = errors.length > 1 ? t('errors.others', { count: errors.length - 1 }) : '';
  if (label && reason) return t('errors.fieldReason', { field: label, reason }) + more;
  if (label) return t('errors.field', { field: label }) + more;
  return reason || null;
}

/**
 * Resolve a user-facing message for an API error: the localized message for the
 * code — completed, where the backend says what to correct, by its own words
 * or by the field a validation error names — else the backend-provided message,
 * else the caller's fallback.
 */
export function apiErrorMessage(err: unknown, fallback: string = t('errors.generic')): string {
  const response = (err as AxiosError<ApiErrorBody>)?.response;
  const body = response?.data;
  const code = body?.error?.code;
  // Refused by the proxy in front of the API, which answers without the
  // error envelope (audit U16).
  if (!code && response?.status === 413)
    return errorCodeMessage('package.file.too_large') ?? fallback;
  const label = code ? errorCodeMessage(code) : null;
  if (code && label) {
    // A refused file name: the server names the file and the rule it breaks
    // (« « nul.txt » refusé : nom réservé par Windows »), a sentence of its own.
    const details = body?.error?.details;
    const cause = causeOf(details);
    if (code === 'package.file.name_invalid' && (cause || details?.reason)) {
      const name = typeof details?.name === 'string' ? details.name : '';
      const worded = cause ? refusedNameText(name, cause) : null;
      if (worded) return worded;
      if (body?.error?.message) return body.error.message;
    }
    const wording = CAUSE_WORDING[code];
    if (wording) {
      const detail = (cause ? wording(cause) : null) ?? body?.error?.message;
      if (detail) return t('errors.withDetail', { label, detail });
    }
    if (code === 'request.validation_error') {
      const detail = validationDetail(body?.error?.details);
      if (detail) return t('errors.withDetail', { label, detail });
    }
    if (code === 'room.in_group_scope') {
      const groups = body?.error?.details?.groups;
      if (Array.isArray(groups) && groups.length) {
        const quoted = groups.map((g) => t('errors.quoted', { name: String(g) }));
        return t('errors.groups', { label, groups: quoted.join(t('errors.listSeparator')) });
      }
    }
    if (code === 'maintenance.items.not_in_room') {
      const names = body?.error?.details?.hostnames;
      if (Array.isArray(names) && names.length) {
        const detail = names.map(String).join(t('errors.listSeparator'));
        return t('errors.withDetail', { label, detail });
      }
    }
    if (code === 'package.not_ready') {
      const causes = details?.causes;
      const problems = details?.problems;
      const texts =
        Array.isArray(causes) && causes.length
          ? (causes as Cause[]).map((c, i) =>
              problemText({
                ...c,
                message: Array.isArray(problems) ? String(problems[i] ?? '') : undefined,
              }),
            )
          : Array.isArray(problems)
            ? problems.map(String)
            : [];
      if (texts.length) {
        const detail = texts.join(t('errors.problemSeparator'));
        return t('errors.withDetail', { label, detail });
      }
    }
    return label;
  }
  return body?.error?.message ?? fallback;
}

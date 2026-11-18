import { t } from 'src/i18n';

/**
 * What is wrong with a whole number typed in a settings field, in the page's
 * words; null when nothing. An emptied field is an error, never a 0: the
 * server would take 0 for an answer — « base périmée au-delà de 0 jour » turns
 * the whole parc red (audit U06).
 */
export function intFieldError(
  value: number | string | null | undefined,
  min: number,
  max: number,
): string | null {
  if (value === '' || value === null || value === undefined) return t('settings.number.required');
  const n = typeof value === 'number' ? value : Number(String(value).trim());
  if (!Number.isFinite(n) || !Number.isInteger(n)) return t('settings.number.integer');
  if (n < min || n > max) return t('settings.number.between', { min, max });
  return null;
}

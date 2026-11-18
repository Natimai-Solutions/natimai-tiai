/**
 * The server's environment (page Paramètres → « Réglages du serveur ») in the
 * reader's language (plan `dev/plan-console-bilingue.md`, I2).
 *
 * The server sends each variable with its French value and description, and
 * beside them what the console needs to word it itself: the group's `code`,
 * the raw value and a `format`. The French worded here is the server's, word
 * for word (`backend/tests/data/settings_texts_fr.json`, checked on both
 * sides). A group, a variable or a format the console does not know — a
 * server newer than it — is shown with the server's French, as before; so is
 * everything from a server older than the codes.
 */
import { intlTag, t } from 'src/i18n';
import type { EnvGroup, EnvItem } from 'src/services/settings';
import { weekdayName } from 'src/utils/settingsSchedule';

/** `key` translated, or null when the catalogue has no such key. */
function translated(key: string, named: Record<string, unknown> = {}): string | null {
  const text = t(key, named);
  return text === key ? null : text;
}

/** A group's name. */
export function envGroupLabel(group: EnvGroup): string {
  return (group.code && translated(`settingsEnv.groups.${group.code}`)) || group.label;
}

/** What a variable decides. */
export function envDescription(item: EnvItem): string {
  return translated(`settingsEnv.descriptions.${item.key}`) ?? item.description;
}

const MIB = 1024 ** 2;
const GIB = 1024 ** 3;

/**
 * `value / size` with one decimal, rounded as the server rounds it — the
 * exact quotient, half to even (Python's `f"{x:.1f}"`) —, in tenths.
 */
function tenths(value: number, size: number): number {
  // Exact: the sizes are powers of two and the values far below 2^53.
  const scaled = value * 10;
  let n = Math.floor(scaled / size);
  const rest = scaled - n * size;
  if (rest * 2 > size || (rest * 2 === size && n % 2 === 1)) n += 1;
  return n;
}

/** « 2147483648 (2 Gio) », « 1572864 (1,5 Mio) », « 1000 octets ». */
export function bytesText(value: number): string {
  for (const [unit, size] of [
    ['gib', GIB],
    ['mib', MIB],
  ] as const) {
    if (value < size) continue;
    const amount =
      value % size === 0
        ? new Intl.NumberFormat(intlTag(), { useGrouping: false }).format(value / size)
        : new Intl.NumberFormat(intlTag(), {
            useGrouping: false,
            minimumFractionDigits: 1,
            maximumFractionDigits: 1,
          }).format(tenths(value, size) / 10);
    return t('settingsEnv.values.bytes', {
      raw: String(value),
      amount,
      unit: t(`settingsEnv.values.${unit}`),
    });
  }
  return t('settingsEnv.values.bytesOnly', { raw: String(value) });
}

function withMeaning(raw: unknown, meaning: string): string {
  return t('settingsEnv.values.withMeaning', { raw: String(raw), meaning });
}

/** The worded value, or null when the console cannot word it (the server's then). */
function worded(item: EnvItem): string | null {
  const { raw } = item;
  const params = item.params ?? {};
  switch (item.format) {
    case 'plain':
      return item.value;
    case 'bool':
      return typeof raw === 'boolean' ? t(`settingsEnv.values.${raw ? 'yes' : 'no'}`) : null;
    case 'list':
      return Array.isArray(raw)
        ? raw.map(String).join(t('settingsEnv.values.listSeparator'))
        : null;
    case 'bytes':
      return typeof raw === 'number' && Number.isSafeInteger(raw) && raw >= 0
        ? bytesText(raw)
        : null;
    case 'weekday':
      return typeof raw === 'number' && Number.isInteger(raw) && raw >= 0 && raw <= 6
        ? withMeaning(raw, weekdayName(raw))
        : null;
    case 'room_source':
      return typeof raw === 'string'
        ? withMeaning(raw, translated(`settingsEnv.roomSources.${raw}`) ?? raw)
        : null;
    case 'mail_state':
      return typeof raw === 'string' && typeof params.configured === 'boolean'
        ? withMeaning(
            raw,
            t(`settingsEnv.values.${params.configured ? 'mailConfigured' : 'mailIncomplete'}`),
          )
        : null;
    case 'proxy':
      if (params.unreadable === true) return t('settingsEnv.values.unreadable');
      return typeof raw === 'string' ? raw : null;
    default:
      return null;
  }
}

/** A variable's value as the page shows it; null = not set (the page shows a dash). */
export function envValue(item: EnvItem): string | null {
  if (item.value === null) return null;
  return worded(item) ?? item.value;
}

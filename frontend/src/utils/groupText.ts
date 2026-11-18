/**
 * A group's name and description as the console shows them. A built-in
 * group (`builtin_key`) is named in the reader's language while it still
 * carries the name and description the installation gave it; once an
 * administrator has changed them, they are theirs, shown as typed.
 *
 * Names are unique only as stored: an operator group may be named «
 * Administrators » beside « Administrateurs ». Given the list it is shown
 * with, a built-in group keeps its stored name when another group of the list
 * already carries its translation, so a picker or a row of chips never shows
 * the same name twice.
 */
import { t } from 'src/i18n';
import catalogue from 'src/i18n/messages/groups';

type Builtin = keyof typeof catalogue.fr.builtin;

interface GroupLike {
  name: string;
  description?: string | null;
  builtin_key?: string | null;
}

function seed(group: GroupLike): Builtin | null {
  const key = group.builtin_key;
  return key && Object.prototype.hasOwnProperty.call(catalogue.fr.builtin, key)
    ? (key as Builtin)
    : null;
}

export function groupName(group: GroupLike, among: readonly GroupLike[] = []): string {
  const key = seed(group);
  if (!key || group.name !== catalogue.fr.builtin[key].name) return group.name;
  const translated = t(`groups.builtin.${key}.name`);
  const folded = translated.toLocaleLowerCase();
  // In French the translation is the stored name: the group finds itself.
  return among.some((other) => other.name.toLocaleLowerCase() === folded) ? group.name : translated;
}

export function groupDescription(group: GroupLike): string | null {
  const key = seed(group);
  const description = group.description ?? null;
  return key && description === catalogue.fr.builtin[key].description
    ? t(`groups.builtin.${key}.description`)
    : description;
}

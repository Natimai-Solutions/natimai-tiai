/**
 * A group's name and description as the console shows them. A built-in
 * group (`builtin_key`) is named in the reader's language while it still
 * carries the name and description the installation gave it; once an
 * administrator has changed them, they are theirs, shown as typed.
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

export function groupName(group: GroupLike): string {
  const key = seed(group);
  return key && group.name === catalogue.fr.builtin[key].name
    ? t(`groups.builtin.${key}.name`)
    : group.name;
}

export function groupDescription(group: GroupLike): string | null {
  const key = seed(group);
  const description = group.description ?? null;
  return key && description === catalogue.fr.builtin[key].description
    ? t(`groups.builtin.${key}.description`)
    : description;
}

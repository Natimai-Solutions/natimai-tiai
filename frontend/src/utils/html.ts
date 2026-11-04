/**
 * Escape text before it is interpolated into HTML — the confirmation dialogs
 * built with Quasar's `html: true`, which renders its message as markup.
 *
 * Every name such a dialog quotes must go through here: a hostname comes from
 * a poste, a room created from the directory is named after an OU or an AD
 * attribute, and an account or group is named by another administrator —
 * none of which this console wrote.
 */
export function escapeHtml(value: string): string {
  return value.replace(
    /[&<>"']/g,
    (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c] as string,
  );
}

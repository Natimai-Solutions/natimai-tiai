/**
 * A form's values as one comparable string — to tell whether it was changed
 * since it was filled. Numbers and their typed text compare equal (« 10 » and
 * 10), as do null and an emptied box: a box retouched back to its value is
 * not an unsaved change.
 */
export function formSnapshot(form: object): string {
  return JSON.stringify(
    Object.entries(form)
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([key, value]) => [key, value == null ? '' : String(value)]),
  );
}

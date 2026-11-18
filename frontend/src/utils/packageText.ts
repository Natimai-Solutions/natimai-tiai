/**
 * A package's diagnostics in the reader's language (plan
 * `dev/plan-console-bilingue.md`, I2): the server sends each one as a code and
 * its parameters beside its French sentence; the console words the code from
 * its catalogue (`i18n/messages/packages.ts`).
 *
 * A code the console does not know — a server newer than it — is shown with
 * the server's own sentence, as before.
 */
import { t } from 'src/i18n';

/** What the server sends to word: a code, and what fills its sentence. */
export interface Cause {
  code: string;
  params?: Record<string, unknown> | undefined;
}

/** A problem or a refusal: its cause, and the server's French sentence. */
export interface Worded extends Cause {
  message?: string | undefined;
}

/** `key` translated with `named`, or null when the catalogue has no such key. */
function translated(key: string, named: Record<string, unknown>, plural?: number): string | null {
  const text = plural === undefined ? t(key, named) : t(key, named, plural);
  return text === key ? null : text;
}

function strings(value: unknown): string[] {
  return Array.isArray(value) ? value.map(String) : [];
}

/** « a », « b » — names quoted and listed as the server lists them. */
function quotedList(names: string[]): string {
  return names.map((name) => t('packages.quoted', { name })).join(t('packages.listSeparator'));
}

/** A refused character as the server shows it: quoted, or a code point bare. */
function shownCharacter(c: string): string {
  return [...c].length === 1 ? t('packages.quoted', { name: c }) : c;
}

/** Why a file name is refused, or null for an unknown reason. */
export function fileNameReason(cause: Cause): string | null {
  const params = cause.params ?? {};
  if (cause.code === 'forbidden_characters') {
    const chars = strings(params.characters);
    return translated(
      'packages.fileName.reasons.forbidden_characters',
      { characters: chars.map(shownCharacter).join(t('packages.listSeparator')) },
      chars.length,
    );
  }
  return translated(`packages.fileName.reasons.${cause.code}`, params);
}

/** A problem of a package (`problems`, `install_blocker_problems`, `causes`). */
export function problemText(problem: Worded): string {
  // A server older than the codes' parameters: its sentence is the only one
  // that names the file.
  if (problem.params === undefined && problem.message) return problem.message;
  const params = problem.params ?? {};
  let text: string | null = null;
  if (problem.code === 'untrusted') {
    const reason = typeof params.reason === 'string' ? params.reason : 'other';
    const files = strings(params.files);
    text = translated(
      `packages.problems.untrusted.${reason}`,
      { ...params, files: quotedList(files) },
      reason === 'loadable' ? files.length : undefined,
    );
  } else if (problem.code === 'duplicate_names') {
    const groups = Array.isArray(params.groups) ? params.groups : [];
    text = translated('packages.problems.duplicate_names', {
      groups: groups.map((g) => quotedList(strings(g))).join(t('packages.groupSeparator')),
    });
  } else if (problem.code === 'file_missing_in_store') {
    text = translated('packages.problems.file_missing_in_store', {
      files: quotedList(strings(params.files)),
    });
  } else {
    text = translated(`packages.problems.${problem.code}`, params);
  }
  return text ?? problem.message ?? problem.code;
}

/** Why no poste would install the package, one sentence each (`install_blockers`). */
export function installBlockerTexts(p: {
  install_blockers: string[];
  install_blocker_problems?: Worded[] | undefined;
}): string[] {
  return p.install_blocker_problems
    ? p.install_blocker_problems.map(problemText)
    : p.install_blockers;
}

/** Why a field of a package is refused (`package.invalid`'s `details.cause`). */
export function invalidText(cause: Cause): string | null {
  const params = cause.params ?? {};
  if (cause.code === 'run_file_refused') {
    const refusal = params.refusal as Cause | undefined;
    const reason = refusal ? fileNameReason(refusal) : null;
    if (reason === null) return null;
    return translated('packages.invalid.run_file_refused', { ...params, refusal: reason });
  }
  const sentence = translated(`packages.invalid.${cause.code}`, params);
  // The removal may hide in a file name: the argument says where.
  if (sentence !== null && cause.code === 'install_removes' && typeof params.argument === 'string')
    return t('packages.invalid.withArgument', { sentence, argument: params.argument });
  return sentence;
}

/** A refused upload name, whole: « « name » refusé : reason ». */
export function refusedNameText(name: string, cause: Cause): string | null {
  const reason = fileNameReason(cause);
  return reason === null ? null : t('packages.fileName.refused', { name, reason });
}

/** Why a signature is refused (`package.signature.invalid`'s `details.cause`). */
export function signatureText(cause: Cause): string | null {
  const params = cause.params ?? {};
  if (cause.code === 'missing_field' || cause.code === 'bad_base64') {
    return translated(`packages.signature.${cause.code}.${String(params.field)}`, {});
  }
  if (cause.code === 'algorithm_key_mismatch') {
    const key = translated(`packages.signature.keys.${String(params.key)}`, {});
    return translated('packages.signature.algorithm_key_mismatch', {
      algorithm: params.algorithm,
      key: key ?? params.key,
    });
  }
  return translated(`packages.signature.${cause.code}`, params);
}

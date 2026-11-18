import { afterEach, describe, expect, it } from 'vitest';
import { setLocale } from 'src/i18n';

import { apiErrorCode, apiErrorMessage } from './errors';

function axiosError(code?: string, message?: string) {
  return { response: { data: { error: { code, message } } } };
}

describe('apiErrorCode', () => {
  it('extracts the code from an API error', () => {
    expect(apiErrorCode(axiosError('machine.not_found'))).toBe('machine.not_found');
  });

  it('returns null when there is no envelope', () => {
    expect(apiErrorCode(new Error('boom'))).toBeNull();
    expect(apiErrorCode(undefined)).toBeNull();
  });
});

describe('apiErrorMessage', () => {
  it('maps a known code to its localized message', () => {
    expect(apiErrorMessage(axiosError('auth.credentials.invalid'))).toBe('Identifiants invalides');
  });

  it('falls back to the backend message for an unknown code', () => {
    expect(apiErrorMessage(axiosError('some.unknown.code', 'Backend says no'))).toBe(
      'Backend says no',
    );
  });

  it('uses the provided fallback when there is no envelope', () => {
    expect(apiErrorMessage(new Error('boom'), 'Échec')).toBe('Échec');
  });

  it('completes a code whose backend message says what to correct', () => {
    const err = axiosError('package.invalid', 'Version winget invalide');
    expect(apiErrorMessage(err)).toBe('Paquet invalide : Version winget invalide');
  });

  it('names the field a validation error is about', () => {
    const err = {
      response: {
        data: {
          error: {
            code: 'request.validation_error',
            details: {
              errors: [
                {
                  loc: ['body', 'performed_at'],
                  msg: 'Value error, la date ne peut pas être dans le futur',
                },
              ],
            },
          },
        },
      },
    };
    expect(apiErrorMessage(err)).toBe(
      'Requête invalide : champ « date » : la date ne peut pas être dans le futur',
    );
  });

  it('lists why a package cannot be deployed', () => {
    const err = {
      response: {
        data: { error: { code: 'package.not_ready', details: { problems: ['A', 'B'] } } },
      },
    };
    expect(apiErrorMessage(err)).toMatch(/: A ; B$/);
  });

  it('reads a 413 from the proxy, which has no envelope', () => {
    const proxy = { response: { status: 413, data: '<html>Request Entity Too Large</html>' } };
    expect(apiErrorMessage(proxy, 'Dépôt impossible')).toBe('Fichier trop volumineux');
  });

  it('uses the default fallback when nothing else is available', () => {
    expect(apiErrorMessage(undefined)).toBe('Une erreur est survenue');
  });
});

describe('apiErrorMessage in English', () => {
  afterEach(() => setLocale('fr'));

  it('speaks the language of the console, details included', () => {
    setLocale('en');
    expect(apiErrorMessage(axiosError('machine.not_found'))).toBe('Computer not found');
    const err = {
      response: {
        data: {
          error: {
            code: 'request.validation_error',
            details: { errors: [{ loc: ['body', 'name'], msg: 'too long' }, { loc: ['x'] }] },
          },
        },
      },
    };
    expect(apiErrorMessage(err)).toBe('Invalid request: field “name”: too long (and 1 more)');
    expect(apiErrorMessage(new Error('offline'))).toBe('Something went wrong');
  });

  it('names a field no form names by its own name', () => {
    setLocale('en');
    const err = {
      response: {
        data: {
          error: {
            code: 'request.validation_error',
            details: { errors: [{ loc: ['body', 'odd_field'], msg: 'bad' }] },
          },
        },
      },
    };
    expect(apiErrorMessage(err)).toBe('Invalid request: field “odd_field”: bad');
  });
});

describe('apiErrorMessage — package causes (plan console bilingue, I2)', () => {
  afterEach(() => setLocale('fr'));

  const refused = (
    code: string,
    details: Record<string, unknown>,
    message = 'Texte du serveur',
  ) => ({
    response: { data: { error: { code, message, details } } },
  });

  it('words the cause, in French as the server did and in English', () => {
    const invalid = refused(
      'package.invalid',
      { cause: { code: 'winget_id_invalid', params: {} } },
      'Identifiant winget invalide (ex. Mozilla.Firefox)',
    );
    expect(apiErrorMessage(invalid)).toBe(
      'Paquet invalide : Identifiant winget invalide (ex. Mozilla.Firefox)',
    );
    setLocale('en');
    expect(apiErrorMessage(invalid)).toBe(
      'Invalid package: Invalid winget identifier (e.g. Mozilla.Firefox)',
    );
  });

  it('words a refused upload name, a refused signature and a refused deployment', () => {
    setLocale('en');
    expect(
      apiErrorMessage(
        refused('package.file.name_invalid', {
          name: 'nul.txt',
          reason: 'nom réservé…',
          cause: { code: 'reserved', params: {} },
        }),
      ),
    ).toMatch(/^“nul\.txt” refused: name reserved by Windows/);
    expect(
      apiErrorMessage(
        refused('package.signature.invalid', { cause: { code: 'not_json', params: {} } }),
      ),
    ).toBe('Signature refused: The signature file is not JSON.');
    expect(
      apiErrorMessage(
        refused('package.not_ready', {
          problems: ['Aucun fichier déposé', '« a.exe » n’est pas dans le paquet'],
          causes: [
            { code: 'no_files', params: {} },
            { code: 'install_missing', params: { file: 'a.exe' } },
          ],
        }),
      ),
    ).toBe('This package cannot be deployed yet: No file uploaded; “a.exe” is not in the package');
  });

  it('falls back to the server’s sentence without a cause, or for an unknown one', () => {
    setLocale('en');
    expect(apiErrorMessage(refused('package.invalid', {}, 'Phrase du serveur'))).toBe(
      'Invalid package: Phrase du serveur',
    );
    expect(
      apiErrorMessage(refused('package.invalid', { cause: { code: 'brand_new' } }, 'Phrase')),
    ).toBe('Invalid package: Phrase');
    expect(
      apiErrorMessage(
        refused('package.not_ready', {
          problems: ['Nouveau problème'],
          causes: [{ code: 'brand_new', params: {} }],
        }),
      ),
    ).toBe('This package cannot be deployed yet: Nouveau problème');
  });
});

describe('postes a visit is refused for (maintenance.items.not_in_room)', () => {
  afterEach(() => setLocale('fr'));
  function notInRoom(count: number) {
    const hostnames = Array.from({ length: count }, (_, i) => `PC-${i + 1}`);
    const details = { hostnames };
    return { response: { data: { error: { code: 'maintenance.items.not_in_room', details } } } };
  }

  it('names a few postes as before', () => {
    expect(apiErrorMessage(notInRoom(5))).toBe(
      'Ces postes ne sont pas dans la salle de la séance : PC-1, PC-2, PC-3, PC-4, PC-5',
    );
  });

  it('names the first five of fifty, then how many more, in both languages', () => {
    expect(apiErrorMessage(notInRoom(50))).toBe(
      'Ces postes ne sont pas dans la salle de la séance : PC-1, PC-2, PC-3, PC-4, PC-5 et 45 autre(s)',
    );
    setLocale('en');
    expect(apiErrorMessage(notInRoom(50))).toBe(
      'These computers are not in the session’s room: PC-1, PC-2, PC-3, PC-4, PC-5 and 45 others',
    );
    expect(apiErrorMessage(notInRoom(6))).toBe(
      'These computers are not in the session’s room: PC-1, PC-2, PC-3, PC-4, PC-5 and 1 other',
    );
  });
});

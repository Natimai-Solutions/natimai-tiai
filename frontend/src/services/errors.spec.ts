import { describe, expect, it } from 'vitest';

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

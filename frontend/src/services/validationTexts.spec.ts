import { readFileSync } from 'node:fs';
import { afterEach, describe, expect, it } from 'vitest';
import { setLocale } from 'src/i18n';
import { apiErrorMessage } from './errors';

/**
 * The server's own French for each coded validation refusal, with its code
 * and parameters (backend/tests/test_validation_texts.py writes and checks
 * them). The console must write the same from the code.
 */
interface Case {
  code: string;
  params: Record<string, unknown>;
  message: string;
}
const CASES = JSON.parse(
  readFileSync(
    new URL('../../../backend/tests/data/validation_texts_fr.json', import.meta.url),
    'utf-8',
  ),
) as Case[];

function refused(c: Case, msg = `Value error, ${c.message}`) {
  return {
    response: {
      data: {
        error: {
          code: 'request.validation_error',
          details: {
            errors: [{ loc: ['body', 'odd'], msg, type: `tiai_${c.code}`, params: c.params }],
          },
        },
      },
    },
  };
}

afterEach(() => setLocale('fr'));

describe('validation refusals, from their codes', () => {
  it.each(CASES.map((c) => [c.code, c] as const))('%s: French as the server writes it', (_, c) => {
    // Worded from the code, not read from msg: a message that differs would show.
    expect(apiErrorMessage(refused(c, 'Value error, autre chose'))).toBe(
      `Requête invalide : champ « odd » : ${c.message}`,
    );
  });

  it('writes every case in English', () => {
    setLocale('en');
    for (const c of CASES) {
      const text = apiErrorMessage(refused(c));
      expect(text, c.code).toMatch(/^Invalid request: field “odd”: /);
      expect(text, c.code).not.toMatch(/[éèàç«»]| le | la | du /);
    }
  });

  it('shows the server’s text for a code it does not know, or Pydantic’s own', () => {
    setLocale('en');
    const unknown = refused({ code: 'brand_new', params: {}, message: 'nouveau refus' });
    expect(apiErrorMessage(unknown)).toBe('Invalid request: field “odd”: nouveau refus');
    const pydantic = {
      response: {
        data: {
          error: {
            code: 'request.validation_error',
            details: {
              errors: [{ loc: ['body', 'name'], msg: 'Field required', type: 'missing' }],
            },
          },
        },
      },
    };
    expect(apiErrorMessage(pydantic)).toBe('Invalid request: field “name”: Field required');
  });
});

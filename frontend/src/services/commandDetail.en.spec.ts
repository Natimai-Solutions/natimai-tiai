import { afterEach, describe, expect, it } from 'vitest';
import { setLocale } from 'src/i18n';
import { commandMessage } from './commands';

// Verification of 2026-11-18: a coded cause inside a coded sentence reached
// an English reader in French (« downloading setup.exe: serveur occupé »).
afterEach(() => setLocale('fr'));

describe('a coded detail inside a coded sentence', () => {
  const busy = {
    file: 'setup.exe',
    detail: 'serveur occupé (429)',
    detail_code: 'deploy.download.busy',
    detail_status: 429,
  };

  it('is worded in English', () => {
    setLocale('en');
    expect(commandMessage('deploy.download_failed', busy)).toBe(
      'downloading setup.exe: server busy (429)',
    );
    expect(
      commandMessage('deploy.authenticode_refused', {
        file: 'setup.exe',
        detail: 'fichier non signé (pas de signature Authenticode)',
        detail_code: 'deploy.not_signed',
      }),
    ).toBe('signature of setup.exe refused by Windows: unsigned file (no Authenticode signature)');
  });

  it('reads as the agent wrote it in French, and keeps an uncoded detail', () => {
    expect(commandMessage('deploy.download_failed', busy)).toBe(
      'téléchargement de setup.exe : serveur occupé (429)',
    );
    setLocale('en');
    expect(
      commandMessage('deploy.download_failed', {
        file: 'a.exe',
        detail: 'Access is denied.',
        detail_code: 'brand.new',
      }),
    ).toBe('downloading a.exe: Access is denied.');
  });
});

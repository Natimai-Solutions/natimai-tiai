import { afterEach, describe, expect, it, vi } from 'vitest';
import { setLocale } from 'src/i18n';

vi.mock('boot/axios', () => ({ api: { get: vi.fn(), post: vi.fn() } }));

import { commandMessage, commandResultText, type Command } from './commands';

/**
 * The agent's composite texts, coded since the verification of 2026-11-18
 * (they reached an English console in French): an install's report, the
 * steps of a Windows Update reset, a spooler reset that went partly, the
 * sentence after dism's output, and the two refusals of a deployment. The
 * French is checked against the agent's shared cases
 * (`commandResults.spec.ts`); here, the English and the failed command's
 * output.
 */
afterEach(() => setLocale('fr'));

const install = {
  selected: 4,
  installed: 3,
  skipped: 1,
  reboot: true,
  updates:
    'succeeded\t\tKB5063878 — 2025-08 Mise à jour cumulative\nfailed\t0x80240017\tKB5062660 — Broken\naborted\t0x00000000\tPilote',
};

const reset = {
  steps: [
    'stopped\twuauserv',
    'already_stopped\tcryptsvc',
    'renamed\tsoftware_distribution\tSoftwareDistribution.old',
    'rename_failed\tcatroot2\tC:\\Windows\\System32\\catroot2',
    'restart_failed\twuauserv',
  ].join('\n'),
  e1: 'suppression du renommage précédent (C:\\Windows\\System32\\catroot2.old) : Access is denied.',
  e1_code: 'wu_reset.backup_not_removed',
  e1_path: 'C:\\Windows\\System32\\catroot2.old',
  e1_detail: 'Access is denied.',
  e2: 'The service did not respond.',
};

describe('the composite texts of the agent, in English', () => {
  it('words an install report, the titles as Windows gave them', () => {
    setLocale('en');
    expect(commandMessage('wu.install_report', install)).toBe(
      [
        '4 updates selected, 3 installed.',
        '1 skipped: it needs user interaction, impossible from a service.',
        'KB5063878 — 2025-08 Mise à jour cumulative: installed',
        'KB5062660 — Broken: failed (0x80240017)',
        'Pilote: aborted (0x00000000)',
        '1 update could not be downloaded, so it was not installed.',
        '',
        'Restart required to finish the installation (“Restart the computer” command).',
      ].join('\n'),
    );
    expect(commandMessage('wu.install_report', { selected: 0, installed: 0, skipped: 0 })).toBe(
      'No applicable update: the computer is up to date.',
    );
  });

  it('words the steps of a reset and its verdict, each failure with its error', () => {
    setLocale('en');
    expect(commandMessage('wu_reset.report', reset)).toBe(
      [
        'Windows Update (wuauserv): stopped.',
        'Cryptographic Services (cryptsvc): already stopped.',
        'Windows Update store (SoftwareDistribution): renamed to SoftwareDistribution.old.',
        'FAILED — renaming C:\\Windows\\System32\\catroot2: removing the previous rename (C:\\Windows\\System32\\catroot2.old): Access is denied.',
        'FAILED — restarting the service Windows Update (wuauserv): The service did not respond.',
      ].join('\n'),
    );
    expect(
      commandMessage('wu_reset.incomplete', {
        failed: 'rename_failed\tcatroot2\tC:\\x\nrestart_failed\tbits',
      }),
    ).toBe(
      'incomplete reset: renaming C:\\x; restarting the service Background Intelligent Transfer Service (BITS) (bits)',
    );
    expect(commandMessage('wu_reset.report', { steps: 'kept\t\nnext\t' })).toBe(
      'No folder renamed: a service still holds the update store.\n\nWindows will rebuild these folders at the next check: run “Check for updates” to confirm the computer is back on track.',
    );
  });

  it('words a partial spooler reset, the queue’s error included', () => {
    setLocale('en');
    expect(commandMessage('spooler.report', { removed: 1, restarted: false })).toBe(
      'Print spooler stopped.\nPrint queue emptied (1 file).\nThe spooler could NOT be restarted.',
    );
    expect(
      commandMessage('spooler.report', {
        restarted: true,
        purge: '2 fichier(s) non supprimé(s), première erreur : Access is denied.',
        purge_code: 'spooler.files_not_removed',
        purge_failed: 2,
        purge_detail: 'Access is denied.',
      }),
    ).toBe(
      'Print spooler stopped.\nPrint queue only partly emptied: 2 files not deleted, first error: Access is denied.\nPrint spooler restarted.',
    );
  });

  it('words the sentence after dism’s output, which stays as dism wrote it', () => {
    setLocale('en');
    expect(commandMessage('dism.reboot_required', { output: 'L’opération a réussi.' })).toBe(
      'L’opération a réussi.\n\nRestart required to finish the operation.',
    );
  });

  it('words both refusals of a deployment, method A prefixed as the agent does', () => {
    setLocale('en');
    expect(
      commandMessage('deploy.both_refused', {
        b: 'signature invalide : le manifeste a changé depuis sa signature',
        b_code: 'deploy.signature.invalid',
        a: 'méthode A : seul un exécutable (.exe) signé par un éditeur approuvé peut être lancé — signez le paquet (méthode B)',
        a_code: 'deploy.method_a.exe_only',
      }),
    ).toBe(
      'method B: invalid signature: the manifest has changed since it was signed; method A: only an executable (.exe) signed by an approved publisher can be run — sign the package (method B)',
    );
    expect(
      commandMessage('deploy.both_refused', {
        b: 'x509: unknown authority',
        a: 'éditeur "X" non approuvé sur ce poste (DeployPublishers)',
        a_code: 'deploy.publisher_not_approved',
        a_publisher: '"X"',
      }),
    ).toBe(
      'method B: x509: unknown authority; method A: publisher "X" not approved on this computer (DeployPublishers)',
    );
  });
});

function failed(overrides: Partial<Command>): Command {
  return {
    id: 'c1',
    machine_id: 'm1',
    type: 'spooler_reset',
    status: 'failed',
    created_by: null,
    created_at: '2026-11-10T10:00:00Z',
    expires_at: '2026-11-10T11:00:00Z',
    delivered_at: null,
    started_at: null,
    finished_at: null,
    result_output: null,
    error: null,
    ...overrides,
  };
}

describe('the output of a failed command, when the agent wrote it', () => {
  const spooler = failed({
    result_output:
      "Spouleur d'impression arrêté.\nFile d'impression purgée (4 fichier(s)).\nLe spouleur n'a PAS pu être redémarré.",
    error: 'démarrage du spouleur : Access is denied.',
    result_code: 'spooler.start_failed',
    result_params: {
      detail: 'Access is denied.',
      output_code: 'spooler.report',
      output_removed: 4,
      output_restarted: false,
    },
  });

  it('reads as stored in French', () => {
    expect(commandResultText(spooler, 'output')).toBe(spooler.result_output);
    expect(commandResultText(spooler, 'error')).toBe(spooler.error);
  });

  it('is worded in English from the code beside the error’s', () => {
    setLocale('en');
    expect(commandResultText(spooler, 'output')).toBe(
      'Print spooler stopped.\nPrint queue emptied (4 files).\nThe spooler could NOT be restarted.',
    );
    expect(commandResultText(spooler, 'error')).toBe('starting the spooler: Access is denied.');
  });

  it('stays as stored without a code this console knows, or from an older agent', () => {
    setLocale('en');
    const newer = failed({
      ...spooler,
      result_params: { detail: 'x', output_code: 'spooler.from_the_future' },
    });
    expect(commandResultText(newer, 'output')).toBe(spooler.result_output);
    const older = failed({ ...spooler, result_params: { detail: 'Access is denied.' } });
    expect(commandResultText(older, 'output')).toBe(spooler.result_output);
  });
});

import { readFileSync } from 'node:fs';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { setLocale } from 'src/i18n';

vi.mock('boot/axios', () => ({ api: { get: vi.fn(), post: vi.fn() } }));

import {
  commandMessage,
  commandResultText,
  commandVerdictText,
  wakeDetailText,
  type Command,
} from './commands';

/**
 * The verdicts the server and the agent write into a command, with the codes
 * and parameters they store beside them (plan console bilingue, I3 and I5):
 * `backend/tests/test_command_texts.py` and `agent/internal/msg` write and
 * check these cases. The console must write the same French from the codes:
 * an installation updated to the bilingual console reads what it read before.
 */
interface Case {
  code: string;
  params: Record<string, unknown>;
  message: string;
}

function cases(path: string): Case[] {
  return JSON.parse(readFileSync(new URL(path, import.meta.url), 'utf-8')) as Case[];
}

const SERVER = cases('../../../backend/tests/data/command_texts_fr.json');
const AGENT = cases('../../../agent/internal/msg/testdata/messages_fr.json');

afterEach(() => setLocale('fr'));

function label(c: Case): string {
  return `${c.code}: ${c.message.slice(0, 50)}`;
}

/** The English text with the parameters' own values taken out. */
function ownWords(text: string, params: Record<string, unknown>): string {
  let out = text;
  for (const value of Object.values(params)) {
    if (typeof value === 'string' && value) out = out.split(value).join('');
  }
  return out;
}

describe('the verdicts, from their codes', () => {
  it('has the shared cases to check', () => {
    expect(SERVER.length).toBeGreaterThan(20);
    expect(AGENT.length).toBeGreaterThan(100);
  });

  it.each(SERVER.map((c) => [label(c), c] as const))(
    'writes in French what the server writes: %s',
    (_label, c) => {
      expect(commandMessage(c.code, c.params)).toBe(c.message);
    },
  );

  it.each(AGENT.map((c) => [label(c), c] as const))(
    'writes in French what the agent writes: %s',
    (_label, c) => {
      expect(commandMessage(c.code, c.params)).toBe(c.message);
    },
  );

  it.each([...SERVER, ...AGENT].map((c) => [label(c), c] as const))(
    'writes it in English: %s',
    (_label, c) => {
      setLocale('en');
      const english = commandMessage(c.code, c.params);
      expect(english).not.toBeNull();
      expect(english).not.toBe(c.message);
      expect(ownWords(english!, c.params)).not.toMatch(/[éèàùçâêîôû«»]/);
    },
  );

  it('words a few in English as an English admin would read them', () => {
    setLocale('en');
    expect(commandMessage('command.unanswered', { hours: 6 })).toBe(
      'No answer from the computer 6 h after delivery: the command is considered lost (computer off, agent stopped or updated while it ran). Run it again if needed.',
    );
    expect(commandMessage('wu.scan', { count: 1 })).toBe('1 pending update.');
    expect(commandMessage('wu.scan', { count: 7 })).toBe('7 pending updates.');
    expect(commandMessage('inventory.scan', { disks: 1, volumes: 2, nics: 1, software: 143 })).toBe(
      '1 disk, 2 volumes, 1 network card, 143 programs.',
    );
    expect(commandMessage('wol.relay_already', { state: 'delivered', minutes: 65 })).toBe(
      'Wake already handed to a relay computer for 1 h 05; nothing new was queued.',
    );
    expect(
      commandMessage('deploy.done', {
        action: 'install',
        name: '7-Zip 23.01',
        package_id: 'p',
        method: 'A',
        reboot: true,
        trust: 'publisher',
        by: 'Igor Pavlov',
      }),
    ).toBe(
      'Installation of 7-Zip 23.01 finished (method A, approved publisher: Igor Pavlov)\nRestart required to finish.',
    );
  });

  it('knows nothing of a code it was not given: the caller shows the text', () => {
    expect(commandMessage('agent.from_the_future', {})).toBeNull();
    expect(commandMessage('wol', {})).toBeNull();
    expect(commandMessage(null, null)).toBeNull();
  });

  it('signs a relayed verdict with the relay, as the server does', () => {
    const params = { mac: 'AA:BB:CC:DD:EE:FF', copies: 3, targets: 'x', relay: 'PC-12' };
    expect(commandMessage('wol.relay.sent', params)).toMatch(
      /^Relayé par PC-12 — Paquet magique émis vers AA:BB:CC:DD:EE:FF depuis ce poste/,
    );
    setLocale('en');
    expect(commandMessage('wol.relay.sent', params)).toMatch(
      /^Relayed by PC-12 — Magic packet sent to AA:BB:CC:DD:EE:FF from this computer — 3 copies/,
    );
  });
});

function row(overrides: Partial<Command>): Command {
  return {
    id: 'c1',
    machine_id: 'm1',
    type: 'flush_dns',
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

describe('commandResultText', () => {
  const merged = row({
    error: 'Poste fusionné : commande annulée',
    result_code: 'command.merged',
    result_params: {},
  });

  it('shows the stored French in French, and the English worded from the code', () => {
    expect(commandResultText(merged, 'error')).toBe('Poste fusionné : commande annulée');
    setLocale('en');
    expect(commandResultText(merged, 'error')).toBe('Computer merged: command cancelled');
  });

  it('shows a row without code — stored before, older agent, a tool — as stored', () => {
    setLocale('en');
    const old = row({ error: 'Poste fusionné : commande annulée' });
    expect(commandResultText(old, 'error')).toBe('Poste fusionné : commande annulée');
    const tool = row({ status: 'succeeded', result_output: 'Configuration IP de Windows' });
    expect(commandResultText(tool, 'output')).toBe('Configuration IP de Windows');
    const newer = row({ error: 'texte', result_code: 'agent.from_the_future' });
    expect(commandResultText(newer, 'error')).toBe('texte');
  });

  it('words the error of a failed command and the output of a succeeded one', () => {
    setLocale('en');
    // A failed sfc: the tool's output stays, the agent's verdict is worded.
    const sfc = row({
      status: 'failed',
      result_output: 'Protection des ressources Windows…',
      error: 'sfc a terminé en erreur (code 1)',
      result_code: 'sfc.failed',
      result_params: { code: '1' },
    });
    expect(commandResultText(sfc, 'output')).toBe('Protection des ressources Windows…');
    expect(commandResultText(sfc, 'error')).toBe('sfc ended with an error (code 1)');
    expect(commandVerdictText(sfc)).toBe('sfc ended with an error (code 1)');

    const scan = row({
      status: 'succeeded',
      result_output: '3 mise(s) à jour en attente.',
      result_code: 'wu.scan',
      result_params: { count: 3 },
    });
    expect(commandResultText(scan, 'output')).toBe('3 pending updates.');
    expect(commandResultText(scan, 'error')).toBe('');
    expect(commandVerdictText(scan)).toBe('3 pending updates.');
  });

  it('words the note of a text cut short, by the server or by the agent', () => {
    const server = row({ error: 'boom\n[…] sortie tronquée par le serveur' });
    const agent = row({
      status: 'succeeded',
      result_output: "Résultats\n[…] sortie tronquée à 64 Kio par l'agent",
    });
    expect(commandResultText(server, 'error')).toBe('boom\n[…] sortie tronquée par le serveur');
    setLocale('en');
    expect(commandResultText(server, 'error')).toBe('boom\n[…] output cut short by the server');
    expect(commandResultText(agent, 'output')).toBe(
      'Résultats\n[…] output cut short at 64 KiB by the agent',
    );
  });
});

describe('wakeDetailText', () => {
  const unknown = 'Poste introuvable : il a été supprimé ou fusionné.';

  it('words the detail of a wake from its code, in French as the server wrote it', () => {
    expect(wakeDetailText(unknown, 'wol.unknown_machine', {})).toBe(unknown);
    setLocale('en');
    expect(wakeDetailText(unknown, 'wol.unknown_machine', {})).toBe(
      'Computer not found: it was deleted or merged.',
    );
    expect(
      wakeDetailText('…', 'wol.relay_queued', {
        site_kind: 'location',
        site: 'Building A',
        peers: 3,
        ttl_minutes: 10,
      }),
    ).toMatch(
      /^Wake handed to the computers at the location “Building A”: 3 computers that are on/,
    );
  });

  it('falls back to the server’s sentence: no code, or one unknown here', () => {
    setLocale('en');
    expect(wakeDetailText(unknown)).toBe(unknown);
    expect(wakeDetailText(unknown, null, null)).toBe(unknown);
    expect(wakeDetailText(unknown, 'wol.from_the_future', {})).toBe(unknown);
    expect(wakeDetailText(null)).toBeNull();
  });
});

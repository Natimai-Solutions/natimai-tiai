import { mount } from '@vue/test-utils';
import { describe, expect, it } from 'vitest';
import MachineCommandsCard from './MachineCommandsCard.vue';
import type { Command } from 'src/services/commands';

function command(overrides: Partial<Command> = {}): Command {
  return {
    id: 'c1',
    machine_id: 'm1',
    type: 'package_install',
    status: 'succeeded',
    package_name: '7-Zip 23.01',
    created_by: 'admin@x',
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

function mountCard(commands: Command[], failed = false) {
  return mount(MachineCommandsCard, {
    props: {
      commands,
      loading: false,
      failed,
      pagination: { page: 1, rowsPerPage: 10, rowsNumber: commands.length },
    },
  });
}

describe('MachineCommandsCard', () => {
  // C5: a deployment names its package.
  it('names the package of a deployment', () => {
    expect(mountCard([command()]).text()).toContain('Installation de logiciel — 7-Zip 23.01');
  });

  // Item 1: an unread history is not « Aucune commande ».
  it('says the history could not be read instead of « Aucune commande »', () => {
    const text = mountCard([], true).text();
    expect(text).toContain('Impossible de charger les commandes');
    expect(text).not.toContain('Aucune commande');
  });
});

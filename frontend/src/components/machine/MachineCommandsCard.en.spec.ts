import { mount } from '@vue/test-utils';
import { nextTick } from 'vue';
import { afterEach, describe, expect, it } from 'vitest';
import { setLocale } from 'src/i18n';
import MachineCommandsCard from './MachineCommandsCard.vue';
import type { Command } from 'src/services/commands';

function command(overrides: Partial<Command> = {}): Command {
  return {
    id: 'c1',
    machine_id: 'm1',
    type: 'flush_dns',
    status: 'failed',
    created_by: 'admin@x',
    created_at: '2026-11-10T10:00:00Z',
    expires_at: '2026-11-10T11:00:00Z',
    delivered_at: null,
    started_at: null,
    finished_at: '2026-11-10T10:05:00Z',
    result_output: 'Windows IP Configuration',
    error: 'code 1',
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

afterEach(() => setLocale('fr'));

describe('MachineCommandsCard in English', () => {
  it('shows the history in English, with nothing left in French', () => {
    setLocale('en');
    const wrapper = mountCard([
      command(),
      command({ id: 'c2', type: 'package_install', package_name: '7-Zip', status: 'succeeded' }),
    ]);
    const text = wrapper.text();
    expect(text).toContain('Latest commands');
    expect(text).toContain('Flush the DNS cache');
    expect(text).toContain('Software installation — 7-Zip');
    expect(text).toContain('Failed');
    expect(text).toContain('Succeeded');
    for (const header of ['Type', 'Status', 'By', 'Created', 'Finished']) {
      expect(text).toContain(header);
    }
    expect(wrapper.find('[aria-label="Show the result"]').exists()).toBe(true);
    expect(wrapper.find('[aria-label="Show the error"]').exists()).toBe(true);
    expect(text).not.toMatch(/[éèàùçâêîôû«»]/);
  });

  it('says so when the history is empty or could not be read', () => {
    setLocale('en');
    expect(mountCard([]).text()).toContain('No commands.');
    expect(mountCard([], true).text()).toContain('the commands');
  });

  it('switches language live', async () => {
    const wrapper = mountCard([command()]);
    expect(wrapper.text()).toContain('Dernières commandes');
    expect(wrapper.text()).toContain('Vider le cache DNS');
    expect(wrapper.text()).toContain('Échec');
    setLocale('en');
    await nextTick();
    expect(wrapper.text()).toContain('Latest commands');
    expect(wrapper.text()).toContain('Flush the DNS cache');
    expect(wrapper.text()).toContain('Failed');
    expect(wrapper.text()).not.toContain('Dernières commandes');
  });
});

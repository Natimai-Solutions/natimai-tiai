import { flushPromises, mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import { QBtn } from 'quasar';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('src/services/directory', async (importOriginal) => ({
  ...(await importOriginal<typeof import('src/services/directory')>()),
  designateReader: vi.fn(),
  revokeReader: vi.fn(),
}));

import { designateReader, revokeReader } from 'src/services/directory';
import type { MachineDetail } from 'src/services/machines';
import { useAuthStore } from 'src/stores/auth';
import MachineDirectoryCard from './MachineDirectoryCard.vue';

function machine(fields: Partial<MachineDetail>): MachineDetail {
  return {
    id: 'm-1',
    domain: 'LYCEE',
    directory_mode: 'relay',
    ad_distinguished_name: 'CN=PC-1,OU=Profs,DC=lycee,DC=local',
    ad_ou: 'Profs',
    ad_location: null,
    dir_distinguished_name: 'CN=PC-1,OU=Salle B12,DC=lycee,DC=local',
    dir_ou: 'Salle B12',
    dir_location: null,
    directory_status: 'mismatch',
    directory_reader: false,
    ...fields,
  } as MachineDetail;
}

function mountCard(m: MachineDetail, perms = ['settings:write']) {
  setActivePinia(createPinia());
  useAuthStore().$patch({ user: { permissions: perms } as never });
  return mount(MachineDirectoryCard, { props: { machine: m } });
}

describe('MachineDirectoryCard', () => {
  beforeEach(() => {
    vi.mocked(designateReader).mockReset();
    vi.mocked(revokeReader).mockReset();
  });

  it('says nothing where the server does not read the directory', () => {
    const w = mountCard(machine({ directory_mode: 'off' }));
    expect(w.text()).toBe('');
  });

  it('shows the declaration beside the reading, the difference flagged', () => {
    const w = mountCard(machine({}));
    expect(w.find('[data-test="directory-status"]').text()).toContain('Écart');
    const rows = w.findAll('tbody tr');
    expect(rows[1]!.text()).toContain('Profs');
    expect(rows[1]!.text()).toContain('Salle B12');
    expect(rows[1]!.classes()).toContain('text-warn');
    expect(rows[2]!.classes()).not.toContain('text-warn');
  });

  it('designates the poste, and tells the page to reload', async () => {
    vi.mocked(designateReader).mockResolvedValue({} as never);
    const w = mountCard(machine({}));
    await w
      .findAllComponents(QBtn)
      .find((b) => b.text().includes('Désigner'))!
      .trigger('click');
    await flushPromises();
    expect(designateReader).toHaveBeenCalledWith('m-1');
    expect(w.emitted('changed')).toHaveLength(1);
  });

  it('withdraws a designation', async () => {
    vi.mocked(revokeReader).mockResolvedValue();
    const w = mountCard(
      machine({ directory_reader: true, directory_reader_since: '2026-11-20T08:00:00Z' }),
    );
    expect(w.text()).toContain('Lecteur d’annuaire depuis');
    await w
      .findAllComponents(QBtn)
      .find((b) => b.text().includes('Retirer'))!
      .trigger('click');
    await flushPromises();
    expect(revokeReader).toHaveBeenCalledWith('m-1');
  });

  it('offers no button without settings:write, nor on a workgroup poste', () => {
    expect(mountCard(machine({}), ['machine:read']).findAllComponents(QBtn)).toHaveLength(0);
    expect(mountCard(machine({ domain: null })).findAllComponents(QBtn)).toHaveLength(0);
  });
});

import { flushPromises, mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import { QBtn } from 'quasar';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { defineComponent, h } from 'vue';
import { createMemoryHistory, createRouter } from 'vue-router';

vi.mock('src/services/directory', async (importOriginal) => ({
  ...(await importOriginal<typeof import('src/services/directory')>()),
  getDirectoryState: vi.fn(),
  confirmMoves: vi.fn(),
  discardMoves: vi.fn(),
}));

import {
  confirmMoves,
  discardMoves,
  getDirectoryState,
  type DirectoryState,
} from 'src/services/directory';
import { useAuthStore } from 'src/stores/auth';
import SettingsDirectoryCard from './SettingsDirectoryCard.vue';

const Stub = defineComponent({ render: () => h('div') });

const state = (over: Partial<DirectoryState> = {}): DirectoryState => ({
  mode: 'relay',
  sync_minutes: 60,
  stale_hours: 72,
  confirm_moves: 20,
  room_source: 'ad_ou',
  domains: [
    {
      sid: 'S-1-5-21-1-2-3',
      name: 'lycee.local',
      netbios_name: 'LYCEE',
      last_read_at: '2026-11-21T08:00:00Z',
      last_reader: 'SRV-ADM',
      objects_read: 412,
      disagreement_at: null,
      disagreement: [],
      pending_count: 25,
      pending_since: '2026-11-21T08:00:00Z',
      pending_moves: [
        { machine_id: 'm1', hostname: 'PC-1', from_room: null, to_room: 'Salle B12' },
      ],
      readers: [{ id: 'r', hostname: 'SRV-ADM', domain: 'LYCEE', since: null, last_seen: '' }],
    },
  ],
  readers_waiting: [],
  domains_without_reader: ['college'],
  status_counts: { verified: 400, mismatch: 3 },
  ...over,
});

async function mountCard(perms: string[]) {
  setActivePinia(createPinia());
  const auth = useAuthStore();
  auth.$patch({ user: { permissions: perms } as never });
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', component: Stub },
      { path: '/machines', name: 'machines', component: Stub },
    ],
  });
  await router.push('/');
  const w = mount(SettingsDirectoryCard, { global: { plugins: [router] } });
  await flushPromises();
  return w;
}

describe('SettingsDirectoryCard', () => {
  beforeEach(() => {
    vi.mocked(getDirectoryState).mockReset();
    vi.mocked(confirmMoves).mockReset();
    vi.mocked(discardMoves).mockReset();
  });

  it('says the agents are taken at their word when the reading is off', async () => {
    vi.mocked(getDirectoryState).mockResolvedValue(state({ mode: 'off', domains: [] }));
    const w = await mountCard(['settings:read']);
    expect(w.find('[data-test="directory-mode"]').text()).toContain('DIRECTORY_VERIFY=off');
    expect(w.find('[data-test="domain-LYCEE"]').exists()).toBe(false);
  });

  it('shows each domain, its reader, the held moves, and the domains without one', async () => {
    vi.mocked(getDirectoryState).mockResolvedValue(state());
    const w = await mountCard(['settings:read', 'settings:write']);
    const domain = w.find('[data-test="domain-LYCEE"]');
    expect(domain.text()).toContain('par SRV-ADM : 412 objet(s)');
    expect(domain.text()).toContain('déplacerait 25 poste(s), plus que le seuil de 20');
    expect(domain.text()).toContain('PC-1 : aucune salle → Salle B12');
    expect(w.text()).toContain('sans lecteur : college');
    expect(w.text()).toContain('écarts : 3');

    vi.mocked(confirmMoves).mockResolvedValue({ moved: 25 });
    const confirm = w
      .findAllComponents(QBtn)
      .find((b) => b.text() === 'Appliquer les déplacements')!;
    await confirm.trigger('click');
    await flushPromises();
    // With what was shown: a reading taken since must ask again.
    expect(vi.mocked(confirmMoves).mock.calls[0]![0]).toBe('S-1-5-21-1-2-3');
    expect(vi.mocked(confirmMoves).mock.calls[0]![1]).toMatchObject({
      pending_since: '2026-11-21T08:00:00Z',
      pending_count: 25,
    });
    expect(getDirectoryState).toHaveBeenCalledTimes(2);
  });

  it('offers no button to a read-only account', async () => {
    vi.mocked(getDirectoryState).mockResolvedValue(state());
    const w = await mountCard(['settings:read']);
    expect(w.text()).not.toContain('Appliquer les déplacements');
  });

  it('shows nothing of the parc to an account confined to some places', async () => {
    vi.mocked(getDirectoryState).mockResolvedValue(state({ restricted: true, domains: [] }));
    const w = await mountCard(['settings:read', 'settings:write']);
    expect(w.text()).toContain('n’est pas affiché à un compte limité');
    expect(w.find('[data-test="directory-mode"]').exists()).toBe(false);
  });

  it('says so when the state cannot be read', async () => {
    vi.mocked(getDirectoryState).mockRejectedValueOnce(new Error('boom'));
    const w = await mountCard(['settings:read']);
    expect(w.text()).toContain('n’a pas pu être chargé');
  });
});

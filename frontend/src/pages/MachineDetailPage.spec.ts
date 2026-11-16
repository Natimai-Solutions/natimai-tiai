import { flushPromises, mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import { QTabPanels } from 'quasar';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { defineComponent, h } from 'vue';
import { createMemoryHistory, createRouter } from 'vue-router';

/**
 * The fiche against a fake server whose answers to `GET /machines/:id` are
 * held until the test releases them: the bugs here are all about which answer
 * lands when. Everything else the page asks for answers at once, empty.
 */
type Deferred = { resolve: (v: unknown) => void; reject: (e: unknown) => void };
const machineCalls: Record<string, Deferred[]> = {};
const calls: string[] = [];
// GETs answered with a 500 instead, for the specs of a side list failing.
const failing = new Map<string, number>();

vi.mock('boot/axios', () => {
  const page = { data: { items: [], total: 0 } };
  return {
    api: {
      get: vi.fn((url: string) => {
        calls.push(url);
        const status = failing.get(url);
        if (status) {
          return Promise.reject(
            Object.assign(new Error(`HTTP ${status}`), {
              isAxiosError: true,
              response: { status },
            }),
          );
        }
        const m = /^\/machines\/([^/]+)$/.exec(url);
        if (m) {
          return new Promise((resolve, reject) => {
            (machineCalls[m[1]!] ??= []).push({ resolve, reject });
          });
        }
        if (url === '/threats' || url === '/commands' || url.endsWith('/interventions')) {
          return Promise.resolve(page);
        }
        if (url === '/rooms/config') return Promise.resolve({ data: { manual: true } });
        if (url.endsWith('/duplicates')) return Promise.resolve({ data: [] });
        return Promise.reject(new Error(`unexpected GET ${url}`));
      }),
      post: vi.fn(),
      patch: vi.fn(),
      put: vi.fn(),
      delete: vi.fn(),
    },
  };
});

// Spied on rather than read off the axios mock: the service caches its answer
// for the session, so only the first mount of the file would reach the server.
vi.mock('src/services/rooms', async (importOriginal) => ({
  ...(await importOriginal<typeof import('src/services/rooms')>()),
  getRoomConfig: vi.fn(() => Promise.resolve({ manual: true })),
}));

import { api } from 'boot/axios';
import { getRoomConfig } from 'src/services/rooms';
import LoadErrorBanner from 'src/components/LoadErrorBanner.vue';
import CheckRequestDialog from 'src/components/check/CheckRequestDialog.vue';
import MachineCommandsCard from 'src/components/machine/MachineCommandsCard.vue';
import MachineMergeDialog from 'src/components/machine/MachineMergeDialog.vue';
import MachineStatusCard from 'src/components/machine/MachineStatusCard.vue';
import MachineThreatsCard from 'src/components/machine/MachineThreatsCard.vue';
import { QItem } from 'quasar';
import { tasksVersion } from 'src/composables/useTasksBadge';
import type { CheckPayload } from 'src/services/checks';
import { useAuthStore } from 'src/stores/auth';
import MachineDetailPage from './MachineDetailPage.vue';

const Stub = defineComponent({ render: () => h('div') });

function detail(id: string) {
  return {
    id,
    machine_uuid: `uuid-${id}`,
    hostname: `HOST-${id}`,
    is_online: true,
    last_seen: new Date().toISOString(),
    software: [],
    disks: [],
  };
}

const fail500 = {
  isAxiosError: true,
  response: { status: 500, data: { error: { code: 'internal.server_error' } } },
};

function answer(id: string, n = 0, over: Record<string, unknown> = {}) {
  machineCalls[id]![n]!.resolve({ data: { ...detail(id), ...over } });
}

async function mountPage(
  id: string,
  permissions: string[],
  query = '',
  stubs: Record<string, boolean> = {},
) {
  const pinia = createPinia();
  setActivePinia(pinia);
  useAuthStore().user = { id: 'u', email: 'a@b.c', permissions } as never;
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/machines', name: 'machines', component: Stub },
      { path: '/machines/:id', name: 'machine-detail', component: Stub },
    ],
  });
  await router.push(`/machines/${id}${query}`);
  const wrapper = mount(MachineDetailPage, {
    shallow: true,
    props: { id },
    // Shallow for speed, but the page sits in a q-page: its content is the slot.
    global: { plugins: [router, pinia], renderStubDefaultSlot: true, stubs },
  });
  await flushPromises();
  return wrapper;
}

describe('MachineDetailPage', () => {
  beforeEach(() => {
    for (const k of Object.keys(machineCalls)) delete machineCalls[k];
    calls.length = 0;
    failing.clear();
  });

  // Audit T14: machine:read alone opens the fiche, and nothing it may not
  // read is asked for — a 403 there used to blank the whole page.
  it('asks neither for threats nor for commands with machine:read alone, and shows the poste', async () => {
    const w = await mountPage('B', ['machine:read']);
    answer('B');
    await flushPromises();

    expect(calls).not.toContain('/threats');
    expect(calls).not.toContain('/commands');
    expect(w.find('h1').text()).toContain('HOST-B');
    expect(w.findComponent(LoadErrorBanner).exists()).toBe(false);
  });

  it('falls back to the default tab when the commands tab is linked without command:read', async () => {
    const w = await mountPage('B', ['machine:read'], '?tab=commands');
    answer('B');
    await flushPromises();

    expect(w.findComponent(QTabPanels).props('modelValue')).toBe('identity');
  });

  it('keeps the commands tab for an account that may read commands', async () => {
    const w = await mountPage('B', ['machine:read', 'command:read'], '?tab=commands');
    answer('B');
    await flushPromises();

    expect(w.findComponent(QTabPanels).props('modelValue')).toBe('commands');
  });

  // Audit T20 (B04, U01): walking on before the previous poste has answered.
  it('never shows the poste being left under the next one’s id', async () => {
    const w = await mountPage('A', ['machine:read']);
    answer('A');
    await flushPromises();

    // Next: B is asked for...
    await w.setProps({ id: 'B' });
    await flushPromises();
    // ...and Next again before B has answered.
    await w.setProps({ id: 'C' });
    await flushPromises();
    answer('B');
    await flushPromises();

    // B's answer is dropped, C is asked for, and the page waits for it.
    expect(w.find('h1').text()).not.toContain('HOST-B');
    expect(machineCalls.C).toHaveLength(1);

    machineCalls.C![0]!.reject(fail500);
    await flushPromises();

    expect(w.find('h1').text()).not.toContain('HOST-B');
    expect(w.findComponent(LoadErrorBanner).exists()).toBe(true);
  });

  it('shows the next poste once it answers, after the dropped one', async () => {
    const w = await mountPage('A', ['machine:read']);
    answer('A');
    await flushPromises();
    await w.setProps({ id: 'B' });
    await w.setProps({ id: 'C' });
    await flushPromises();
    answer('B');
    await flushPromises();
    answer('C');
    await flushPromises();

    expect(w.find('h1').text()).toContain('HOST-C');
  });

  it('drops a refresh of the previous poste that answers after the walk', async () => {
    const w = await mountPage('A', ['machine:read']);
    answer('A');
    await flushPromises();
    // A refresh of A is in flight (the « Actualiser » button)...
    const refresh = w.findAll('[aria-label="Actualiser"]');
    expect(refresh).toHaveLength(1);
    await refresh[0]!.trigger('click');
    await flushPromises();
    expect(machineCalls.A).toHaveLength(2);
    // ...when the reader walks to B, which then fails.
    await w.setProps({ id: 'B' });
    await flushPromises();
    answer('A', 1);
    await flushPromises();
    machineCalls.B![0]!.reject(fail500);
    await flushPromises();

    expect(w.find('h1').text()).not.toContain('HOST-A');
    expect(w.findComponent(LoadErrorBanner).exists()).toBe(true);
  });

  // Audit B19: a merge writes the duplicate's history into this poste's journal.
  it('reloads the journal of interventions after a merge', async () => {
    const w = await mountPage('B', ['machine:read', 'machine:write', 'intervention:read']);
    answer('B');
    await flushPromises();
    const journal = () => calls.filter((u) => u === '/machines/B/interventions').length;
    expect(journal()).toBe(1);

    w.findComponent(MachineMergeDialog).vm.$emit('merged');
    await flushPromises();
    answer('B', 1);
    await flushPromises();

    expect(journal()).toBe(2);
  });

  // Audit U19: a check asked for from the fiche changes « Mes tâches ».
  it('has the tasks badge read again once a check is asked for', async () => {
    vi.mocked(api.post).mockResolvedValue({ data: {} });
    const w = await mountPage('B', ['machine:read', 'check:write']);
    answer('B');
    await flushPromises();
    const before = tasksVersion.value;

    const ask = w.findAllComponents(CheckRequestDialog)[0]!.props('save') as (
      payload: CheckPayload,
    ) => Promise<void>;
    const done = ask({ assigned_to_id: null, instructions: 'Écran noir' });
    await flushPromises();
    answer('B', 1);
    await done;

    expect(api.post).toHaveBeenCalledWith('/machines/B/check', expect.anything());
    expect(tasksVersion.value).toBe(before + 1);
  });

  // Audit U19: handing an open check to somebody else moves it from one
  // « Mes tâches » to another.
  it('has the tasks badge read again once the open check is edited', async () => {
    vi.mocked(api.patch).mockResolvedValue({ data: {} });
    const w = await mountPage('B', ['machine:read', 'check:write']);
    answer('B', 0, {
      open_check: {
        id: 'c-1',
        requested_by: 'Alice',
        assigned_to: null,
        instructions: null,
        created_at: '2026-11-10T20:00:00Z',
      },
    });
    await flushPromises();
    const before = tasksVersion.value;

    const edit = w.findAllComponents(CheckRequestDialog)[1]!.props('save') as (
      payload: CheckPayload,
    ) => Promise<void>;
    const done = edit({ assigned_to_id: 'u-2', instructions: null });
    await flushPromises();
    answer('B', 1);
    await done;

    expect(api.patch).toHaveBeenCalledWith('/checks/c-1', expect.anything());
    expect(tasksVersion.value).toBe(before + 1);
  });

  // Audit U19: a poste follows its room's maintenance owner and cycle.
  it('has the tasks badge read again once the poste is moved to another room', async () => {
    vi.mocked(api.post).mockReset();
    vi.mocked(api.post).mockResolvedValue({ data: { moved: 1, mismatched: [] } });
    const w = await mountPage('B', ['machine:read', 'room:write']);
    answer('B');
    await flushPromises();
    const before = tasksVersion.value;

    // « Affecter à une salle » opens the dialog on « Sans salle »…
    await w.find('[icon="meeting_room"]').trigger('click');
    await flushPromises();
    // …and « Enregistrer » files the poste there.
    await w.find('[label="Enregistrer"]').trigger('click');
    await flushPromises();

    expect(api.post).toHaveBeenCalledWith('/rooms/unassign', { machine_ids: ['B'] });
    expect(tasksVersion.value).toBe(before + 1);
  });

  it('counts a software list the server cut short as « n+ » on its tab', async () => {
    const software = [{ software_id: 1 }, { software_id: 2 }];
    const w = await mountPage('B', ['machine:read']);
    answer('B', 0, { software, software_truncated: true });
    await flushPromises();
    const tab = () => w.find('[name="software"]').text().replace(/\s+/g, '');
    expect(tab()).toBe('2+');

    // A complete list — or an older server, which says nothing — is counted as it is.
    await w.setProps({ id: 'C' });
    await flushPromises();
    answer('C', 0, { software });
    await flushPromises();
    expect(tab()).toBe('2');
  });

  it('leaves the tasks badge alone when the move is refused', async () => {
    vi.mocked(api.post).mockReset();
    vi.mocked(api.post).mockRejectedValue(fail500);
    const w = await mountPage('B', ['machine:read', 'room:write']);
    answer('B');
    await flushPromises();
    const before = tasksVersion.value;

    await w.find('[icon="meeting_room"]').trigger('click');
    await flushPromises();
    await w.find('[label="Enregistrer"]').trigger('click');
    await flushPromises();

    expect(api.post).toHaveBeenCalledTimes(1);
    expect(tasksVersion.value).toBe(before);
  });

  // Item 1: a side list failing must never read as « nothing there ».
  describe('a side list that fails', () => {
    it('flags the threats as unread on the card and on the head of the fiche', async () => {
      failing.set('/threats', 500);
      const w = await mountPage('B', ['machine:read', 'threat:read'], '?tab=antivirus');
      answer('B');
      await flushPromises();

      expect(w.findComponent(MachineStatusCard).props('threatsFailed')).toBe(true);
      expect(w.findComponent(MachineThreatsCard).props('failed')).toBe(true);

      // Back online: the next load clears the flag.
      failing.clear();
      await w.find('[aria-label="Actualiser"]').trigger('click');
      await flushPromises();
      answer('B', 1);
      await flushPromises();
      expect(w.findComponent(MachineStatusCard).props('threatsFailed')).toBe(false);
    });

    it('flags the commands as unread on their card', async () => {
      failing.set('/commands', 500);
      const w = await mountPage('B', ['machine:read', 'command:read'], '?tab=commands');
      answer('B');
      await flushPromises();

      expect(w.findComponent(MachineCommandsCard).props('failed')).toBe(true);
      expect(w.findComponent(MachineStatusCard).props('threatsFailed')).toBe(false);
    });
  });

  // Item 2 / 11: an id nobody knows — or that is not even an id.
  it.each([404, 422])(
    'says « Poste introuvable » for a %i, with no retry and no action',
    async (status) => {
      // The journal fails the same way, and must not add a technical toast.
      failing.set('/machines/pas-un-uuid/interventions', status);
      const w = await mountPage('pas-un-uuid', [
        'machine:read',
        'machine:write',
        'command:execute',
        'intervention:read',
      ]);
      machineCalls['pas-un-uuid']![0]!.reject({
        isAxiosError: true,
        response: {
          status,
          data: {
            error: { code: 'request.validation_error', message: 'Input should be a valid UUID' },
          },
        },
      });
      await flushPromises();

      expect(w.text()).toContain('Poste introuvable');
      expect(w.text()).not.toContain('valid UUID');
      expect(w.findComponent(LoadErrorBanner).exists()).toBe(false);
      expect(w.find('[label="Action"]').exists()).toBe(false);
      expect(w.find('[icon="merge"]').exists()).toBe(false);
      expect(w.find('[label="Révoquer le token"]').exists()).toBe(false);
      expect(document.body.textContent).not.toContain('Historique indisponible');
    },
  );

  // Item 5: a double click on a menu entry queues the command once.
  it('sends a command once on a double click of its menu entry', async () => {
    let release: (v: unknown) => void = () => undefined;
    vi.mocked(api.post).mockReset();
    vi.mocked(api.post).mockImplementation(() => new Promise((resolve) => (release = resolve)));
    const w = await mountPage('B', ['machine:read', 'command:execute']);
    answer('B');
    await flushPromises();

    const entry = w.findAllComponents(QItem).find((i) => i.text().includes('Vider le cache DNS'))!;
    // Two clicks before the first answer: the menu has not closed yet.
    entry.vm.$emit('click');
    entry.vm.$emit('click');
    release({ data: { created: ['c'], count: 1 } });
    await flushPromises();

    expect(vi.mocked(api.post).mock.calls.filter(([url]) => url === '/commands')).toHaveLength(1);
  });

  // C3: a revoked poste takes no command; the menu says why.
  it('disables the action menu of a poste whose token is revoked', async () => {
    const w = await mountPage('B', ['machine:read', 'command:execute']);
    answer('B', 0, { token_revoked: true });
    await flushPromises();

    expect(w.find('[label="Action"]').attributes('disable')).toBe('true');
    expect(w.find('[data-test="action-menu"]').text()).toContain('Token révoqué');
  });

  // C4: where the standing command is, in the notification.
  it('says the command is already running on the poste', async () => {
    vi.mocked(api.post).mockReset();
    vi.mocked(api.post).mockResolvedValue({
      data: { created: [], count: 0, skipped: 1, reason: 'running' },
    });
    const w = await mountPage('B', ['machine:read', 'command:execute']);
    answer('B');
    await flushPromises();
    const notify = vi.spyOn(w.vm.$q, 'notify').mockImplementation(() => () => undefined);

    w.findAllComponents(QItem)
      .find((i) => i.text().includes('Vider le cache DNS'))!
      .vm.$emit('click');
    await flushPromises();

    expect(notify).toHaveBeenCalledWith(
      expect.objectContaining({
        message: '« Vider le cache DNS » est déjà en cours sur ce poste.',
      }),
    );
    notify.mockRestore();
  });

  // C1: « Confirmer l'identité » beside « Fusionner un doublon ».
  it('confirms the identity of a poste after a confirmation', async () => {
    vi.mocked(api.post).mockReset();
    vi.mocked(api.post).mockResolvedValue({ data: {} });
    const w = await mountPage('B', ['machine:read', 'machine:write'], '', { QBanner: false });
    answer('B', 0, { needs_verification: true });
    await flushPromises();
    const dialog = vi.spyOn(w.vm.$q, 'dialog').mockReturnValue({
      onOk: (fn: () => void) => {
        fn();
        return { onCancel: () => undefined };
      },
    } as never);

    await w.find('[label="Confirmer l\'identité"]').trigger('click');
    await flushPromises();

    expect(dialog).toHaveBeenCalled();
    expect(api.post).toHaveBeenCalledWith('/machines/B/confirm-identity');
    dialog.mockRestore();
  });

  it('offers no identity confirmation to an account that may not merge', async () => {
    const w = await mountPage('B', ['machine:read'], '', { QBanner: false });
    answer('B', 0, { needs_verification: true });
    await flushPromises();

    expect(w.find('[label="Confirmer l\'identité"]').exists()).toBe(false);
  });

  // Item 4: the room settings are asked only of an account that may place postes.
  it('asks for the room settings only with room:write', async () => {
    vi.mocked(getRoomConfig).mockClear();
    await mountPage('B', ['machine:read']);
    expect(getRoomConfig).not.toHaveBeenCalled();
    await mountPage('B', ['machine:read', 'room:write']);
    expect(getRoomConfig).toHaveBeenCalledTimes(1);
  });
});

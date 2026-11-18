import { flushPromises, mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { defineComponent, h } from 'vue';
import { createMemoryHistory, createRouter } from 'vue-router';

const listCalls: unknown[] = [];
const getCalls: string[] = [];
const neighbourCalls: unknown[] = [];
// The list answers no poste at all (a filter nothing matches).
const emptyParc = { value: false };
// What `/stats/overview` answers; null: refused, as for the other side lists.
const overview: { value: Record<string, unknown> | null } = { value: null };

// The list against a fake server: three postes out of a long search, and the
// rest of what the page asks for at mount answered empty or refused (the
// fleet options are best-effort side lists).
vi.mock('boot/axios', () => ({
  api: {
    get: vi.fn((url: string, cfg?: { params?: unknown }) => {
      getCalls.push(url);
      if (url === '/machines') {
        listCalls.push(cfg?.params);
        const items = emptyParc.value
          ? []
          : ['a', 'b', 'c'].map((id) => ({ id, hostname: id, machine_uuid: id }));
        return Promise.resolve({
          data: {
            items,
            total: emptyParc.value ? 0 : 800,
            page: 1,
            page_size: 50,
            agent_latest_version: null,
            usage_days: 7,
            usage_low_hours: 1,
            usage_high_hours: 10,
          },
        });
      }
      if (url === '/rooms/config') return Promise.resolve({ data: { manual: true } });
      if (url === '/stats/overview' && overview.value) {
        return Promise.resolve({ data: overview.value });
      }
      if (url.endsWith('/neighbours')) {
        neighbourCalls.push(cfg?.params);
        return Promise.resolve({
          data: { previous: null, next: null, rank: 0, total: 3, cursor: 'place-of-a' },
        });
      }
      return Promise.reject(new Error(`unexpected GET ${url}`));
    }),
    post: vi.fn(),
    patch: vi.fn(),
    put: vi.fn(),
    delete: vi.fn(),
  },
}));

import CheckRequestDialog from 'src/components/check/CheckRequestDialog.vue';
import MachinesBulkBar from 'src/components/machines-list/MachinesBulkBar.vue';
import MachinesFiltersBar from 'src/components/machines-list/MachinesFiltersBar.vue';
import MachinesTable from 'src/components/machines-list/MachinesTable.vue';
import { resetFleetThresholds } from 'src/composables/useFleetThresholds';
import { useMachineNavigation } from 'src/composables/useMachineNavigation';
import { useAuthStore } from 'src/stores/auth';
import { emptyMachineFilters } from 'src/utils/machineListFilters';
import MachinesPage from './MachinesPage.vue';

const Stub = defineComponent({ render: () => h('div') });

async function mountList(path: string, permissions = ['machine:read', 'command:execute']) {
  const pinia = createPinia();
  setActivePinia(pinia);
  useAuthStore().user = {
    id: 'u',
    email: 'a@b.c',
    permissions,
    preferences: {},
  } as never;
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/machines', name: 'machines', component: Stub },
      { path: '/machines/:id', name: 'machine-detail', component: Stub },
    ],
  });
  await router.push(path);
  const wrapper = mount(MachinesPage, {
    shallow: true,
    global: { plugins: [router, pinia], renderStubDefaultSlot: true },
  });
  await flushPromises();
  return { wrapper, router };
}

describe('MachinesPage — selection (audit B05)', () => {
  beforeEach(() => {
    listCalls.length = 0;
  });

  async function selectTwo(wrapper: Awaited<ReturnType<typeof mountList>>['wrapper']) {
    const table = wrapper.findComponent(MachinesTable);
    table.vm.$emit('update:selected', (table.props('rows') as unknown[]).slice(0, 2));
    await flushPromises();
    expect(wrapper.findComponent(MachinesBulkBar).props('count')).toBe(2);
  }

  it('drops the selection on a filter change', async () => {
    const { wrapper } = await mountList('/machines?room=B12');
    await selectTwo(wrapper);
    wrapper
      .findComponent(MachinesFiltersBar)
      .vm.$emit('update:modelValue', { ...emptyMachineFilters(), room: 'B14' });
    await flushPromises();

    expect(wrapper.findComponent(MachinesBulkBar).props('count')).toBe(0);
  });

  // The drawer's « Postes » link: the same page, the query dropped, without
  // going through any of the page's own handlers.
  it('drops the selection when the query changes from outside the page', async () => {
    const { wrapper, router } = await mountList('/machines?room=B12');
    await selectTwo(wrapper);
    await router.push({ name: 'machines' });
    await flushPromises();

    expect(wrapper.findComponent(MachinesBulkBar).props('count')).toBe(0);
    // The list reloaded on the new, unfiltered search.
    expect(listCalls.at(-2)).toHaveProperty('room_id', 'B12');
    expect(listCalls.at(-1)).not.toHaveProperty('room_id');
  });

  it('keeps the selection across a navigation to the same search', async () => {
    const { wrapper, router } = await mountList('/machines?room=B12');
    await selectTwo(wrapper);
    await router.replace({ name: 'machines', query: { room: 'B12' }, hash: '#x' });
    await flushPromises();

    expect(wrapper.findComponent(MachinesBulkBar).props('count')).toBe(2);
  });
});

describe('MachinesPage — what a read-only account is offered (item 4)', () => {
  beforeEach(() => {
    getCalls.length = 0;
  });

  it('offers no selection column and asks for no room listing without the rights', async () => {
    const { wrapper } = await mountList('/machines', ['machine:read']);

    expect(wrapper.findComponent(MachinesTable).props('selectable')).toBe(false);
    expect(wrapper.findComponent(MachinesFiltersBar).props('canReadRooms')).toBe(false);
    expect(getCalls.filter((u) => u.startsWith('/rooms'))).toEqual([]);
  });

  it('keeps the selection for an account with a bulk action to run', async () => {
    const { wrapper } = await mountList('/machines', ['machine:read', 'command:execute']);
    expect(wrapper.findComponent(MachinesTable).props('selectable')).toBe(true);
  });
});

// Surviving mutations of the review: wiring that only the leaf components
// tested.
describe('MachinesPage — what it hands to its pieces', () => {
  beforeEach(() => {
    resetFleetThresholds();
    overview.value = null;
    neighbourCalls.length = 0;
  });

  it('colours the disk bars by the threshold of the parc', async () => {
    overview.value = { low_disk_free_percent: 30 };
    const { wrapper } = await mountList('/machines');
    expect(wrapper.findComponent(MachinesTable).props('lowDiskPercent')).toBe(30);
  });

  it('leaves the default threshold to the table while the parc’s is unknown', async () => {
    const { wrapper } = await mountList('/machines');
    expect(wrapper.findComponent(MachinesTable).props('lowDiskPercent')).toBeUndefined();
  });

  // Review, « partial filter values »: the bar may say that an exact value
  // matches nothing only over a list the server answered empty.
  it('tells the filters bar when the server answered no poste', async () => {
    const full = await mountList('/machines?hw_model=OptiPlex');
    expect(full.wrapper.findComponent(MachinesFiltersBar).props('listEmpty')).toBe(false);

    emptyParc.value = true;
    try {
      const empty = await mountList('/machines?hw_model=OptiPlex');
      expect(empty.wrapper.findComponent(MachinesFiltersBar).props('listEmpty')).toBe(true);
    } finally {
      emptyParc.value = false;
    }
  });

  it('gives each name its fiche, with the search and the rank of the row', async () => {
    const { wrapper } = await mountList('/machines?search=pc&page=2&page_size=25');
    const detailRoute = wrapper.findComponent(MachinesTable).props('detailRoute') as (
      row: { id: string },
      index: number,
    ) => unknown;
    expect(detailRoute({ id: 'b' }, 1)).toEqual({
      name: 'machine-detail',
      params: { id: 'b' },
      query: { search: 'pc', page: '2', page_size: '25', i: '26' },
    });
  });

  // Review finding 1: the draft of the bulk request is tied to its selection.
  it('tells the request dialog which postes are selected', async () => {
    const { wrapper } = await mountList('/machines', ['machine:read', 'check:write']);
    wrapper.findComponent(MachinesTable).vm.$emit('update:selected', [{ id: 'c' }, { id: 'a' }]);
    await flushPromises();
    const dialog = wrapper.findComponent(CheckRequestDialog);
    expect(dialog.props('machineIds')).toEqual(['c', 'a']);
    expect(dialog.props('machineId')).toBeUndefined();
  });

  // A walk through the fiches remembers where each poste stood, to go on from
  // there. Back on the list, the next fiche opened is placed where it stands
  // now: the list forgets the walk as it mounts.
  it('forgets the places of the last walk when the list is shown again', async () => {
    const pinia = createPinia();
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: '/machines/:id', name: 'machine-detail', component: Stub }],
    });
    const Fiche = defineComponent({
      setup() {
        useMachineNavigation();
        return () => h('div');
      },
    });
    async function openFiche() {
      await router.push('/machines/a?i=0');
      const fiche = mount(Fiche, { global: { plugins: [router, pinia] } });
      await flushPromises();
      fiche.unmount();
      await router.push('/machines/elsewhere');
    }

    await openFiche();
    await openFiche();
    // The second visit of the walk goes on from the place the first one learnt.
    expect(neighbourCalls).toHaveLength(2);
    expect(neighbourCalls[0]).not.toHaveProperty('cursor');
    expect(neighbourCalls[1]).toHaveProperty('cursor', 'place-of-a');

    await mountList('/machines');
    await openFiche();
    expect(neighbourCalls[2]).not.toHaveProperty('cursor');
  });
});

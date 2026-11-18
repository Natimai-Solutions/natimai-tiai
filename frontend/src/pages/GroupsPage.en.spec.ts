import { flushPromises, mount } from '@vue/test-utils';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { nextTick } from 'vue';

vi.mock('src/services/groups', async (importOriginal) => ({
  ...(await importOriginal<typeof import('src/services/groups')>()),
  listGroups: vi.fn(),
}));
vi.mock('src/services/machines', async (importOriginal) => ({
  ...(await importOriginal<typeof import('src/services/machines')>()),
  listLocations: vi.fn(),
}));
vi.mock('src/services/rooms', async (importOriginal) => ({
  ...(await importOriginal<typeof import('src/services/rooms')>()),
  listBuildings: vi.fn(),
  listRooms: vi.fn(),
}));
vi.mock('src/stores/auth', () => ({
  useAuthStore: () => ({
    fetchMe: () => Promise.resolve(),
    can: () => true,
    user: { id: 'me' },
  }),
}));

import { setLocale } from 'src/i18n';
import { listGroups, type Group } from 'src/services/groups';
import { listLocations } from 'src/services/machines';
import { listBuildings, listRooms } from 'src/services/rooms';
import GroupsPage from './GroupsPage.vue';

function group(over: Partial<Group>): Group {
  return {
    id: 'g',
    name: 'Group',
    description: null,
    builtin_key: null,
    is_admin: false,
    permissions: [],
    scope: null,
    member_count: 0,
    created_at: '',
    updated_at: '',
    ...over,
  };
}

const groups: Group[] = [
  group({ id: 'g-admin', name: 'Admins', builtin_key: 'admin', is_admin: true }),
  group({
    id: 'g-north',
    name: 'North',
    permissions: ['machine:read', 'command:read'],
    scope: { locations: ['North site'], buildings: [], rooms: ['r-gone'] },
    scope_labels: [
      { kind: 'location', id: 'North site', label: 'North site', exists: true },
      { kind: 'room', id: 'r-gone', label: 'r-gone', exists: false },
    ],
    member_count: 3,
  }),
  group({ id: 'g-empty', name: 'Empty' }),
];

interface PageApi {
  openEdit: (group: Group) => void;
}

async function mountPage() {
  const wrapper = mount(GroupsPage, {
    attachTo: document.body,
    global: { stubs: { QPage: { template: '<div><slot /></div>' } } },
  });
  await flushPromises();
  return { wrapper, vm: wrapper.vm as unknown as PageApi };
}

afterEach(() => {
  setLocale('fr');
  document.body.innerHTML = '';
});

describe('GroupsPage in English', () => {
  beforeEach(() => {
    vi.mocked(listGroups).mockResolvedValue(groups);
    vi.mocked(listLocations).mockResolvedValue([]);
    vi.mocked(listBuildings).mockResolvedValue([]);
    vi.mocked(listRooms).mockResolvedValue([]);
  });

  it('reads in English, with no French left', async () => {
    setLocale('en');
    const { wrapper } = await mountPage();
    const text = wrapper.text();
    expect(text).toContain('Groups');
    expect(text).toContain('New group');
    expect(text).toContain('An account may do what its groups grant it');
    for (const header of ['Group', 'Permissions', 'Computers', 'Accounts']) {
      expect(wrapper.find('thead').text()).toContain(header);
    }
    expect(text).toContain('All permissions');
    expect(text).toContain('Computers — view');
    expect(text).toContain('Commands — view the history');
    expect(text).toContain('North site');
    expect(text).toContain('Deleted place');
    expect(text).toContain('Whole fleet');
    expect(text).toContain('None');
    expect(wrapper.find('button[aria-label="Actions for North"]').exists()).toBe(true);
    expect(text).not.toMatch(/[éèàùç«»]/);
    wrapper.unmount();
  });

  it('words the group form and its permission grid', async () => {
    setLocale('en');
    const { wrapper, vm } = await mountPage();
    vm.openEdit(groups[1]!);
    await flushPromises();
    const text = document.body.textContent ?? '';
    expect(text).toContain('Edit the group');
    expect(text).toContain('Ticking an edit or run permission');
    expect(text).toContain('Rooms and buildings');
    expect(text).toContain('Run the risky commands');
    expect(text).toContain('Computers covered');
    expect(text).toContain('Locations');
    expect(text).toContain('As the agents report them; free text allowed');
    expect(text).toContain('Save');
    expect(text).not.toMatch(/[éèàùç«»]/);
    wrapper.unmount();
  });

  it('switches language while open', async () => {
    const { wrapper } = await mountPage();
    expect(wrapper.text()).toContain('Tous les droits');
    expect(wrapper.text()).toContain('Postes — consulter');

    setLocale('en');
    await nextTick();
    expect(wrapper.text()).toContain('All permissions');
    expect(wrapper.text()).toContain('Computers — view');
    expect(wrapper.find('thead').text()).toContain('Permissions');
    expect(wrapper.text()).not.toContain('Tous les droits');
    wrapper.unmount();
  });
});

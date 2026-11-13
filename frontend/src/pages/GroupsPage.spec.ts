import { flushPromises, mount } from '@vue/test-utils';
import { QSelect } from 'quasar';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('src/services/groups', async (importOriginal) => ({
  ...(await importOriginal<typeof import('src/services/groups')>()),
  listGroups: vi.fn(),
  createGroup: vi.fn(),
  updateGroup: vi.fn(),
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
// The page reads the profile again after a save; nothing to read here.
vi.mock('src/stores/auth', () => ({
  useAuthStore: () => ({ fetchMe: () => Promise.resolve(), can: () => true, user: { id: 'me' } }),
}));

import { createGroup, listGroups, updateGroup, type Group } from 'src/services/groups';
import { listLocations } from 'src/services/machines';
import { listBuildings, listRooms } from 'src/services/rooms';
import GroupsPage from './GroupsPage.vue';

const restricted = {
  id: 'g-1',
  name: 'Nord',
  description: null,
  permissions: ['machine:read'],
  scope: { locations: ['Lycée Nord'], buildings: [], rooms: [] },
  is_admin: false,
  is_builtin: false,
  member_count: 2,
} as unknown as Group;
const wholeParc = { ...restricted, id: 'g-2', name: 'Tous', scope: null } as unknown as Group;

/** What the page keeps to itself, reached the way the row menu would. */
interface GroupsApi {
  openCreate: () => void;
  openEdit: (group: Group) => void;
  form: { name: string; scope: { locations: string[] } };
}

async function mountPage() {
  const wrapper = mount(GroupsPage, {
    attachTo: document.body,
    global: { stubs: { QPage: { template: '<div><slot /></div>' } } },
  });
  await flushPromises();
  return { wrapper, vm: wrapper.vm as unknown as GroupsApi };
}

/** The form lives in a portal under <body>, not under the wrapper. */
async function submit() {
  document
    .querySelector('.q-dialog form')!
    .dispatchEvent(new Event('submit', { cancelable: true, bubbles: true }));
  await flushPromises();
}

function pluginButton(label: string): HTMLElement {
  return [...document.querySelectorAll<HTMLElement>('.q-dialog-plugin button')].find((b) =>
    b.textContent?.includes(label),
  )!;
}

async function typeLocation(
  wrapper: Awaited<ReturnType<typeof mountPage>>['wrapper'],
  text: string,
) {
  const input = wrapper.findAllComponents(QSelect)[0]!.find('input');
  (input.element as HTMLInputElement).focus();
  await input.setValue(text);
  await flushPromises();
}

describe('GroupsPage — scope (audit T26)', () => {
  beforeEach(() => {
    vi.mocked(listGroups).mockResolvedValue([restricted, wholeParc]);
    vi.mocked(listLocations).mockResolvedValue([{ name: 'Lycée A', count: 1 }] as never);
    vi.mocked(listBuildings).mockResolvedValue([]);
    vi.mocked(listRooms).mockResolvedValue([]);
    vi.mocked(createGroup)
      .mockReset()
      .mockResolvedValue({} as never);
    vi.mocked(updateGroup)
      .mockReset()
      .mockResolvedValue({} as never);
  });
  afterEach(() => {
    document.body.innerHTML = '';
  });

  it('keeps a location typed without Entrée when the form is saved', async () => {
    const { wrapper, vm } = await mountPage();
    vm.openCreate();
    await flushPromises();
    vm.form.name = 'Techniciens Nord';
    await typeLocation(wrapper, 'Lycée Nord');
    await submit();

    expect(createGroup).toHaveBeenCalledWith(
      expect.objectContaining({
        scope: expect.objectContaining({ locations: ['Lycée Nord'] }),
      }),
    );
    // Restricted: nothing to confirm.
    expect(document.body.textContent).not.toContain('Enregistrer pour tout le parc');
    wrapper.unmount();
  });

  it('turns a typed location into a chip when the field loses focus', async () => {
    const { wrapper, vm } = await mountPage();
    vm.openCreate();
    await flushPromises();
    await typeLocation(wrapper, 'Lycée Nord');
    wrapper.findAllComponents(QSelect)[0]!.vm.$emit('blur', new Event('blur'));
    await flushPromises();

    expect(vm.form.scope.locations).toEqual(['Lycée Nord']);
    wrapper.unmount();
  });

  it('asks before creating a group over the whole parc', async () => {
    const { wrapper, vm } = await mountPage();
    vm.openCreate();
    await flushPromises();
    vm.form.name = 'Partout';
    await submit();

    expect(createGroup).not.toHaveBeenCalled();
    expect(document.body.textContent).toContain('Enregistrer pour tout le parc');

    pluginButton('Revenir au formulaire').click();
    await flushPromises();
    expect(createGroup).not.toHaveBeenCalled();

    await submit();
    pluginButton('Enregistrer pour tout le parc').click();
    await flushPromises();
    expect(createGroup).toHaveBeenCalledWith(expect.objectContaining({ scope: null }));
    wrapper.unmount();
  });

  it('asks before a restricted group loses its scope, not for one already over the parc', async () => {
    const { wrapper, vm } = await mountPage();
    vm.openEdit(wholeParc);
    await flushPromises();
    await submit();
    expect(updateGroup).toHaveBeenCalledTimes(1);

    vm.openEdit(restricted);
    await flushPromises();
    vm.form.scope.locations = [];
    await submit();
    expect(updateGroup).toHaveBeenCalledTimes(1);
    expect(document.body.textContent).toContain('Enregistrer pour tout le parc');
    wrapper.unmount();
  });
});

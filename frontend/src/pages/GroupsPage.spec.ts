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
const authState = vi.hoisted(() => {
  const state: { user: Record<string, unknown> } = { user: { id: 'me' } };
  return state;
});
vi.mock('src/stores/auth', () => ({
  useAuthStore: () => ({
    fetchMe: () => Promise.resolve(),
    can: () => true,
    get user() {
      return authState.user;
    },
  }),
}));

import { createGroup, listGroups, updateGroup, type Group } from 'src/services/groups';
import { listLocations } from 'src/services/machines';
import { listBuildings, listRooms } from 'src/services/rooms';
import LoadErrorBanner from 'src/components/LoadErrorBanner.vue';
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
  form: { name: string; scope: { locations: string[] }; mfa_required: boolean };
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

  it('sends the second factor obligation (C7) on create and edit', async () => {
    const { wrapper, vm } = await mountPage();
    vm.openCreate();
    await flushPromises();
    expect(vm.form.mfa_required).toBe(false);
    vm.form.name = 'Techs MFA';
    vm.form.mfa_required = true;
    await typeLocation(wrapper, 'Lycée Nord');
    await submit();
    expect(createGroup).toHaveBeenCalledWith(expect.objectContaining({ mfa_required: true }));
    wrapper.unmount();
  });

  it('sends the directory groups (C7), one typed without Entrée included', async () => {
    const { wrapper, vm } = await mountPage();
    vm.openCreate();
    await flushPromises();
    vm.form.name = 'Techs annuaire';
    await typeLocation(wrapper, 'Lycée Nord');
    const idp = wrapper.findAllComponents(QSelect).at(-1)!;
    idp.vm.$emit('new-value', 'BAD ID;', () => undefined);
    await flushPromises();
    expect(idp.props('errorMessage')).toContain('Identifiant invalide');
    // An invalid id left typed stops the save instead of vanishing.
    idp.vm.$emit('input-value', 'bad id;');
    await submit();
    expect(createGroup).not.toHaveBeenCalled();
    idp.vm.$emit('input-value', ' 11111111-AAAA-4bbb-8ccc-000000000001 ');
    await submit();
    expect(createGroup).toHaveBeenCalledWith(
      expect.objectContaining({ idp_groups: ['11111111-aaaa-4bbb-8ccc-000000000001'] }),
    );
    wrapper.unmount();
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

describe('GroupsPage — item 2, item 4, C6', () => {
  beforeEach(() => {
    authState.user = { id: 'me' };
    vi.mocked(listLocations).mockResolvedValue([] as never);
    vi.mocked(listBuildings).mockResolvedValue([]);
    vi.mocked(listRooms).mockResolvedValue([]);
  });
  afterEach(() => {
    document.body.innerHTML = '';
  });

  // The confirmation is rendered as HTML: a name typed by another
  // administrator is quoted as text, never as markup.
  it('quotes the group’s name escaped in the delete confirmation', async () => {
    vi.mocked(listGroups).mockResolvedValue([]);
    const { wrapper } = await mountPage();
    const dialog = vi.spyOn(wrapper.vm.$q, 'dialog').mockReturnValue({
      onDismiss() {
        return this;
      },
      update() {
        return this;
      },
      onOk: () => undefined,
    } as never);
    (wrapper.vm as unknown as { confirmDelete: (g: Group) => void }).confirmDelete({
      ...restricted,
      name: '<img src=x> Lab',
    });
    const { message, html } = dialog.mock.calls[0]![0] as { message: string; html: boolean };
    expect(html).toBe(true);
    expect(message).toContain('<b>&lt;img src=x&gt; Lab</b>');
    expect(message).not.toContain('<img');
    dialog.mockRestore();
    wrapper.unmount();
  });

  it('keeps a banner with « Réessayer » when the groups cannot be read', async () => {
    vi.mocked(listGroups).mockRejectedValueOnce({ response: { status: 500, data: {} } });
    const { wrapper } = await mountPage();
    expect(wrapper.findComponent(LoadErrorBanner).exists()).toBe(true);
    expect(wrapper.text()).not.toContain('Aucun groupe');

    vi.mocked(listGroups).mockResolvedValueOnce([restricted]);
    wrapper.findComponent(LoadErrorBanner).vm.$emit('retry');
    await flushPromises();
    expect(wrapper.findComponent(LoadErrorBanner).exists()).toBe(false);
    wrapper.unmount();
  });

  it('names the scope by the server’s labels, a deleted place as « Lieu supprimé »', async () => {
    const labelled = {
      ...restricted,
      scope: { locations: [], buildings: ['b-1'], rooms: ['r-gone'] },
      scope_labels: [
        { kind: 'building', id: 'b-1', label: 'Bâtiment A', exists: true },
        { kind: 'room', id: 'r-gone', label: 'r-gone', exists: false },
      ],
    } as Group;
    vi.mocked(listGroups).mockResolvedValue([labelled]);
    const { wrapper, vm } = await mountPage();
    expect(wrapper.text()).toContain('Bâtiment A');
    expect(wrapper.text()).toContain('Lieu supprimé');
    expect(wrapper.text()).not.toContain('Salle supprimée');

    // In the form, the deleted room is a named, removable chip — not its id.
    vm.openEdit(labelled);
    await flushPromises();
    const rooms = wrapper.findAllComponents(QSelect).find((s) => s.props('label') === 'Salles')!;
    expect(rooms.props('options')).toContainEqual({ label: 'Lieu supprimé', value: 'r-gone' });
    wrapper.unmount();
  });

  it('ticks the read a write needs, and withholds what the caller cannot grant', async () => {
    const managers: Group = {
      ...wholeParc,
      id: 'managers',
      permissions: ['user:read', 'user:write', 'room:read', 'room:write'],
    };
    const admins: Group = { ...wholeParc, id: 'admins', is_admin: true };
    vi.mocked(listGroups).mockResolvedValue([managers, admins]);
    authState.user = {
      id: 'me',
      permissions: managers.permissions,
      groups: [{ id: 'managers', name: 'managers' }],
    };
    const { wrapper, vm } = await mountPage();
    const api = vm as unknown as {
      onPermissions: (next: string[]) => void;
      form: { permissions: string[] };
      beyondMe: (g: Group) => boolean;
      cannotGrant: (k: string) => boolean;
    };
    vm.openCreate();
    await flushPromises();
    api.onPermissions(['room:write']);
    expect(api.form.permissions).toEqual(['room:read', 'room:write']);

    expect(api.beyondMe(admins)).toBe(true);
    expect(api.beyondMe(managers)).toBe(false);
    expect(api.cannotGrant('audit:read')).toBe(true);
    expect(api.cannotGrant('room:write')).toBe(false);
    wrapper.unmount();
  });
});

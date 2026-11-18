import { flushPromises, mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import { QDialog, QInput, QSelect } from 'quasar';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { nextTick } from 'vue';

vi.mock('src/services/users', async (importOriginal) => ({
  ...(await importOriginal<typeof import('src/services/users')>()),
  listUsers: vi.fn(),
  resetUserPassword: vi.fn(),
}));
vi.mock('src/services/groups', async (importOriginal) => ({
  ...(await importOriginal<typeof import('src/services/groups')>()),
  listGroups: vi.fn(),
}));

import LoadErrorBanner from 'src/components/LoadErrorBanner.vue';
import { setLocale, t } from 'src/i18n';
import { listGroups, type Group } from 'src/services/groups';
import { listUsers, resetUserPassword, type ConsoleUser } from 'src/services/users';
import { useAuthStore } from 'src/stores/auth';
import UsersPage from './UsersPage.vue';

/** What the page keeps to itself, reached the way a click on the row's menu would. */
interface ResetApi {
  openReset: (user: ConsoleUser) => void;
  submitReset: () => Promise<void>;
  resetOpen: boolean;
  resetResult: string | null;
}

let release!: (password: string) => void;

function mountPage() {
  const pinia = createPinia();
  setActivePinia(pinia);
  useAuthStore().user = {
    id: 'me',
    email: 'admin@example.org',
    permissions: ['user:read', 'user:write'],
  } as never;
  const wrapper = mount(UsersPage, {
    attachTo: document.body,
    global: { plugins: [pinia], stubs: { QPage: { template: '<div><slot /></div>' } } },
  });
  return { wrapper, vm: wrapper.vm as unknown as ResetApi };
}

/** The reset dialog: the page's last one. */
function resetDialog(wrapper: ReturnType<typeof mountPage>['wrapper']) {
  return wrapper.findAllComponents(QDialog).at(-1)!;
}

describe('UsersPage — password reset (audit T29, U13)', () => {
  beforeEach(() => {
    vi.mocked(listUsers).mockResolvedValue({ items: [], total: 0, page: 1, page_size: 25 });
    vi.mocked(listGroups).mockResolvedValue([]);
    vi.mocked(resetUserPassword).mockImplementation(
      () => new Promise<string>((resolve) => (release = resolve)),
    );
  });

  it('cannot be dismissed while the reset is in flight', async () => {
    const { wrapper, vm } = mountPage();
    await flushPromises();
    vm.openReset({ id: 'x', email: 'tech@example.org' } as ConsoleUser);
    await flushPromises();
    expect(resetDialog(wrapper).props('persistent')).toBe(false);

    const done = vm.submitReset();
    await flushPromises();

    expect(resetDialog(wrapper).props('persistent')).toBe(true);
    release('S3cret-Generated-Pw');
    await done;
    await flushPromises();
    expect(resetDialog(wrapper).props('persistent')).toBe(true);
    wrapper.unmount();
  });

  it('shows a password that arrives after the dialog was closed', async () => {
    const { wrapper, vm } = mountPage();
    await flushPromises();
    vm.openReset({ id: 'x', email: 'tech@example.org' } as ConsoleUser);
    await flushPromises();
    const done = vm.submitReset();
    await flushPromises();
    // However it went away meanwhile...
    vm.resetOpen = false;
    await flushPromises();

    release('S3cret-Generated-Pw');
    await done;
    await flushPromises();

    // ...the password the server applied is on screen.
    expect(vm.resetOpen).toBe(true);
    expect(vm.resetResult).toBe('S3cret-Generated-Pw');
    const shown = resetDialog(wrapper)
      .findAllComponents(QInput)
      .find((i) => i.props('modelValue') === 'S3cret-Generated-Pw');
    expect(shown).toBeDefined();
    wrapper.unmount();
  });
});

function group(id: string, over: Partial<Group> = {}): Group {
  return {
    id,
    name: id,
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

function user(id: string, over: Partial<ConsoleUser> = {}): ConsoleUser {
  return {
    id,
    email: `${id}@example.org`,
    full_name: null,
    is_active: true,
    email_preference: 'digest_daily',
    groups: [],
    locked_until: null,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    ...over,
  };
}

describe('UsersPage — item 2, item 4, item 13', () => {
  beforeEach(() => {
    vi.mocked(listGroups).mockResolvedValue([]);
  });

  it('lifts the « Verrouillé » badge as soon as the password is reset', async () => {
    const locked = user('x', { locked_until: new Date(Date.now() + 3600_000).toISOString() });
    vi.mocked(listUsers).mockResolvedValue({ items: [locked], total: 1, page: 1, page_size: 25 });
    vi.mocked(resetUserPassword).mockResolvedValue('S3cret-Generated-Pw');
    const { wrapper, vm } = mountPage();
    await flushPromises();
    expect(wrapper.text()).toContain('Verrouillé');

    vm.openReset(locked);
    await vm.submitReset();
    await flushPromises();

    expect(listUsers).toHaveBeenCalledTimes(1);
    expect(wrapper.find('table').text()).not.toContain('Verrouillé');
    wrapper.unmount();
  });

  it('clears the rows of the previous search when a search fails, and says so', async () => {
    vi.mocked(listUsers).mockResolvedValueOnce({
      items: [user('a')],
      total: 1,
      page: 1,
      page_size: 25,
    });
    const { wrapper } = mountPage();
    await flushPromises();
    expect(wrapper.text()).toContain('a@example.org');

    vi.mocked(listUsers).mockRejectedValueOnce({ response: { status: 500, data: {} } });
    wrapper.findComponent(QInput).vm.$emit('update:modelValue', 'zz');
    await flushPromises();

    expect(wrapper.text()).not.toContain('a@example.org');
    expect(wrapper.findComponent(LoadErrorBanner).exists()).toBe(true);
    wrapper.unmount();
  });

  it('withholds the actions on an account holding more rights, and the groups beyond mine', async () => {
    const managers = group('managers', { permissions: ['user:read', 'user:write'] });
    const techs = group('techs', { permissions: ['command:execute'] });
    vi.mocked(listGroups).mockResolvedValue([managers, techs]);
    vi.mocked(listUsers).mockResolvedValue({
      items: [
        user('peer', { groups: [{ id: 'managers', name: 'managers' }] }),
        user('tech', { groups: [{ id: 'techs', name: 'techs' }] }),
      ],
      total: 2,
      page: 1,
      page_size: 25,
    });
    const pinia = createPinia();
    setActivePinia(pinia);
    useAuthStore().user = {
      id: 'me',
      email: 'manager@example.org',
      permissions: ['user:read', 'user:write'],
      groups: [{ id: 'managers', name: 'managers' }],
    } as never;
    const wrapper = mount(UsersPage, {
      global: { plugins: [pinia], stubs: { QPage: { template: '<div><slot /></div>' } } },
    });
    await flushPromises();
    const vm = wrapper.vm as unknown as {
      beyondMe: (u: ConsoleUser) => boolean;
      grantableGroupOptions: { value: string; disable: boolean }[];
    };

    expect(vm.beyondMe(user('peer', { groups: [{ id: 'managers', name: 'managers' }] }))).toBe(
      false,
    );
    expect(vm.beyondMe(user('tech', { groups: [{ id: 'techs', name: 'techs' }] }))).toBe(true);
    expect(vm.grantableGroupOptions).toEqual([
      expect.objectContaining({ value: 'managers', disable: false }),
      expect.objectContaining({ value: 'techs', disable: true }),
    ]);
    wrapper.unmount();
  });
});

describe('UsersPage — the account form and the delete confirmation', () => {
  beforeEach(() => {
    vi.mocked(listGroups).mockResolvedValue([]);
  });
  afterEach(() => {
    setLocale('fr');
    document.body.innerHTML = '';
  });

  // Columns and option lists follow a change of language (README « Langues »).
  it('words the e-mail cadences in the language shown, live', async () => {
    vi.mocked(listUsers).mockResolvedValue({
      items: [user('a')],
      total: 1,
      page: 1,
      page_size: 25,
    });
    const { wrapper } = mountPage();
    await flushPromises();
    (wrapper.vm as unknown as { openEdit: (u: ConsoleUser) => void }).openEdit(user('a'));
    await flushPromises();
    const cadences = () =>
      (
        wrapper
          .findAllComponents(QSelect)
          .find((s) => s.props('label') === t('users.form.emailPreference'))!
          .props('options') as { value: string; label: string }[]
      ).map((o) => o.label);
    expect(cadences()).toContain('Résumé quotidien, tous les jours');

    setLocale('en');
    await nextTick();
    expect(cadences()).toContain('Daily summary, every day');
    expect(cadences()).not.toContain('Résumé quotidien, tous les jours');
    wrapper.unmount();
  });

  // The confirmation is rendered as HTML: an address typed by another
  // administrator is quoted as text, never as markup.
  it('quotes the account’s address escaped in the delete confirmation', async () => {
    vi.mocked(listUsers).mockResolvedValue({ items: [], total: 0, page: 1, page_size: 25 });
    const { wrapper } = mountPage();
    await flushPromises();
    const dialog = vi.spyOn(wrapper.vm.$q, 'dialog').mockReturnValue({
      onDismiss() {
        return this;
      },
      update() {
        return this;
      },
      onOk: () => undefined,
    } as never);
    (wrapper.vm as unknown as { confirmDelete: (u: ConsoleUser) => void }).confirmDelete(
      user('x', { email: '<img src=x>@example.org' }),
    );
    const { message, html } = dialog.mock.calls[0]![0] as { message: string; html: boolean };
    expect(html).toBe(true);
    expect(message).toContain('<b>&lt;img src=x&gt;@example.org</b>');
    expect(message).not.toContain('<img');
    dialog.mockRestore();
    wrapper.unmount();
  });
});

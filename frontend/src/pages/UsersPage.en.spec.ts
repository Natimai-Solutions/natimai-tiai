import { flushPromises, mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { nextTick } from 'vue';

vi.mock('src/services/users', async (importOriginal) => ({
  ...(await importOriginal<typeof import('src/services/users')>()),
  listUsers: vi.fn(),
}));
vi.mock('src/services/groups', async (importOriginal) => ({
  ...(await importOriginal<typeof import('src/services/groups')>()),
  listGroups: vi.fn(),
}));
// The e-mail cadences are worded by `utils/format` (another batch of the
// translation): stood in for here, so that this page's own words are tested.
vi.mock('src/utils/format', async (importOriginal) => {
  const actual = await importOriginal<typeof import('src/utils/format')>();
  return { ...actual, emailPreferenceLabel: (value: string) => `pref:${value}` };
});

import { setLocale } from 'src/i18n';
import { listGroups, type Group } from 'src/services/groups';
import { listUsers, type ConsoleUser } from 'src/services/users';
import { useAuthStore } from 'src/stores/auth';
import UsersPage from './UsersPage.vue';

const admins: Group = {
  id: 'g-admin',
  name: 'Admins',
  description: null,
  builtin_key: 'admin',
  is_admin: true,
  permissions: [],
  scope: null,
  member_count: 1,
  created_at: '',
  updated_at: '',
};

const users: ConsoleUser[] = [
  {
    id: 'u-1',
    email: 'tech@example.org',
    full_name: 'Tech One',
    is_active: true,
    email_preference: 'digest_daily',
    groups: [],
    locked_until: '2099-01-01T00:00:00Z',
    created_at: '2026-01-02T03:04:05Z',
    updated_at: '2026-01-02T03:04:05Z',
  },
  {
    id: 'u-2',
    email: 'boss@example.org',
    full_name: null,
    is_active: false,
    email_preference: 'none',
    groups: [{ id: 'g-admin', name: 'Admins' }] as never,
    locked_until: null,
    created_at: '2026-01-02T03:04:05Z',
    updated_at: '2026-01-02T03:04:05Z',
  },
];

interface PageApi {
  openCreate: () => void;
  openReset: (user: ConsoleUser) => void;
}

function mountPage() {
  const pinia = createPinia();
  setActivePinia(pinia);
  useAuthStore().user = {
    id: 'me',
    email: 'admin@example.org',
    permissions: ['user:read', 'user:write'],
    groups: [],
  } as never;
  const wrapper = mount(UsersPage, {
    attachTo: document.body,
    global: { plugins: [pinia], stubs: { QPage: { template: '<div><slot /></div>' } } },
  });
  return { wrapper, vm: wrapper.vm as unknown as PageApi };
}

afterEach(() => {
  setLocale('fr');
  document.body.innerHTML = '';
});

describe('UsersPage in English', () => {
  beforeEach(() => {
    vi.mocked(listUsers).mockResolvedValue({ items: users, total: 2, page: 1, page_size: 25 });
    vi.mocked(listGroups).mockResolvedValue([admins]);
  });

  it('reads in English, with no French left', async () => {
    setLocale('en');
    const { wrapper } = mountPage();
    await flushPromises();
    const text = wrapper.text();
    expect(text).toContain('Users');
    expect(text).toContain('New account');
    for (const header of ['E-mail', 'Name', 'Groups', 'Status', 'E-mails', 'Created on']) {
      expect(wrapper.find('thead').text()).toContain(header);
    }
    expect(text).toContain('Active');
    expect(text).toContain('Disabled');
    expect(text).toContain('Locked');
    expect(text).toContain('None');
    expect(text).toContain('pref:digest_daily');
    expect(wrapper.find('input[aria-label="Search for an account"]').exists()).toBe(true);
    expect(wrapper.find('button[aria-label="Actions for tech@example.org"]').exists()).toBe(true);
    expect(text).not.toMatch(/[éèàùç«»]/);
    wrapper.unmount();
  });

  it('words the account form and the password reset', async () => {
    setLocale('en');
    const { wrapper, vm } = mountPage();
    await flushPromises();
    vm.openCreate();
    await flushPromises();
    let text = document.body.textContent ?? '';
    expect(text).toContain('New account');
    expect(text).toContain('Full name');
    expect(text).toContain('Password');
    expect(text).toContain('At least 12 characters');
    expect(text).toContain('Greyed out: the groups that grant more permissions than you hold');
    expect(text).toContain('Save');
    expect(text).toContain('Cancel');

    vm.openReset(users[0]!);
    await flushPromises();
    text = document.body.textContent ?? '';
    expect(text).toContain('Reset the password');
    expect(text).toContain('Generate a password');
    expect(text).toContain('Type a password');
    expect(text).toContain('The open sessions of this account will be closed.');
    expect(text).not.toMatch(/[éèàùç«»]/);
    wrapper.unmount();
  });

  it('switches language while open', async () => {
    const { wrapper } = mountPage();
    await flushPromises();
    expect(wrapper.text()).toContain('Utilisateurs');
    expect(wrapper.find('thead').text()).toContain('Créé le');
    expect(wrapper.text()).toContain('Désactivé');

    setLocale('en');
    await nextTick();
    expect(wrapper.text()).toContain('Users');
    expect(wrapper.find('thead').text()).toContain('Created on');
    expect(wrapper.text()).toContain('Disabled');
    expect(wrapper.text()).not.toContain('Désactivé');
    wrapper.unmount();
  });
});

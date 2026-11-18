import { flushPromises, mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { nextTick } from 'vue';
import { createMemoryHistory, createRouter } from 'vue-router';

vi.mock('src/services/auth', async (importOriginal) => ({
  ...(await importOriginal<typeof import('src/services/auth')>()),
  listSessions: vi.fn(),
}));
// The e-mail cadences and the « 2 min ago » are worded by `utils/format`
// (another batch of the translation): stood in for here, so that this page's
// own words are tested.
vi.mock('src/utils/format', async (importOriginal) => {
  const actual = await importOriginal<typeof import('src/utils/format')>();
  return {
    ...actual,
    EMAIL_PREFERENCE_OPTIONS: actual.EMAIL_PREFERENCE_OPTIONS.map((o) => ({
      ...o,
      hint: `hint:${o.value}`,
    })),
    emailPreferenceLabel: (value: string) => `pref:${value}`,
    timeAgoLabel: () => '2 min ago',
  };
});

import { setLocale } from 'src/i18n';
import { listSessions, type AuthSession } from 'src/services/auth';
import { useAuthStore } from 'src/stores/auth';
import AccountPage from './AccountPage.vue';

const FIREFOX_WINDOWS =
  'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:140.0) Gecko/20100101 Firefox/140.0';

const sessions = [
  {
    id: 's-1',
    current: true,
    user_agent: FIREFOX_WINDOWS,
    ip: '10.0.0.1',
    created_at: '2026-11-01T08:00:00Z',
    last_used_at: '2026-11-18T08:00:00Z',
  },
  {
    id: 's-2',
    current: false,
    user_agent: null,
    ip: null,
    created_at: '2026-11-01T08:00:00Z',
    last_used_at: '2026-11-18T08:00:00Z',
  },
] as unknown as AuthSession[];

async function mountPage(groups: unknown[] = []) {
  const pinia = createPinia();
  setActivePinia(pinia);
  useAuthStore().user = {
    id: 'me',
    email: 'a@b.c',
    full_name: 'Ann Smith',
    permissions: [],
    groups,
    email_preference: 'none',
    language: null,
    preferences: {},
  } as never;
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/', component: { render: () => null } }],
  });
  const w = mount(AccountPage, {
    global: { plugins: [pinia, router], stubs: { QPage: { template: '<div><slot /></div>' } } },
  });
  await flushPromises();
  return w;
}

afterEach(() => setLocale('fr'));

describe('AccountPage in English', () => {
  it('reads in English, with no French left', async () => {
    vi.mocked(listSessions).mockResolvedValue(sessions);
    setLocale('en');
    const w = await mountPage();
    const text = w.text();
    expect(text).toContain('My account');
    expect(text).toContain('None — this account cannot view anything');
    expect(text).toContain('E-mail notifications');
    expect(text).toContain('pref:none');
    expect(text).toContain('Change my password');
    expect(text).toContain('At least 12 characters');
    expect(text).toContain('All your sessions will be closed: you will have to log in again.');
    expect(text).toContain('Open sessions');
    expect(text).toContain('Firefox on Windows');
    expect(text).toContain('This session');
    expect(text).toContain('10.0.0.1 · last active 2 min ago');
    expect(text).toContain('Unknown device');
    expect(text).toContain('Unknown address · last active 2 min ago');
    expect(text).toContain('Opened on');
    expect(text).toContain('Log out');
    expect(text).toContain('Close');
    // Each language is named in itself in the picker: « Français » is meant.
    expect(text.replace('Français', '')).not.toMatch(/[éèàùç«»]/);
  });

  it('says there is no open session, in English', async () => {
    vi.mocked(listSessions).mockResolvedValue([]);
    setLocale('en');
    const w = await mountPage();
    expect(w.text()).toContain('No open session.');
  });

  it('names a built-in group in English, one renamed as typed', async () => {
    vi.mocked(listSessions).mockResolvedValue([]);
    setLocale('en');
    // The names the installation gave: what /auth/me sends, with the keys.
    const w = await mountPage([
      { id: 'g-ro', name: 'Lecture seule', builtin_key: 'readonly' },
      { id: 'g-tech', name: 'Équipe info', builtin_key: 'technician' },
    ]);
    const chips = w.findAll('.q-chip').map((c) => c.text());
    expect(chips).toEqual(['Read only', 'Équipe info']);
  });

  it('switches language while open — the reader may have just chosen it here', async () => {
    vi.mocked(listSessions).mockResolvedValue(sessions);
    const w = await mountPage();
    expect(w.text()).toContain('Mon compte');
    expect(w.text()).toContain('Firefox sur Windows');
    expect(w.text()).toContain('Cette session');

    setLocale('en');
    await nextTick();
    expect(w.text()).toContain('My account');
    expect(w.text()).toContain('Firefox on Windows');
    expect(w.text()).toContain('This session');
    expect(w.text()).not.toContain('Mon compte');
  });
});

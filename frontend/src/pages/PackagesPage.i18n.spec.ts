import { flushPromises, mount, RouterLinkStub } from '@vue/test-utils';
import { nextTick } from 'vue';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { setLocale } from 'src/i18n';
import type { Package } from 'src/services/packages';

const listPackages = vi.fn();

vi.mock('src/services/packages', async (orig) => ({
  ...(await orig<object>()),
  listPackages: (...a: unknown[]) => listPackages(...a),
  createPackage: vi.fn(),
}));
vi.mock('vue-router', async (orig) => ({
  ...(await orig<object>()),
  useRouter: () => ({ push: vi.fn() }),
}));
vi.mock('src/stores/auth', () => ({
  useAuthStore: () => ({ can: () => true, user: { id: 'u' }, permissions: [] }),
}));

import PackagesPage from './PackagesPage.vue';

function pkg(over: Partial<Package> = {}): Package {
  return {
    id: 'p-1',
    kind: 'files',
    name: 'Tool',
    version: '1.0',
    notes: null,
    winget_id: null,
    winget_version: null,
    install_run: 'setup.exe',
    install_args: [],
    uninstall_run: null,
    uninstall_args: [],
    success_codes: [0],
    detect_name: null,
    files: [{ name: 'setup.exe', sha256: 'a'.repeat(64), size: 1, publisher_name: 'TDF' }],
    signed: false,
    signer_subject: null,
    signer_thumbprint: null,
    signed_at: null,
    signed_by: null,
    publisher_name: 'TDF',
    method_a_too_large: false,
    method_a_max_bytes: 8 * 1024 ** 3,
    file_max_bytes: 2 * 1024 ** 3,
    problems: [],
    install_blockers: [],
    installed_count: 4,
    created_by: null,
    created_at: '2026-11-04T00:00:00Z',
    updated_at: '2026-11-04T00:00:00Z',
    retired_at: null,
    ...over,
  };
}

const ROWS = [
  pkg({ id: 'ready', name: 'Ready tool' }),
  pkg({
    id: 'blocked',
    name: 'Blocked tool',
    publisher_name: null,
    files: [{ name: 'setup.exe', sha256: 'b'.repeat(64), size: 1, publisher_name: null }],
    install_blockers: ['Paquet non signé, et « setup.exe » ne porte pas de signature…'],
    install_blocker_problems: [
      {
        code: 'untrusted',
        params: { reason: 'no_publisher', file: 'setup.exe' },
        message: 'Paquet non signé, et « setup.exe » ne porte pas de signature…',
        blocks_uninstall: false,
      },
    ],
  }),
  pkg({
    id: 'winget',
    kind: 'winget',
    name: 'Firefox',
    version: null,
    winget_id: 'Mozilla.Firefox',
    install_run: null,
    files: [],
  }),
  pkg({ id: 'empty', name: 'Empty', install_run: null, files: [], retired_at: '2026-11-05' }),
];

async function mountPage() {
  const w = mount(PackagesPage, {
    attachTo: document.body,
    global: { stubs: { QPage: { template: '<div><slot /></div>' }, RouterLink: RouterLinkStub } },
  });
  await flushPromises();
  return w;
}

describe('PackagesPage in English', () => {
  beforeEach(() => {
    listPackages.mockReset().mockResolvedValue(ROWS);
    document.body.innerHTML = '';
  });
  afterEach(() => setLocale('fr'));

  it('reads in English, the server’s diagnostics worded from their codes', async () => {
    setLocale('en');
    const w = await mountPage();
    const text = w.text();
    expect(text).toContain('Packages');
    expect(text).toContain('What the console can install.');
    expect(w.find('b').text()).toBe('winget');
    for (const column of ['Package', 'Trust', 'State', 'Computers with it'])
      expect(text).toContain(column);
    const rows = w.findAll('tbody tr').map((r) => r.text());
    expect(rows.find((r) => r.includes('Ready tool'))).toContain('Publisher (method A)');
    expect(rows.find((r) => r.includes('Ready tool'))).toContain('Ready');
    expect(rows.find((r) => r.includes('Blocked tool'))).toContain(
      'Unsigned package, and “setup.exe” bears no publisher signature',
    );
    expect(rows.find((r) => r.includes('Firefox'))).toContain('Mozilla.Firefox');
    expect(rows.find((r) => r.includes('Empty'))).toContain('No files');
    expect(rows.find((r) => r.includes('Empty'))).toContain('Retired');
    expect(text).not.toMatch(/[éèàùç«»]/);
    w.unmount();
  });

  it('follows a change of language while open', async () => {
    const w = await mountPage();
    expect(w.text()).toContain('Postes équipés');
    expect(w.text()).toContain('Éditeur (méthode A)');
    setLocale('en');
    await nextTick();
    expect(w.text()).toContain('Computers with it');
    expect(w.text()).toContain('Publisher (method A)');
    expect(w.text()).not.toContain('Postes équipés');
    w.unmount();
  });

  it('offers the new package form in English', async () => {
    setLocale('en');
    const w = await mountPage();
    (w.vm as unknown as { openCreate: () => void }).openCreate();
    await flushPromises();
    const dialog = document.querySelector('.q-dialog')!.textContent ?? '';
    expect(dialog).toContain('New package');
    expect(dialog).toContain('Files (.exe, .msi…)');
    expect(dialog).toContain('winget identifier');
    expect(dialog).toContain('Create');
    expect(dialog).not.toMatch(/[éèàùç«»]/);
    w.unmount();
  });
});

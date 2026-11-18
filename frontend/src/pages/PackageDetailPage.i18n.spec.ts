import { flushPromises, mount } from '@vue/test-utils';
import { nextTick } from 'vue';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { setLocale } from 'src/i18n';
import type { CommandList } from 'src/services/commands';
import type { Package } from 'src/services/packages';

const getPackage = vi.fn();
const getPackageSummary = vi.fn();
const retirePackage = vi.fn();

vi.mock('src/services/packages', async (orig) => ({
  ...(await orig<object>()),
  getPackage: (...a: unknown[]) => getPackage(...a),
  listPackageCommands: () =>
    Promise.resolve({ items: [], total: 0, page: 1, page_size: 25 } as unknown as CommandList),
  getPackageSummary: (...a: unknown[]) => getPackageSummary(...a),
  retirePackage: (...a: unknown[]) => retirePackage(...a),
}));
vi.mock('vue-router', async (orig) => ({
  ...(await orig<object>()),
  onBeforeRouteLeave: () => undefined,
}));
vi.mock('src/stores/auth', () => ({
  useAuthStore: () => ({ can: () => true, user: { id: 'u' }, permissions: [] }),
}));

import PackageDetailPage from './PackageDetailPage.vue';

const GIB = 1024 ** 3;

/** An editor's installer with a .dll beside it: method A refuses it. */
const pkg: Package = {
  id: 'p-1',
  kind: 'files',
  name: 'Pronote',
  version: '2026',
  notes: null,
  winget_id: null,
  winget_version: null,
  install_run: 'Install.exe',
  install_args: [],
  uninstall_run: null,
  uninstall_args: [],
  success_codes: [0],
  detect_name: 'Pronote',
  files: [
    { name: 'Install.exe', sha256: 'a'.repeat(64), size: 1536, publisher_name: 'INDEX' },
    { name: 'helper.dll', sha256: 'b'.repeat(64), size: 250 * 1024 * 1024, publisher_name: null },
  ],
  signed: false,
  signer_subject: null,
  signer_thumbprint: null,
  signed_at: null,
  signed_by: null,
  publisher_name: 'INDEX',
  method_a_too_large: false,
  method_a_max_bytes: 8 * GIB,
  file_max_bytes: 2 * GIB,
  problems: [],
  install_blockers: ['Paquet non signé, et « helper.dll » est à côté de « Install.exe »…'],
  install_blocker_problems: [
    {
      code: 'untrusted',
      params: { reason: 'loadable', file: 'Install.exe', files: ['helper.dll'] },
      message: 'Paquet non signé, et « helper.dll » est à côté de « Install.exe »…',
      blocks_uninstall: false,
    },
  ],
  installed_count: 1,
  created_by: null,
  created_at: '2026-11-04T00:00:00Z',
  updated_at: '2026-11-04T00:00:00Z',
  retired_at: null,
};

type VM = {
  toggleRetired: () => Promise<void>;
  toggleStatusFilter: (s: string) => void;
  $q: { dialog: (o: unknown) => unknown; notify: (o: unknown) => unknown };
};

async function mountPage() {
  const w = mount(PackageDetailPage, {
    props: { id: 'p-1' },
    attachTo: document.body,
    global: {
      stubs: {
        QPage: { template: '<div><slot /></div>' },
        RouterLink: { template: '<a><slot /></a>' },
        PackageDeployDialog: true,
      },
    },
  });
  await flushPromises();
  return w;
}

describe('PackageDetailPage in English', () => {
  beforeEach(() => {
    getPackage.mockReset().mockResolvedValue(pkg);
    getPackageSummary
      .mockReset()
      .mockResolvedValue({ postes: 4, by_status: { succeeded: 3, failed: 1 }, by_action: {} });
    retirePackage.mockReset().mockResolvedValue({ ...pkg, retired_at: '2026-11-18' });
    document.body.innerHTML = '';
  });
  afterEach(() => setLocale('fr'));

  it('reads in English: definition, files, trust and deployments', async () => {
    setLocale('en');
    const w = await mountPage();
    const text = w.text();
    for (const words of [
      'Unsigned',
      'Deploy',
      'Retire',
      'Definition',
      'File to run to install',
      'Accepted exit codes',
      'Name in the inventory',
      'No computer will install it',
      'Unsigned package, and “helper.dll” is next to “Install.exe”',
      'Files',
      'Choose files',
      '1.5 KiB',
      '250 MiB',
      'signed by INDEX',
      'Computers’ trust',
      'Method B — the administrator’s signature',
      'Unsigned. Download the manifest, sign it on your own computer with Sign-TiaiPackage.ps1',
      'Method A — approved publisher (fallback)',
      'Unavailable: the file that runs is signed by INDEX, but “helper.dll” is next to it',
      'Remove this file from the package',
      'Present, according to the inventory, on 1 computer.',
      'Deployments',
      '4 computers targeted — the latest deployment of each',
      'Succeeded: 3',
      'Failed: 1',
      'History: every send, newest first',
      'Never deployed',
    ])
      expect(text).toContain(words);
    // The marked values keep their mark.
    expect(w.findAll('code').map((c) => c.text())).toContain('Sign-TiaiPackage.ps1');
    expect(w.findAll('b').map((b) => b.text())).toContain('INDEX');
    expect(text).not.toMatch(/[éèàùç«»]/);
    w.unmount();
  });

  it('follows a change of language while open', async () => {
    const w = await mountPage();
    expect(w.text()).toContain('Confiance des postes');
    expect(w.text()).toContain('4 postes visés');
    setLocale('en');
    await nextTick();
    expect(w.text()).toContain('Computers’ trust');
    expect(w.text()).toContain('4 computers targeted');
    expect(w.text()).not.toContain('Confiance des postes');
    w.unmount();
  });

  it('says the signature and winget sentences in English', async () => {
    setLocale('en');
    getPackage.mockResolvedValue({
      ...pkg,
      signed: true,
      signer_subject: 'CN=IT',
      signer_thumbprint: 'ABCDEF',
      signed_at: '2026-11-04T10:00:00Z',
      signed_by: 'admin',
      install_blockers: [],
      install_blocker_problems: [],
    });
    let w = await mountPage();
    expect(w.text()).toContain('Signed by CN=IT on');
    expect(w.text()).toContain('this certificate’s thumbprint in DeploySigners:');
    expect(w.text()).toContain('Not needed: the package is signed.');
    w.unmount();

    getPackage.mockResolvedValue({
      ...pkg,
      kind: 'winget',
      winget_id: 'Mozilla.Firefox',
      install_run: null,
      files: [],
      install_blockers: [],
      install_blocker_problems: [],
    });
    w = await mountPage();
    expect(w.text()).toContain(
      'Computers install it if their GPO turns winget on (DeployWinget = 1) and, when it is set, if Mozilla.Firefox is listed in DeployWingetAllow.',
    );
    expect(w.findAll('code').map((c) => c.text())).toEqual([
      'DeployWinget',
      'Mozilla.Firefox',
      'DeployWingetAllow',
    ]);
    w.unmount();
  });

  it('filters by a state named in English', async () => {
    setLocale('en');
    const w = await mountPage();
    (w.vm as unknown as VM).toggleStatusFilter('failed');
    await flushPromises();
    expect(w.text()).toContain('Latest deployment of each computer, failed');
    expect(w.text()).toContain('No deployment in this state');
    w.unmount();
  });

  it('asks before retiring, in English', async () => {
    setLocale('en');
    getPackageSummary.mockResolvedValue({
      postes: 4,
      by_status: {},
      by_action: {},
      pending_installs: 1,
    });
    const w = await mountPage();
    const vm = w.vm as unknown as VM;
    const seen: { title?: string; message?: string }[] = [];
    vi.spyOn(vm.$q, 'dialog').mockImplementation((opts: unknown) => {
      seen.push(opts as { title?: string; message?: string });
      const chain = {
        onOk(fn: () => void) {
          queueMicrotask(fn);
          return chain;
        },
        onCancel() {
          return chain;
        },
      };
      return chain;
    });
    const notify = vi.spyOn(vm.$q, 'notify');
    await vm.toggleRetired();
    await flushPromises();
    expect(seen[0]!.title).toBe('Retire the package');
    expect(seen[0]!.message).toContain(
      '1 pending installation (not yet received by its computer) will be cancelled.',
    );
    expect(notify).toHaveBeenCalledWith(
      expect.objectContaining({
        message: 'Package retired',
        caption: '1 pending installation cancelled.',
      }),
    );
    w.unmount();
  });
});

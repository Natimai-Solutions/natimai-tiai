import { flushPromises, mount } from '@vue/test-utils';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { CommandList } from 'src/services/commands';

const getPackage = vi.fn();
const listPackageCommands = vi.fn();
const getPackageSummary = vi.fn();

vi.mock('src/services/packages', async (orig) => ({
  ...(await orig<object>()),
  getPackage: (...a: unknown[]) => getPackage(...a),
  listPackageCommands: (...a: unknown[]) => listPackageCommands(...a),
  getPackageSummary: (...a: unknown[]) => getPackageSummary(...a),
  listPackages: () => Promise.resolve([]),
}));
vi.mock('src/services/machines', async (orig) => ({
  ...(await orig<object>()),
  listLocations: () => Promise.resolve([]),
}));
vi.mock('vue-router', async (orig) => ({
  ...(await orig<object>()),
  onBeforeRouteLeave: () => undefined,
}));
vi.mock('src/stores/auth', () => ({
  useAuthStore: () => ({ can: () => true, user: { id: 'u' }, permissions: [] }),
}));

import PackageDetailPage from './PackageDetailPage.vue';

const pkg = {
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
  detect_name: null,
  files: [{ name: 'Install.exe', sha256: 'a'.repeat(64), size: 1, publisher_name: 'INDEX' }],
  signed: false,
  signer_subject: null,
  signer_thumbprint: null,
  signed_at: null,
  signed_by: null,
  publisher_name: 'INDEX',
  problems: [],
  installed_count: null,
  created_by: null,
  created_at: '2026-11-04T00:00:00Z',
  updated_at: '2026-11-04T00:00:00Z',
  retired_at: null,
};

function page(items: { id: string; status: string }[], total: number): CommandList {
  return { items, total, page: 1, page_size: 25 } as unknown as CommandList;
}

type VM = {
  commands: { id: string }[];
  commandPagination: { rowsNumber: number };
  toggleStatusFilter: (s: string) => void;
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

describe('PackageDetailPage', () => {
  beforeEach(() => {
    getPackage.mockReset().mockResolvedValue(pkg);
    listPackageCommands.mockReset().mockResolvedValue(page([], 0));
    getPackageSummary.mockReset().mockResolvedValue({ postes: 0, by_status: {}, by_action: {} });
    document.body.innerHTML = '';
  });

  it('shows the answer to the last filter, not the last answer (audit T25)', async () => {
    const w = await mountPage();
    const vm = w.vm as unknown as VM;

    let failedAnswer!: (v: CommandList) => void;
    listPackageCommands
      .mockReset()
      .mockImplementationOnce(() => new Promise((resolve) => (failedAnswer = resolve)))
      .mockImplementationOnce(() => Promise.resolve(page([{ id: 'all-1', status: 'ok' }], 40)));

    // « Échec », then straight back to everything: the first answer lands last.
    vm.toggleStatusFilter('failed');
    vm.toggleStatusFilter('failed');
    await flushPromises();
    failedAnswer(page([{ id: 'failed-1', status: 'failed' }], 1));
    await flushPromises();

    expect(listPackageCommands).toHaveBeenLastCalledWith('p-1', 1, 25, null);
    expect(vm.commands.map((c) => c.id)).toEqual(['all-1']);
    expect(vm.commandPagination.rowsNumber).toBe(40);
    w.unmount();
  });
});

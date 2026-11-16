import { flushPromises, mount } from '@vue/test-utils';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { CommandList } from 'src/services/commands';

const getPackage = vi.fn();
const listPackageCommands = vi.fn();
const getPackageSummary = vi.fn();
const uploadPackageFiles = vi.fn();

vi.mock('src/services/packages', async (orig) => ({
  ...(await orig<object>()),
  getPackage: (...a: unknown[]) => getPackage(...a),
  listPackageCommands: (...a: unknown[]) => listPackageCommands(...a),
  getPackageSummary: (...a: unknown[]) => getPackageSummary(...a),
  uploadPackageFiles: (...a: unknown[]) => uploadPackageFiles(...a),
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
  method_a_too_large: false,
  method_a_max_bytes: 8 * 1024 ** 3,
  file_max_bytes: 2 * 1024 ** 3,
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
  toUpload: File[] | null;
  upload: () => Promise<void>;
  $q: { notify: (o: unknown) => unknown };
};

const GIB = 1024 ** 3;

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
    uploadPackageFiles.mockReset().mockImplementation(() => Promise.resolve(getPackage()));
    document.body.innerHTML = '';
  });

  it('sends a file the server accepts, whatever the default bound is', async () => {
    // PACKAGE_MAX_BYTES raised to 4 Gio on this server: a 3 Gio installer
    // used to be refused here, against a figure compiled into the console.
    getPackage.mockResolvedValue({ ...pkg, file_max_bytes: 4 * GIB });
    const w = await mountPage();
    const vm = w.vm as unknown as VM;
    const installer = { name: 'gros.exe', size: 3 * GIB } as File;
    vm.toUpload = [installer];
    await vm.upload();
    await flushPromises();
    expect(uploadPackageFiles).toHaveBeenCalledTimes(1);
    expect(uploadPackageFiles.mock.calls[0]?.slice(0, 2)).toEqual(['p-1', [installer]]);
    w.unmount();
  });

  it('refuses before sending what the server would refuse, naming its bound', async () => {
    const w = await mountPage();
    const vm = w.vm as unknown as VM;
    const notify = vi.spyOn(vm.$q, 'notify');
    vm.toUpload = [{ name: 'gros.exe', size: 3 * GIB } as File];
    await vm.upload();
    await flushPromises();
    expect(uploadPackageFiles).not.toHaveBeenCalled();
    expect(notify).toHaveBeenCalledWith(
      expect.objectContaining({
        type: 'negative',
        message: 'Trop volumineux : gros.exe',
        caption: 'Limite de ce serveur : 2.0 Gio par fichier.',
      }),
    );
    w.unmount();
  });

  it('does not offer an uninstall the server would refuse', async () => {
    const byCode = {
      ...pkg,
      uninstall_run: 'msiexec',
      uninstall_args: ['/x', '{6C2A1A7B-0D5E-4F1C-9E4B-3B1C2D3E4F50}'],
    };
    const button = (w: Awaited<ReturnType<typeof mountPage>>) =>
      w.findAll('button').find((b) => b.text().includes('Désinstaller'))!;

    // Nothing in the way.
    getPackage.mockResolvedValue(byCode);
    let w = await mountPage();
    expect(button(w).attributes('disabled')).toBeUndefined();
    w.unmount();

    // No install step: the agent uninstalls all the same, so does the console.
    getPackage.mockResolvedValue({
      ...byCode,
      install_run: null,
      problems: [
        { code: 'no_install', message: 'Fichier à lancer non choisi', blocks_uninstall: false },
      ],
    });
    w = await mountPage();
    expect(button(w).attributes('disabled')).toBeUndefined();
    w.unmount();

    // A file the store lost, on a signed package: every step downloads it.
    getPackage.mockResolvedValue({
      ...byCode,
      signed: true,
      problems: [
        {
          code: 'file_missing_in_store',
          message:
            'Fichier absent du stockage du serveur : « Install.exe » — déposez-le de nouveau',
          blocks_uninstall: true,
        },
      ],
    });
    w = await mountPage();
    expect(button(w).attributes('disabled')).toBeDefined();
    expect(w.text()).toContain('Fichier absent du stockage du serveur : « Install.exe »');
    w.unmount();
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

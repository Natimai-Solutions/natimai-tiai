import { flushPromises, mount } from '@vue/test-utils';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { CommandList } from 'src/services/commands';

const getPackage = vi.fn();
const listPackageCommands = vi.fn();
const getPackageSummary = vi.fn();
const uploadPackageFiles = vi.fn();
const updatePackage = vi.fn();
const retirePackage = vi.fn();
const restorePackage = vi.fn();
// The page's « leave? » guard, as the router would call it.
const routeLeave = vi.hoisted(() => ({ guard: null as null | (() => unknown) }));

vi.mock('src/services/packages', async (orig) => ({
  ...(await orig<object>()),
  getPackage: (...a: unknown[]) => getPackage(...a),
  listPackageCommands: (...a: unknown[]) => listPackageCommands(...a),
  getPackageSummary: (...a: unknown[]) => getPackageSummary(...a),
  uploadPackageFiles: (...a: unknown[]) => uploadPackageFiles(...a),
  updatePackage: (...a: unknown[]) => updatePackage(...a),
  retirePackage: (...a: unknown[]) => retirePackage(...a),
  restorePackage: (...a: unknown[]) => restorePackage(...a),
  listPackages: () => Promise.resolve([]),
}));
vi.mock('src/services/machines', async (orig) => ({
  ...(await orig<object>()),
  listLocations: () => Promise.resolve([]),
}));
vi.mock('vue-router', async (orig) => ({
  ...(await orig<object>()),
  onBeforeRouteLeave: (guard: () => unknown) => {
    routeLeave.guard = guard;
  },
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
  install_blockers: [] as string[],
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
  toggleRetired: () => Promise<void>;
  openDeploy: (a: 'install' | 'uninstall') => Promise<void>;
  deployOpen: boolean;
  uploading: boolean;
  form: { name: string; install_args: string };
  $q: { notify: (o: unknown) => unknown; dialog: (o: unknown) => unknown };
};

interface DialogOptions {
  title?: string;
  message?: string;
  ok?: { label?: string };
}

/** Every dialog the page opens is answered `answer`; returns what they said. */
function answerDialogs(vm: VM, answer: 'ok' | 'cancel'): DialogOptions[] {
  const seen: DialogOptions[] = [];
  vi.spyOn(vm.$q, 'dialog').mockImplementation((opts: unknown) => {
    seen.push(opts as DialogOptions);
    const chain = {
      onOk(fn: () => void) {
        if (answer === 'ok') queueMicrotask(fn);
        return chain;
      },
      onCancel(fn: () => void) {
        if (answer === 'cancel') queueMicrotask(fn);
        return chain;
      },
    };
    return chain;
  });
  return seen;
}

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
    updatePackage.mockReset();
    retirePackage.mockReset();
    restorePackage.mockReset();
    routeLeave.guard = null;
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
        caption: 'Limite de ce serveur : 2,0 Gio par fichier.',
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
      // The server's list of what stops an installation carries it too.
      install_blockers: [
        'Fichier absent du stockage du serveur : « Install.exe » — déposez-le de nouveau',
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

    expect(listPackageCommands).toHaveBeenLastCalledWith('p-1', 1, 25, null, false);
    expect(vm.commands.map((c) => c.id)).toEqual(['all-1']);
    expect(vm.commandPagination.rowsNumber).toBe(40);
    w.unmount();
  });

  it('asks before retiring, with the number of installs it cancels, and says it after', async () => {
    getPackageSummary.mockResolvedValue({
      postes: 9,
      by_status: { pending: 9 },
      by_action: { package_install: 9 },
      pending_installs: 17,
    });
    retirePackage.mockResolvedValue({ ...pkg, retired_at: '2026-11-16T00:00:00Z' });
    const w = await mountPage();
    const vm = w.vm as unknown as VM;
    const notify = vi.spyOn(vm.$q, 'notify');
    const dialogs = answerDialogs(vm, 'ok');
    getPackageSummary.mockClear();
    listPackageCommands.mockClear();

    await vm.toggleRetired();
    await flushPromises();

    expect(dialogs).toHaveLength(1);
    expect(dialogs[0]!.message).toContain('17 installations en attente');
    expect(dialogs[0]!.message).toContain('seront annulées');
    expect(dialogs[0]!.message).toContain('ne relancera pas les installations annulées');
    expect(retirePackage).toHaveBeenCalledWith('p-1');
    expect(notify).toHaveBeenCalledWith(
      expect.objectContaining({
        message: 'Paquet retiré',
        caption: '17 installations en attente annulées.',
      }),
    );
    // The deployments card follows: the summary is read again after.
    expect(listPackageCommands).toHaveBeenCalled();
    expect(getPackageSummary.mock.calls.length).toBeGreaterThanOrEqual(2);
    w.unmount();
  });

  it('retires nothing when the confirmation is declined', async () => {
    const w = await mountPage();
    const vm = w.vm as unknown as VM;
    answerDialogs(vm, 'cancel');
    await vm.toggleRetired();
    await flushPromises();
    expect(retirePackage).not.toHaveBeenCalled();
    w.unmount();
  });

  it('says a restore does not bring the cancelled installs back', async () => {
    getPackage.mockResolvedValue({ ...pkg, retired_at: '2026-11-16T00:00:00Z' });
    restorePackage.mockResolvedValue(pkg);
    const w = await mountPage();
    const vm = w.vm as unknown as VM;
    const dialogs = answerDialogs(vm, 'ok');
    await vm.toggleRetired();
    await flushPromises();
    expect(dialogs[0]!.message).toContain('ne sont pas relancées');
    expect(restorePackage).toHaveBeenCalledWith('p-1');
    w.unmount();
  });

  it('shows what keeps every poste from installing, and names the file beside', async () => {
    const blocker =
      'Paquet non signé, et « helper.dll » est à côté de « Install.exe » : la méthode A refuse…';
    getPackage.mockResolvedValue({
      ...pkg,
      files: [
        ...pkg.files,
        { name: 'helper.dll', sha256: 'b'.repeat(64), size: 1, publisher_name: null },
      ],
      install_blockers: [blocker],
    });
    const w = await mountPage();
    expect(w.text()).toContain('Aucun poste ne l’installera');
    expect(w.text()).toContain(blocker);
    // The method A card no longer says the postes run it.
    expect(w.text()).not.toContain("les postes l'exécutent si la GPO liste ce nom");
    expect(w.text()).toContain('mais « helper.dll » est à côté');
    w.unmount();
  });

  it('lists the files as a French reader sorts them', async () => {
    const file = (name: string) => ({
      name,
      sha256: 'c'.repeat(64),
      size: 1,
      publisher_name: null,
    });
    getPackage.mockResolvedValue({
      ...pkg,
      files: [file('Zeta.ini'), file('été.txt'), file('alpha.iss'), file('Install.exe')],
    });
    const w = await mountPage();
    // The files card, past the form (whose select names the file to run).
    const text = w.text().slice(w.text().indexOf('Déposer'));
    const order = ['alpha.iss', 'été.txt', 'Install.exe', 'Zeta.ini'].map((n) => text.indexOf(n));
    expect(order.every((i) => i >= 0)).toBe(true);
    expect([...order].sort((a, b) => a - b)).toEqual(order);
    w.unmount();
  });

  it('says which files of a drop were kept and which were not sent', async () => {
    const refusal = {
      response: {
        status: 422,
        data: {
          error: {
            code: 'package.file.name_invalid',
            message: '« nul.txt » refusé : nom réservé par Windows (CON, PRN…)',
            details: { name: 'nul.txt', reason: 'nom réservé par Windows (CON, PRN…)' },
          },
        },
      },
    };
    uploadPackageFiles
      .mockReset()
      .mockImplementationOnce(() => Promise.resolve(pkg))
      .mockImplementationOnce(() => Promise.reject(Object.assign(new Error('422'), refusal)));
    const w = await mountPage();
    const vm = w.vm as unknown as VM;
    const notify = vi.spyOn(vm.$q, 'notify');
    vm.toUpload = ['a.ini', 'nul.txt', 'c.ini'].map((name) => ({ name, size: 1 }) as File);
    await vm.upload();
    await flushPromises();
    expect(uploadPackageFiles).toHaveBeenCalledTimes(2);
    expect(notify).toHaveBeenCalledWith(
      expect.objectContaining({
        type: 'negative',
        message: '« nul.txt » refusé : nom réservé par Windows (CON, PRN…)',
        caption: 'Déposé : a.ini. Non envoyés : nul.txt, c.ini.',
      }),
    );
    w.unmount();
  });

  it('asks before leaving while an upload runs, and interrupts it only then', async () => {
    let signal: AbortSignal | undefined;
    uploadPackageFiles.mockReset().mockImplementation((...a: unknown[]) => {
      signal = a[3] as AbortSignal;
      return new Promise(() => undefined);
    });
    const w = await mountPage();
    const vm = w.vm as unknown as VM;
    vm.toUpload = [{ name: 'gros.exe', size: 10 } as File];
    void vm.upload();
    await flushPromises();
    expect(vm.uploading).toBe(true);

    let dialogs = answerDialogs(vm, 'cancel');
    expect(await routeLeave.guard!()).toBe(false);
    expect(dialogs[0]!.message).toContain('Un dépôt de fichiers est en cours');
    expect(signal!.aborted).toBe(false);

    vi.mocked(vm.$q.dialog as () => unknown).mockRestore();
    dialogs = answerDialogs(vm, 'ok');
    expect(await routeLeave.guard!()).toBe(true);
    expect(signal!.aborted).toBe(true);
    w.unmount();
  });

  it('has the browser ask before closing during an upload or with unsaved changes', async () => {
    uploadPackageFiles.mockReset().mockImplementation(() => new Promise(() => undefined));
    const w = await mountPage();
    const vm = w.vm as unknown as VM;
    const unload = () => {
      const event = new Event('beforeunload', { cancelable: true });
      window.dispatchEvent(event);
      return event.defaultPrevented;
    };
    expect(unload()).toBe(false);

    vm.form.name = 'Pronote modifié';
    await flushPromises();
    expect(unload()).toBe(true);
    vm.form.name = 'Pronote';
    await flushPromises();
    expect(unload()).toBe(false);

    vm.toUpload = [{ name: 'gros.exe', size: 10 } as File];
    void vm.upload();
    await flushPromises();
    expect(unload()).toBe(true);

    w.unmount();
    // Gone with the page.
    expect(unload()).toBe(false);
  });

  it('offers to save before deploying a definition changed and not saved', async () => {
    updatePackage.mockImplementation((_id: string, fields: object) =>
      Promise.resolve({ ...pkg, ...fields }),
    );
    const w = await mountPage();
    const vm = w.vm as unknown as VM;

    // Nothing changed: straight to the deployment.
    let dialogs = answerDialogs(vm, 'ok');
    await vm.openDeploy('install');
    expect(dialogs).toHaveLength(0);
    expect(vm.deployOpen).toBe(true);
    vm.deployOpen = false;

    // Changed and declined: nothing saved, nothing opened.
    vm.form.install_args = '/S';
    await flushPromises();
    vi.mocked(vm.$q.dialog as () => unknown).mockRestore();
    dialogs = answerDialogs(vm, 'cancel');
    await vm.openDeploy('install');
    await flushPromises();
    expect(dialogs[0]!.message).toContain('enverrait la version enregistrée');
    expect(updatePackage).not.toHaveBeenCalled();
    expect(vm.deployOpen).toBe(false);

    // « Enregistrer puis déployer »: saved first, then the dialog.
    vi.mocked(vm.$q.dialog as () => unknown).mockRestore();
    dialogs = answerDialogs(vm, 'ok');
    await vm.openDeploy('install');
    await flushPromises();
    expect(dialogs[0]!.ok?.label).toBe('Enregistrer puis déployer');
    expect(updatePackage).toHaveBeenCalledWith(
      'p-1',
      expect.objectContaining({ install_args: ['/S'] }),
    );
    expect(vm.deployOpen).toBe(true);
    w.unmount();
  });

  it('does not open the deployment when the save before it fails', async () => {
    // « Enregistrer puis déployer », and the server refuses the definition:
    // the dialog would deploy the version saved before, the very thing the
    // question was asked to avoid.
    updatePackage.mockRejectedValue(new Error('422'));
    const w = await mountPage();
    const vm = w.vm as unknown as VM;
    const notify = vi.spyOn(vm.$q, 'notify');
    vm.form.install_args = '/S';
    await flushPromises();
    answerDialogs(vm, 'ok');
    await vm.openDeploy('install');
    await flushPromises();
    expect(updatePackage).toHaveBeenCalledTimes(1);
    expect(notify).toHaveBeenCalledWith(expect.objectContaining({ type: 'negative' }));
    expect(vm.deployOpen).toBe(false);

    // Saved at the next try, the deployment opens.
    updatePackage.mockImplementation((_id: string, fields: object) =>
      Promise.resolve({ ...pkg, ...fields }),
    );
    await vm.openDeploy('install');
    await flushPromises();
    expect(updatePackage).toHaveBeenCalledTimes(2);
    expect(vm.deployOpen).toBe(true);
    w.unmount();
  });

  it('filters the table to each poste’s latest deployment when a state is chosen', async () => {
    const w = await mountPage();
    const vm = w.vm as unknown as VM;
    vm.toggleStatusFilter('pending');
    await flushPromises();
    expect(listPackageCommands).toHaveBeenLastCalledWith('p-1', 1, 25, 'pending', true);
    expect(w.text()).toContain('Dernier déploiement de chaque poste, en attente');
    vm.toggleStatusFilter('pending');
    await flushPromises();
    expect(listPackageCommands).toHaveBeenLastCalledWith('p-1', 1, 25, null, false);
    expect(w.text()).toContain('Historique : tous les envois');
    w.unmount();
  });
});

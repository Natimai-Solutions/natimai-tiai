import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('boot/axios', () => ({
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), put: vi.fn(), delete: vi.fn() },
}));

import { api } from 'boot/axios';
import { apiErrorMessage } from './errors';
import {
  blockingProblems,
  compareFileNames,
  loadableBeside,
  manifestFileName,
  packageChoiceLabel,
  sortedFiles,
  deployPackage,
  deployable,
  formatSize,
  joinArgs,
  getPackageSummary,
  listPackageCommands,
  methodAMaxLabel,
  splitArgs,
  stepTrust,
  tooLargeFiles,
  tooLargeForMethodA,
  trustMethod,
  uninstallable,
  type Package,
} from './packages';

const GIB = 1024 ** 3;

function pkg(over: Partial<Package> = {}): Package {
  return {
    id: 'p-1',
    kind: 'files',
    name: 'Client PRONOTE',
    version: '2026.2.8',
    notes: null,
    winget_id: null,
    winget_version: null,
    install_run: 'Install_PRNclient.exe',
    install_args: [],
    uninstall_run: null,
    uninstall_args: [],
    success_codes: [0, 3010, 1641],
    detect_name: 'PRONOTE',
    files: [],
    signed: false,
    signer_subject: null,
    signer_thumbprint: null,
    signed_at: null,
    signed_by: null,
    publisher_name: null,
    method_a_too_large: false,
    method_a_max_bytes: 8 * GIB,
    file_max_bytes: 2 * GIB,
    problems: [],
    install_blockers: [],
    installed_count: 0,
    created_by: null,
    created_at: '2026-11-04T00:00:00Z',
    updated_at: '2026-11-04T00:00:00Z',
    retired_at: null,
    ...over,
  };
}

describe('command line fields', () => {
  it('splits on spaces and keeps quoted groups whole', () => {
    expect(splitArgs('-s  -f1"{dir}\\Client PRONOTE.iss" /norestart')).toEqual([
      '-s',
      '-f1{dir}\\Client PRONOTE.iss',
      '/norestart',
    ]);
  });

  it('keeps an empty quoted argument and an escaped quote', () => {
    expect(splitArgs('a "" "say \\"hi\\""')).toEqual(['a', '', 'say "hi"']);
  });

  it('joins back to something that splits the same', () => {
    const args = ['-s', '-f1{dir}\\Client PRONOTE.iss', '', 'x"y'];
    expect(splitArgs(joinArgs(args))).toEqual(args);
  });
});

describe('trust method', () => {
  it('reads which way a package can reach a poste', () => {
    expect(trustMethod(pkg({ kind: 'winget' }))).toBe('winget');
    expect(trustMethod(pkg({ signed: true }))).toBe('signed');
    expect(trustMethod(pkg({ publisher_name: 'INDEX EDUCATION SAS' }))).toBe('publisher');
    expect(trustMethod(pkg())).toBe('none');
    // A signed MSI is not method A: only executables are.
    expect(trustMethod(pkg({ install_run: 'app.msi', publisher_name: 'X' }))).toBe('none');
    // A DLL beside the executable: the agent refuses method A (audit S02).
    const file = (name: string) => ({
      name,
      sha256: 'a'.repeat(64),
      size: 1,
      publisher_name: null,
    });
    const pronote = { publisher_name: 'INDEX EDUCATION SAS' };
    expect(trustMethod(pkg({ ...pronote, files: [file('ClientPRONOTE.iss')] }))).toBe('publisher');
    expect(trustMethod(pkg({ ...pronote, files: [file('VERSION.DLL')] }))).toBe('none');
  });

  it('applies the agent rule to an uninstall too (audit T23, U04)', () => {
    const file = (name: string, publisher_name: string | null = null) => ({
      name,
      sha256: 'a'.repeat(64),
      size: 1,
      publisher_name,
    });
    const code = '{6C2A1A7B-0D5E-4F1C-9E4B-3B1C2D3E4F50}';
    const msiexec = (args: string[]) =>
      pkg({ uninstall_run: 'msiexec', uninstall_args: args, files: [file('app.msi')] });
    // Method A runs msiexec /x {product code}, unsigned, without any file.
    expect(stepTrust(msiexec(['/x', code, '/qn']), 'uninstall')).toBe('product_code');
    // Not an MSI path, not a code with anything around it.
    expect(stepTrust(msiexec(['/x', '{dir}\\app.msi']), 'uninstall')).toBe('none');
    expect(stepTrust(msiexec([`/x${code}`]), 'uninstall')).toBe('none');
    // Signed, everything goes (method B).
    expect(stepTrust({ ...msiexec(['/x', '{dir}\\app.msi']), signed: true }, 'uninstall')).toBe(
      'signed',
    );
    // An uninstaller .exe: its own publisher counts, not the installer's.
    const exe = (publisher: string | null) =>
      pkg({
        publisher_name: 'INDEX EDUCATION SAS',
        uninstall_run: 'uninst.exe',
        files: [
          file('Install_PRNclient.exe', 'INDEX EDUCATION SAS'),
          file('uninst.exe', publisher),
        ],
      });
    expect(stepTrust(exe(null), 'uninstall')).toBe('none');
    // Both executables are loadable beside each other: method A refuses.
    expect(stepTrust(exe('INDEX EDUCATION SAS'), 'uninstall')).toBe('none');
    const alone = pkg({
      uninstall_run: 'uninst.exe',
      files: [file('uninst.exe', 'INDEX'), file('uninst.ini')],
    });
    expect(stepTrust(alone, 'uninstall')).toBe('publisher');
    expect(stepTrust({ ...alone, uninstall_run: 'uninst.ini' }, 'uninstall')).toBe('none');
    // The install rule does not take a product code: the agent would turn it
    // into an uninstall.
    expect(
      trustMethod(pkg({ install_run: 'msiexec', install_args: ['/x', code], publisher_name: 'X' })),
    ).toBe('none');
  });

  it('counts the newer loadable extensions (audit T02)', () => {
    const file = (name: string) => ({
      name,
      sha256: 'a'.repeat(64),
      size: 1,
      publisher_name: null,
    });
    for (const ext of ['.bpl', '.pyd', '.xll', '.node', '.rll', '.wsc', '.sct']) {
      expect(
        trustMethod(pkg({ publisher_name: 'INDEX EDUCATION SAS', files: [file(`x${ext}`)] })),
      ).toBe('none');
    }
  });

  it('deploys only what is complete and not retired', () => {
    expect(deployable(pkg())).toBe(true);
    expect(deployable(pkg({ retired_at: '2026-11-04T00:00:00Z' }))).toBe(false);
    expect(
      deployable(pkg({ problems: [{ code: 'no_files', message: '', blocks_uninstall: true }] })),
    ).toBe(false);
  });

  it('leaves method A to packages under the cap the server reports', () => {
    const file = (name: string, publisher_name: string | null = null) => ({
      name,
      sha256: 'a'.repeat(64),
      size: 1,
      publisher_name,
    });
    const heavy = pkg({
      publisher_name: 'INDEX EDUCATION SAS',
      files: [file('Install_PRNclient.exe', 'INDEX EDUCATION SAS'), file('data.cab')],
      method_a_too_large: true,
    });
    // The agent refuses to download it unsigned (deploy.MethodAFiles).
    expect(trustMethod(heavy)).toBe('none');
    expect(tooLargeForMethodA(heavy, 'install')).toBe(true);
    expect(methodAMaxLabel(heavy)).toBe('8 Gio');
    expect(methodAMaxLabel({ ...heavy, method_a_max_bytes: 16 * GIB })).toBe('16 Gio');
    // Under the cap, the same package is method A.
    expect(trustMethod({ ...heavy, method_a_too_large: false })).toBe('publisher');
    // Signed, the size no longer counts.
    expect(trustMethod({ ...heavy, signed: true })).toBe('signed');
    expect(tooLargeForMethodA({ ...heavy, signed: true }, 'install')).toBe(false);
    // Not method A to begin with: the size is not what is wrong.
    expect(tooLargeForMethodA({ ...heavy, publisher_name: null }, 'install')).toBe(false);
    // An uninstaller .exe is downloaded too: capped. msiexec /x {code} is not.
    const exe = { ...heavy, uninstall_run: 'Install_PRNclient.exe', uninstall_args: ['/u'] };
    expect(stepTrust(exe, 'uninstall')).toBe('none');
    expect(tooLargeForMethodA(exe, 'uninstall')).toBe(true);
    const byCode = {
      ...heavy,
      uninstall_run: 'msiexec',
      uninstall_args: ['/x', '{6C2A1A7B-0D5E-4F1C-9E4B-3B1C2D3E4F50}'],
    };
    expect(stepTrust(byCode, 'uninstall')).toBe('product_code');
    expect(tooLargeForMethodA(byCode, 'uninstall')).toBe(false);
  });

  it('holds an uninstall back only for what the server flags', () => {
    const noInstall = { code: 'no_install', message: 'Fichier à lancer non choisi' };
    const missing = { code: 'install_missing', message: '« setup.exe » n’est pas dans le paquet' };
    const byCode = (problems: Package['problems']) =>
      pkg({ install_run: null, uninstall_run: 'msiexec', uninstall_args: ['/x'], problems });

    // The agent runs the uninstall step of a manifest without install step.
    const only = byCode([{ ...noInstall, blocks_uninstall: false }]);
    expect(deployable(only)).toBe(false);
    expect(uninstallable(only)).toBe(true);
    expect(blockingProblems(only, 'install')).toHaveLength(1);
    expect(blockingProblems(only, 'uninstall')).toEqual([]);
    // It refuses a manifest naming a file the package does not have.
    const broken = byCode([{ ...missing, blocks_uninstall: true }]);
    expect(uninstallable(broken)).toBe(false);
    expect(blockingProblems(broken, 'uninstall').map((p) => p.code)).toEqual(['install_missing']);
    // No uninstall defined; winget needs none; a retired package is still removed.
    expect(uninstallable(pkg())).toBe(false);
    expect(uninstallable(pkg({ kind: 'winget' }))).toBe(true);
    expect(uninstallable({ ...byCode([]), retired_at: '2026-11-04T00:00:00Z' })).toBe(true);
  });
});

describe('upload size', () => {
  const file = (name: string, size: number) => ({ name, size }) as File;

  it('checks files against the bound the server reports, not a built-in one', () => {
    const files = [file('petit.iss', 10), file('gros.exe', 3 * GIB)];
    // The default deployment: 2 Gio.
    expect(tooLargeFiles(pkg(), files).map((f) => f.name)).toEqual(['gros.exe']);
    // PACKAGE_MAX_BYTES raised to 4 Gio: the 3 Gio file is sent.
    expect(tooLargeFiles(pkg({ file_max_bytes: 4 * GIB }), files)).toEqual([]);
    // Lowered: refused before sending rather than after the transfer.
    expect(tooLargeFiles(pkg({ file_max_bytes: 5 }), files).map((f) => f.name)).toEqual([
      'petit.iss',
      'gros.exe',
    ]);
    // Exactly the bound is accepted, as the server accepts it.
    expect(tooLargeFiles(pkg({ file_max_bytes: 10 }), [file('x', 10)])).toEqual([]);
  });
});

describe('formatSize', () => {
  it('reads like the file explorer', () => {
    expect(formatSize(512)).toBe('512 o');
    expect(formatSize(1536)).toBe('1,5 Kio');
    expect(formatSize(250 * 1024 * 1024)).toBe('250 Mio');
  });
});

describe('deployment calls', () => {
  beforeEach(() => {
    vi.mocked(api.post).mockReset();
    vi.mocked(api.get).mockReset();
  });

  it('queues the install or uninstall type with the package', async () => {
    vi.mocked(api.post).mockResolvedValue({ data: { created: [], count: 2 } });
    await deployPackage('p-1', 'uninstall', { target_location: 'Lycée A' });
    expect(api.post).toHaveBeenCalledWith('/commands', {
      type: 'package_uninstall',
      package_id: 'p-1',
      target_location: 'Lycée A',
    });
  });

  it('lists the deployments of one package', async () => {
    vi.mocked(api.get).mockResolvedValue({ data: { items: [], total: 0 } });
    await listPackageCommands('p-1');
    expect(api.get).toHaveBeenCalledWith('/commands', {
      params: { package_id: 'p-1', page: 1, page_size: 25 },
    });
    await listPackageCommands('p-1', 3, 50, 'failed');
    expect(api.get).toHaveBeenLastCalledWith('/commands', {
      params: { package_id: 'p-1', page: 3, page_size: 50, status: 'failed' },
    });
  });

  it('reads the tally of a package', async () => {
    vi.mocked(api.get).mockResolvedValue({ data: { postes: 0, by_status: {}, by_action: {} } });
    await getPackageSummary('p-1');
    expect(api.get).toHaveBeenLastCalledWith('/commands/package-summary', {
      params: { package_id: 'p-1' },
    });
  });

  it('lists each poste’s latest deployment only when asked', async () => {
    vi.mocked(api.get).mockResolvedValue({ data: { items: [], total: 0 } });
    await listPackageCommands('p-1', 1, 25, 'pending', true);
    expect(api.get).toHaveBeenLastCalledWith('/commands', {
      params: { package_id: 'p-1', page: 1, page_size: 25, status: 'pending', latest: true },
    });
  });
});

describe('what the package page reads', () => {
  const file = (name: string) => ({ name, sha256: 'a'.repeat(64), size: 1, publisher_name: null });

  it('sorts file names as a French reader does', () => {
    const names = ['Zeta.exe', 'setup10.cab', 'été.txt', 'alpha.ini', 'Beta.dll', 'setup2.cab'];
    expect([...names].sort(compareFileNames)).toEqual([
      'alpha.ini',
      'Beta.dll',
      'été.txt',
      'setup2.cab',
      'setup10.cab',
      'Zeta.exe',
    ]);
    expect(sortedFiles(pkg({ files: names.map(file) })).map((f) => f.name)[0]).toBe('alpha.ini');
  });

  it('names the files that keep method A from running the executable', () => {
    const p = pkg({
      install_run: 'setup.exe',
      files: [file('setup.exe'), file('Helper.dll'), file('readme.txt'), file('autre.msi')],
    });
    expect(loadableBeside(p)).toEqual(['autre.msi', 'Helper.dll']);
  });

  it('never saves the manifest under a bare extension', () => {
    expect(manifestFileName(pkg({ name: 'Блокнот', version: null }))).toBe(
      'p-1.tiai-manifest.json',
    );
    expect(manifestFileName(pkg({ name: 'Блокнот', version: '1.0' }))).toBe(
      'p-1-1.0.tiai-manifest.json',
    );
    expect(manifestFileName(pkg({ name: 'Client PRONOTE', version: '2026.2.8' }))).toBe(
      'Client-PRONOTE-2026.2.8.tiai-manifest.json',
    );
  });

  it('tells apart two packages read the same in a list', () => {
    const a = pkg({ id: 'a', name: 'Outil', version: '1', install_run: 'setup.exe' });
    const b = pkg({ id: 'b', name: 'Outil', version: '1', kind: 'winget', winget_id: 'X.Outil' });
    const c = pkg({ id: 'c', name: 'Autre', version: null });
    expect(packageChoiceLabel(c, [a, b, c])).toBe('Autre');
    expect(packageChoiceLabel(a, [a, b, c])).toMatch(/^Outil 1 \(fichiers, setup\.exe — créé le /);
    expect(packageChoiceLabel(b, [a, b, c])).toMatch(/^Outil 1 \(winget X\.Outil — créé le /);
  });
});

describe('refusals the console passes on', () => {
  const refusal = (code: string, message: string, details: object = {}) => ({
    response: { status: 422, data: { error: { code, message, details } } },
  });

  it('says why a signature was refused', () => {
    const why =
      'La signature ne correspond pas au manifeste actuel : le paquet a changé depuis le téléchargement du manifeste signé.';
    expect(apiErrorMessage(refusal('package.signature.invalid', why))).toBe(
      `Signature refusée : ${why}`,
    );
  });

  it('names a refused file and the rule it breaks', () => {
    const message =
      '« _config.ini » refusé : le nom doit commencer par une lettre sans accent ou un chiffre';
    expect(
      apiErrorMessage(
        refusal('package.file.name_invalid', message, {
          name: '_config.ini',
          reason: 'le nom doit commencer par une lettre sans accent ou un chiffre',
        }),
      ),
    ).toBe(message);
    // An older server, without the reason: the label as before.
    expect(
      apiErrorMessage(refusal('package.file.name_invalid', 'Nom de fichier refusé', { name: 'x' })),
    ).toContain('Nom de fichier refusé : lettres, chiffres');
  });
});

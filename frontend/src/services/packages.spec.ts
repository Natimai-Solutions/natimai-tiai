import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('boot/axios', () => ({
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), put: vi.fn(), delete: vi.fn() },
}));

import { api } from 'boot/axios';
import {
  deployPackage,
  deployable,
  formatSize,
  joinArgs,
  listPackageCommands,
  splitArgs,
  trustMethod,
  type Package,
} from './packages';

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
    problems: [],
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
  });

  it('deploys only what is complete and not retired', () => {
    expect(deployable(pkg())).toBe(true);
    expect(deployable(pkg({ retired_at: '2026-11-04T00:00:00Z' }))).toBe(false);
    expect(deployable(pkg({ problems: [{ code: 'no_files', message: '' }] }))).toBe(false);
  });
});

describe('formatSize', () => {
  it('reads like the file explorer', () => {
    expect(formatSize(512)).toBe('512 o');
    expect(formatSize(1536)).toBe('1.5 Kio');
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
      params: { package_id: 'p-1', page: 1, page_size: 50 },
    });
  });
});

import { flushPromises, mount } from '@vue/test-utils';
import { QForm } from 'quasar';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { Package } from 'src/services/packages';

const listPackages = vi.fn();
const createPackage = vi.fn();
const push = vi.fn();

vi.mock('src/services/packages', async (orig) => ({
  ...(await orig<object>()),
  listPackages: (...a: unknown[]) => listPackages(...a),
  createPackage: (...a: unknown[]) => createPackage(...a),
}));
vi.mock('vue-router', async (orig) => ({
  ...(await orig<object>()),
  useRouter: () => ({ push }),
}));
vi.mock('src/stores/auth', () => ({
  useAuthStore: () => ({ can: () => true, user: { id: 'u' }, permissions: [] }),
}));

import PackagesPage from './PackagesPage.vue';

function pkg(over: Partial<Package> = {}): Package {
  return {
    id: 'p-1',
    kind: 'files',
    name: 'Outil',
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
    files: [{ name: 'setup.exe', sha256: 'a'.repeat(64), size: 1, publisher_name: null }],
    signed: false,
    signer_subject: null,
    signer_thumbprint: null,
    signed_at: null,
    signed_by: null,
    publisher_name: null,
    method_a_too_large: false,
    method_a_max_bytes: 8 * 1024 ** 3,
    file_max_bytes: 2 * 1024 ** 3,
    problems: [],
    install_blockers: [],
    installed_count: null,
    created_by: null,
    created_at: '2026-11-04T00:00:00Z',
    updated_at: '2026-11-04T00:00:00Z',
    retired_at: null,
    ...over,
  };
}

async function mountPage() {
  const w = mount(PackagesPage, {
    attachTo: document.body,
    global: { stubs: { QPage: { template: '<div><slot /></div>' } } },
  });
  await flushPromises();
  return w;
}

describe('PackagesPage', () => {
  beforeEach(() => {
    listPackages.mockReset().mockResolvedValue([]);
    createPackage.mockReset();
    push.mockReset();
    document.body.innerHTML = '';
  });

  it('does not call « Prêt » a package no poste would install', async () => {
    const blocker =
      'Paquet non signé, et « setup.exe » ne porte pas de signature d’éditeur : aucun poste ne l’exécutera.';
    listPackages.mockResolvedValue([
      pkg({ id: 'unsigned', name: 'Non signé', install_blockers: [blocker] }),
      pkg({ id: 'ready', name: 'Prêt pour de bon', publisher_name: 'Éditeur' }),
    ]);
    const w = await mountPage();
    const rows = w.findAll('tbody tr').map((r) => r.text());
    const unsigned = rows.find((r) => r.includes('Non signé'))!;
    expect(unsigned).toContain(blocker);
    expect(unsigned).not.toContain('Prêt');
    expect(rows.find((r) => r.includes('Prêt pour de bon'))).toContain('Prêt');
    w.unmount();
  });

  it('accepts a winget identifier typed with spaces around it, and trims it', async () => {
    createPackage.mockResolvedValue(pkg({ id: 'new', kind: 'winget' }));
    const w = await mountPage();
    const vm = w.vm as unknown as {
      openCreate: () => void;
      form: { kind: string; name: string; winget_id: string };
    };
    vm.openCreate();
    await flushPromises();
    vm.form.name = 'Firefox';
    vm.form.winget_id = '  Mozilla.Firefox ';
    await flushPromises();
    const form = w.findComponent(QForm);
    expect(await (form.vm as unknown as { validate: () => Promise<boolean> }).validate()).toBe(
      true,
    );
    await form.trigger('submit');
    await flushPromises();
    expect(createPackage).toHaveBeenCalledWith(
      expect.objectContaining({ kind: 'winget', winget_id: 'Mozilla.Firefox' }),
    );
    w.unmount();
  });

  it('bounds the fields as the server does', async () => {
    const w = await mountPage();
    (w.vm as unknown as { openCreate: () => void }).openCreate();
    await flushPromises();
    const inputs = [...document.querySelectorAll('.q-dialog input')] as HTMLInputElement[];
    const bounds = inputs.map((i) => i.getAttribute('maxlength'));
    // Nom, version, identifiant winget.
    expect(bounds).toEqual(['200', '100', '128']);
    w.unmount();
  });
});

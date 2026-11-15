import { flushPromises, mount } from '@vue/test-utils';
import { QBtn, QSelect } from 'quasar';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { Package } from 'src/services/packages';

const listMachines = vi.fn();
const listLocations = vi.fn();
const deployPackage = vi.fn();

vi.mock('src/services/machines', async (orig) => ({
  ...(await orig<object>()),
  listMachines: (...a: unknown[]) => listMachines(...a),
  listLocations: (...a: unknown[]) => listLocations(...a),
}));
vi.mock('src/services/packages', async (orig) => ({
  ...(await orig<object>()),
  deployPackage: (...a: unknown[]) => deployPackage(...a),
  listPackages: () => Promise.resolve([]),
}));

import PackageDeployDialog from './PackageDeployDialog.vue';

const PRODUCT_CODE = '{6C2A1A7B-0D5E-4F1C-9E4B-3B1C2D3E4F50}';

function pkg(over: Partial<Package> = {}): Package {
  return {
    id: 'p-1',
    kind: 'files',
    name: 'LibreOffice',
    version: '24.8',
    notes: null,
    winget_id: null,
    winget_version: null,
    install_run: 'setup.exe',
    install_args: [],
    uninstall_run: 'setup.exe',
    uninstall_args: ['/uninstall'],
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
    installed_count: null,
    created_by: null,
    created_at: '2026-11-04T00:00:00Z',
    updated_at: '2026-11-04T00:00:00Z',
    retired_at: null,
    ...over,
  };
}

/** Mounted closed, then opened: the dialog fills itself as it shows. */
async function open(props: Record<string, unknown>) {
  const wrapper = mount(PackageDeployDialog, {
    props: { modelValue: false, ...props },
    attachTo: document.body,
  });
  await wrapper.setProps({ modelValue: true });
  await flushPromises();
  return wrapper;
}

const sendButton = (w: Awaited<ReturnType<typeof open>>) =>
  w
    .findAllComponents(QBtn)
    .filter((b) => /^(Installer|Désinstaller)/.test(String(b.props('label'))))
    .at(-1)!;

describe('PackageDeployDialog', () => {
  beforeEach(() => {
    listMachines.mockReset().mockResolvedValue({ total: 3, items: [] });
    listLocations.mockReset().mockResolvedValue([{ name: 'Lycée A', count: 3 }]);
    deployPackage.mockReset().mockResolvedValue({ created: [], count: 3, skipped: 0 });
    document.body.innerHTML = '';
  });

  it('does not send an uninstall no poste would run (audit T23)', async () => {
    // The uninstaller is not a signed executable, and the package is unsigned.
    const unsigned = pkg({
      uninstall_run: 'uninst.exe',
      files: [
        { name: 'setup.exe', sha256: 'a'.repeat(64), size: 1, publisher_name: 'TDF' },
        { name: 'uninst.exe', sha256: 'b'.repeat(64), size: 1, publisher_name: null },
      ],
    });
    const w = await open({ package: unsigned, machineIds: ['m-1'], initialAction: 'uninstall' });
    expect(document.querySelector('.q-banner')?.textContent).toContain(
      'aucun poste ne l’exécutera',
    );
    expect(sendButton(w).props('disable')).toBe(true);
    w.unmount();
  });

  it('sends msiexec /x {product code}, which method A runs (audit T23)', async () => {
    const byCode = pkg({ uninstall_run: 'msiexec', uninstall_args: ['/x', PRODUCT_CODE, '/qn'] });
    const w = await open({ package: byCode, machineIds: ['m-1'], initialAction: 'uninstall' });
    const banner = document.querySelector('.q-banner')?.textContent ?? '';
    expect(banner).toContain('code produit');
    expect(banner).not.toContain('aucun poste');
    expect(sendButton(w).props('disable')).toBe(false);
    w.unmount();
  });

  it('sends an uninstall by product code of a package without install step', async () => {
    // The server queues it and the agent runs it: the one problem that does
    // not hold an uninstall back.
    const byCode = pkg({
      install_run: null,
      uninstall_run: 'msiexec',
      uninstall_args: ['/x', PRODUCT_CODE],
      problems: [
        { code: 'no_install', message: 'Fichier à lancer non choisi', blocks_uninstall: false },
      ],
    });
    const w = await open({ package: byCode, machineIds: ['m-1'], initialAction: 'uninstall' });
    expect(document.querySelector('.q-banner')?.textContent).toContain('code produit');
    expect(sendButton(w).props('disable')).toBe(false);
    await sendButton(w).trigger('click');
    await flushPromises();
    (
      [...document.querySelectorAll('.q-dialog-plugin button')].find(
        (b) => b.textContent?.trim() === 'Désinstaller',
      ) as HTMLElement
    ).click();
    await flushPromises();
    expect(deployPackage).toHaveBeenCalledWith('p-1', 'uninstall', { machine_ids: ['m-1'] });
    w.unmount();
  });

  it('does not send an uninstall the server would answer 409 to', async () => {
    // The agent refuses the whole manifest: the install step names a file
    // the package does not have. The server refuses the command for it.
    const broken = pkg({
      uninstall_run: 'msiexec',
      uninstall_args: ['/x', PRODUCT_CODE],
      problems: [
        {
          code: 'install_missing',
          message: '« setup.exe » n’est pas dans le paquet',
          blocks_uninstall: true,
        },
      ],
    });
    const w = await open({ package: broken, machineIds: ['m-1'], initialAction: 'uninstall' });
    const banner = document.querySelector('.q-banner')?.textContent ?? '';
    expect(banner).toContain('Désinstallation impossible');
    expect(banner).toContain('« setup.exe » n’est pas dans le paquet');
    expect(sendButton(w).props('disable')).toBe(true);
    w.unmount();
  });

  it('says to sign a package too large for method A, and does not send it', async () => {
    const heavy = pkg({ method_a_too_large: true });
    const w = await open({ package: heavy, machineIds: ['m-1'] });
    const banner = document.querySelector('.q-banner')?.textContent ?? '';
    expect(banner).toContain('Plus de 8 Gio de fichiers');
    expect(banner).toContain('Signez le paquet');
    expect(sendButton(w).props('disable')).toBe(true);
    await w.setProps({ package: { ...heavy, signed: true } });
    expect(sendButton(w).props('disable')).toBe(false);
    w.unmount();
  });

  it('asks nothing once closed while the postes were being counted', async () => {
    let counted!: (v: unknown) => void;
    listMachines.mockReset().mockReturnValue(new Promise((resolve) => (counted = resolve)));
    const w = await open({ package: pkg(), initialAction: 'uninstall' });
    await w.findComponent(QSelect).setValue('Lycée A');
    await flushPromises();

    await sendButton(w).trigger('click');
    // « Annuler », while the count is still on its way.
    await w.setProps({ modelValue: false });
    counted({ total: 3, items: [] });
    await flushPromises();

    expect(document.querySelectorAll('.q-dialog-plugin')).toHaveLength(0);
    expect(deployPackage).not.toHaveBeenCalled();
    w.unmount();
  });

  it('is usable again when reopened after a send that never finished', async () => {
    // The count never answers: the first showing stays busy to its end.
    listMachines.mockReset().mockReturnValue(new Promise(() => undefined));
    const w = await open({ package: pkg(), initialAction: 'uninstall' });
    await w.findComponent(QSelect).setValue('Lycée A');
    await flushPromises();
    await sendButton(w).trigger('click');
    await flushPromises();
    expect(sendButton(w).props('disable')).toBe(true);

    await w.setProps({ modelValue: false });
    await w.setProps({ modelValue: true });
    await flushPromises();
    await w.findComponent(QSelect).setValue('Lycée A');
    await flushPromises();
    expect(sendButton(w).props('disable')).toBe(false);

    // And the new showing sends on its own count.
    listMachines.mockReset().mockResolvedValue({ total: 2, items: [] });
    await sendButton(w).trigger('click');
    await flushPromises();
    expect(document.body.textContent).toContain('Désinstaller sur 2 postes ?');
    expect(document.querySelectorAll('.q-dialog-plugin')).toHaveLength(1);
    w.unmount();
  });

  it('opens one confirmation for a double click while counting the postes', async () => {
    let counted!: (v: unknown) => void;
    listMachines.mockReset().mockReturnValue(new Promise((resolve) => (counted = resolve)));
    const w = await open({ package: pkg(), initialAction: 'uninstall' });
    await w.findComponent(QSelect).setValue('Lycée A');
    await flushPromises();

    await sendButton(w).trigger('click');
    await sendButton(w).trigger('click');
    counted({ total: 3, items: [] });
    await flushPromises();

    expect(listMachines).toHaveBeenCalledTimes(1);
    expect(document.querySelectorAll('.q-dialog-plugin')).toHaveLength(1);
    expect(document.body.textContent).toContain('Désinstaller sur 3 postes ?');
    const confirm = [...document.querySelectorAll('.q-dialog-plugin button')].find(
      (b) => b.textContent?.trim() === 'Désinstaller',
    ) as HTMLElement;
    confirm.click();
    await flushPromises();
    expect(deployPackage).toHaveBeenCalledTimes(1);
    expect(deployPackage).toHaveBeenCalledWith('p-1', 'uninstall', {
      target_location: 'Lycée A',
    });
    w.unmount();
  });
});

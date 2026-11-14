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

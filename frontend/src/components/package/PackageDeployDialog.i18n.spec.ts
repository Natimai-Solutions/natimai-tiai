import { flushPromises, mount } from '@vue/test-utils';
import { QBtn } from 'quasar';
import { nextTick } from 'vue';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { setLocale } from 'src/i18n';
import type { Package } from 'src/services/packages';

const listMachines = vi.fn();

vi.mock('src/services/machines', async (orig) => ({
  ...(await orig<object>()),
  listMachines: (...a: unknown[]) => listMachines(...a),
  listLocations: () => Promise.resolve([{ name: 'Building A', count: 3 }]),
}));
vi.mock('src/services/packages', async (orig) => ({
  ...(await orig<object>()),
  deployPackage: vi.fn(),
  listPackages: () => Promise.resolve([]),
}));

import PackageDeployDialog from './PackageDeployDialog.vue';

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
    install_blockers: [],
    installed_count: null,
    created_by: null,
    created_at: '2026-11-04T00:00:00Z',
    updated_at: '2026-11-04T00:00:00Z',
    retired_at: null,
    ...over,
  };
}

async function open(props: Record<string, unknown>) {
  const wrapper = mount(PackageDeployDialog, {
    props: { modelValue: false, ...props },
    attachTo: document.body,
  });
  await wrapper.setProps({ modelValue: true });
  await flushPromises();
  return wrapper;
}

const dialogText = () => document.querySelector('.q-dialog')?.textContent ?? '';
const labels = (w: Awaited<ReturnType<typeof open>>) =>
  w.findAllComponents(QBtn).map((b) => String(b.props('label')));

describe('PackageDeployDialog in English', () => {
  beforeEach(() => {
    listMachines.mockReset().mockResolvedValue({ total: 0, items: [] });
    document.body.innerHTML = '';
  });
  afterEach(() => setLocale('fr'));

  it('reads in English, on the fleet or one location', async () => {
    setLocale('en');
    const w = await open({ package: pkg() });
    const text = dialogText();
    expect(text).toContain('Install software');
    expect(text).toContain('The whole fleet');
    expect(text).toContain('One location');
    expect(text).toContain(
      'Not signed by the administrator: only the computers whose GPO approves the publisher “TDF” (DeployPublishers) will run it.',
    );
    expect(labels(w)).toContain('Install on …');
    expect(text).not.toMatch(/[éèàùç«»]/);
    w.unmount();
  });

  it('names the computers it acts on, and the reason none would run it', async () => {
    setLocale('en');
    const w = await open({
      package: pkg({ method_a_too_large: true }),
      machineIds: ['m1', 'm2'],
    });
    expect(dialogText()).toContain('On 2 computers.');
    expect(dialogText()).toContain(
      'More than 8 GiB of files: without the administrator’s signature, no computer will download them',
    );
    expect(labels(w)).toContain('Install on 2 computers');
    w.unmount();
  });

  it('confirms an uninstall in English, zero computers included', async () => {
    setLocale('en');
    const w = await open({ package: pkg(), initialAction: 'uninstall' });
    // The whole fleet, counted: none.
    (w.vm as unknown as { scope: string }).scope = 'all';
    await nextTick();
    const send = w
      .findAllComponents(QBtn)
      .find((b) => b.props('label') === 'Uninstall on the whole fleet')!;
    await send.trigger('click');
    await flushPromises();
    expect(document.body.textContent).toContain('Uninstall LibreOffice');
    expect(document.body.textContent).toContain('Uninstall on 0 computers (the whole fleet)?');
    w.unmount();
  });

  it('says zero computers in the singular in French, as before', async () => {
    const w = await open({ package: pkg(), initialAction: 'uninstall' });
    (w.vm as unknown as { scope: string }).scope = 'all';
    await nextTick();
    const send = w
      .findAllComponents(QBtn)
      .find((b) => b.props('label') === 'Désinstaller sur tout le parc')!;
    await send.trigger('click');
    await flushPromises();
    expect(document.body.textContent).toContain('Désinstaller sur 0 poste (tout le parc) ?');
    w.unmount();
  });

  // A location counted at zero goes through whereCount, not whereCountAll:
  // its three forms keep « 0 poste » in the singular too.
  it('says zero computers of a location in the singular in French, plural in English', async () => {
    const uninstallOnBuildingA = async (label: string) => {
      const w = await open({ package: pkg(), initialAction: 'uninstall' });
      (w.vm as unknown as { location: string }).location = 'Building A';
      await nextTick();
      const send = w.findAllComponents(QBtn).find((b) => b.props('label') === label)!;
      await send.trigger('click');
      await flushPromises();
      expect(listMachines).toHaveBeenLastCalledWith({ location: 'Building A', page_size: 1 });
      return w;
    };
    let w = await uninstallOnBuildingA('Désinstaller sur Building A');
    expect(document.body.textContent).toContain('Désinstaller sur 0 poste ?');
    w.unmount();
    document.body.innerHTML = '';

    setLocale('en');
    w = await uninstallOnBuildingA('Uninstall on Building A');
    expect(document.body.textContent).toContain('Uninstall on 0 computers?');
    w.unmount();
  });

  it('follows a change of language while open', async () => {
    const w = await open({ package: pkg({ kind: 'winget', winget_id: 'Mozilla.Firefox' }) });
    expect(dialogText()).toContain('Installer un logiciel');
    setLocale('en');
    await nextTick();
    expect(dialogText()).toContain('Install software');
    expect(dialogText()).toContain(
      'winget package: only the computers whose GPO turns winget on (DeployWinget) will install it.',
    );
    w.unmount();
  });
});

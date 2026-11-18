import { flushPromises, mount } from '@vue/test-utils';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { nextTick } from 'vue';

vi.mock('src/services/machines', async (importOriginal) => ({
  ...(await importOriginal<typeof import('src/services/machines')>()),
  listExportColumns: vi.fn(),
  exportMachines: vi.fn(),
}));
vi.mock('src/utils/format', async (importOriginal) => ({
  ...(await importOriginal<typeof import('src/utils/format')>()),
  downloadBlob: vi.fn(),
}));

import { setLocale } from 'src/i18n';
import { exportMachines, listExportColumns, type ExportColumn } from 'src/services/machines';
import { downloadBlob } from 'src/utils/format';
import MachineExportDialog from './MachineExportDialog.vue';

/** The catalogue as the server lists it, in the language it was asked. */
function catalogue(lang: 'fr' | 'en'): ExportColumn[] {
  const fr = lang === 'fr';
  return [
    {
      key: 'hostname',
      label: fr ? 'Nom' : 'Name',
      group: 'identity',
      group_label: fr ? 'Identité' : 'Identity',
      kind: 'text',
      default: true,
    },
    {
      key: 'cpu_model',
      label: fr ? 'Processeur' : 'Processor',
      group: 'hardware',
      group_label: fr ? 'Matériel' : 'Hardware',
      kind: 'text',
      default: false,
    },
  ];
}

let shown: 'fr' | 'en' = 'fr';

beforeEach(() => {
  shown = 'fr';
  localStorage.clear();
  vi.mocked(listExportColumns).mockReset();
  vi.mocked(listExportColumns).mockImplementation(() => Promise.resolve(catalogue(shown)));
  vi.mocked(exportMachines).mockReset();
  vi.mocked(exportMachines).mockResolvedValue(new Blob(['x']));
  vi.mocked(downloadBlob).mockReset();
});

afterEach(() => {
  setLocale('fr');
  document.body.innerHTML = '';
});

async function mountDialog(count = 1234) {
  const wrapper = mount(MachineExportDialog, {
    props: { modelValue: true, params: {}, count },
    global: { stubs: { QScrollArea: { template: '<div><slot /></div>' } } },
    attachTo: document.body,
  });
  await flushPromises();
  return wrapper;
}

function dialogText(): string {
  return document.body.querySelector('.q-dialog')?.textContent ?? '';
}

function button(label: string): HTMLButtonElement {
  const found = [...document.body.querySelectorAll<HTMLButtonElement>('.q-dialog button')].find(
    (b) => b.textContent?.includes(label),
  );
  expect(found, `button « ${label} »`).toBeDefined();
  return found!;
}

describe('MachineExportDialog', () => {
  it('reads in French as it always did', async () => {
    const wrapper = await mountDialog(1);
    const text = dialogText();
    expect(text).toContain('Exporter le parc');
    expect(text).toContain("1 poste — les filtres de la liste s'appliquent, pas la pagination.");
    expect(text).toContain('Colonnes disponibles');
    expect(text).toContain('Colonnes exportées (1)');
    expect(text).toContain('Par défaut');
    expect(text).toContain('Tout retirer');
    expect(text).toContain('Exporter en Excel');
    expect(text).toContain('Matériel');
    const input = document.body.querySelector('.q-dialog input')!;
    expect(input.getAttribute('placeholder')).toBe('Rechercher une colonne…');
    expect(input.getAttribute('aria-label')).toBe('Rechercher une colonne');
    expect(document.body.querySelector('[aria-label="Retirer la colonne"]')).not.toBeNull();
    wrapper.unmount();
  });

  it('reads in English, the catalogue included, with no French left', async () => {
    setLocale('en');
    shown = 'en';
    const wrapper = await mountDialog(1234);
    const text = dialogText();
    expect(text).toContain('Export the fleet');
    expect(text).toContain("1,234 computers — the list's filters apply, not its pages.");
    expect(text).toContain('Available columns');
    expect(text).toContain('Exported columns (1)');
    expect(text).toContain('Defaults');
    expect(text).toContain('Remove all');
    expect(text).toContain('Export to Excel');
    expect(text).toContain('Hardware');
    expect(text).toContain('Processor');
    expect(text).not.toMatch(/[éèàùçÉ«»]/);
    expect(text).not.toMatch(/Exporter|Colonnes|Annuler|poste/);
    const input = document.body.querySelector('.q-dialog input')!;
    expect(input.getAttribute('placeholder')).toBe('Search for a column…');
    expect(document.body.querySelector('[aria-label="Remove the column"]')).not.toBeNull();
    wrapper.unmount();
  });

  it('switches language live, the catalogue reloaded and the choice kept', async () => {
    const wrapper = await mountDialog(2);
    expect(dialogText()).toContain('Exporter le parc');
    expect(listExportColumns).toHaveBeenCalledTimes(1);

    // Add a column, then change language: the keys chosen stay.
    const processor = [...document.body.querySelectorAll('.q-dialog .q-item')].find((i) =>
      i.textContent?.includes('Processeur'),
    ) as HTMLElement;
    processor.click();
    await nextTick();
    expect(dialogText()).toContain('Colonnes exportées (2)');

    shown = 'en';
    setLocale('en');
    await flushPromises();
    expect(listExportColumns).toHaveBeenCalledTimes(2);
    const text = dialogText();
    expect(text).toContain('Export the fleet');
    expect(text).toContain('2 computers');
    expect(text).toContain('Exported columns (2)');
    expect(text).toContain('Processor');
    wrapper.unmount();
  });

  it('names the downloaded file in the language shown', async () => {
    setLocale('en');
    shown = 'en';
    const wrapper = await mountDialog();
    button('Export to Excel').click();
    await flushPromises();
    expect(exportMachines).toHaveBeenCalledWith(
      {},
      expect.objectContaining({ format: 'xlsx', columns: ['hostname'] }),
    );
    expect(downloadBlob).toHaveBeenCalledWith(expect.any(Blob), 'fleet.xlsx');
    wrapper.unmount();
  });

  it('keeps the French file name in French', async () => {
    const wrapper = await mountDialog();
    button('Exporter en Excel').click();
    await flushPromises();
    expect(downloadBlob).toHaveBeenCalledWith(expect.any(Blob), 'parc.xlsx');
    wrapper.unmount();
  });

  it('says in the language shown that the catalogue could not be read', async () => {
    setLocale('en');
    vi.mocked(listExportColumns).mockRejectedValue(new Error('network'));
    const wrapper = await mountDialog();
    expect(dialogText()).toContain('Could not load the list of columns');
    wrapper.unmount();
  });
});

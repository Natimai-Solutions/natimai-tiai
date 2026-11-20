import { flushPromises, mount } from '@vue/test-utils';
import { QBtn, QFile, QTable } from 'quasar';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('src/services/assets', async (importOriginal) => ({
  ...(await importOriginal<typeof import('src/services/assets')>()),
  importAssets: vi.fn(),
}));

import { setLocale } from 'src/i18n';
import { importAssets, type ImportResult } from 'src/services/assets';
import { apiErrorMessage } from 'src/services/errors';
import AssetImportDialog from './AssetImportDialog.vue';

const preview: ImportResult = {
  dry_run: true,
  counts: { update: 1, invalid: 1 },
  rows: [
    {
      line: 2,
      serial: 'SN-1',
      action: 'update',
      machine_id: 'm-1',
      hostname: 'PC-1',
      changes: {
        purchase_date: '2024-03-01',
        purchase_price: '1234.5',
        status: 'on_loan',
        supplier: 'Dell',
      },
      errors: [],
    },
    {
      line: 3,
      serial: 'SN-1',
      action: 'invalid',
      machine_id: 'm-1',
      hostname: 'PC-1',
      changes: {},
      errors: ['duplicate_serial'],
    },
  ],
};

async function open() {
  const wrapper = mount(AssetImportDialog, {
    props: { modelValue: false },
    attachTo: document.body,
  });
  await wrapper.setProps({ modelValue: true });
  await flushPromises();
  const button = (label: string) =>
    wrapper.findAllComponents(QBtn).find((b) => String(b.props('label')).startsWith(label))!;
  return { wrapper, button };
}

describe('AssetImportDialog', () => {
  beforeEach(() => {
    document.body.innerHTML = '';
    setLocale('fr');
    vi.mocked(importAssets).mockReset();
  });

  it('says the limits up front', async () => {
    const { wrapper } = await open();
    expect(document.body.textContent).toMatch(/Jusqu’à 5\s000 lignes et 8 Mo/);
    wrapper.unmount();
  });

  it('checks first, in the console’s words, then writes and says so', async () => {
    vi.mocked(importAssets)
      .mockResolvedValueOnce(preview)
      .mockResolvedValueOnce({ ...preview, dry_run: false });
    const { wrapper, button } = await open();
    const file = new File(['x'], 'parc.csv');
    wrapper.findComponent(QFile).vm.$emit('update:modelValue', file);
    await flushPromises();

    await button('Vérifier').trigger('click');
    await flushPromises();
    expect(importAssets).toHaveBeenLastCalledWith(file, true);
    const text = document.body.textContent ?? '';
    // The fields as the form names them, the values as the console writes them.
    expect(text).toContain('Date d’achat : 01/03/2024');
    expect(text).toContain('Statut : Prêté');
    expect(text).toContain('Fournisseur : Dell');
    expect(text).toMatch(/Prix d’achat : 1\s234,50/);
    expect(text).not.toContain('purchase_date');
    expect(text).toContain('poste déjà sur une ligne au-dessus');
    const rows = wrapper.findComponent(QTable).props('rows') as unknown[];
    expect(rows).toHaveLength(2);

    await button('Importer').trigger('click');
    await flushPromises();
    expect(importAssets).toHaveBeenLastCalledWith(file, false);
    expect(wrapper.emitted('imported')).toHaveLength(1);
    wrapper.unmount();
  });
});

describe('an import refused for its size', () => {
  afterEach(() => setLocale('fr'));

  it('says which limit and that the file is to be split, not that it is unreadable', () => {
    const refusal = (cause: object) => ({
      response: {
        status: 422,
        data: { error: { code: 'asset.import.too_large', details: { cause } } },
      },
    });
    expect(apiErrorMessage(refusal({ code: 'too_many_rows', params: { max: 5000 } }))).toContain(
      '5000 lignes au plus : découpez le fichier',
    );
    expect(apiErrorMessage(refusal({ code: 'file_too_large', params: { max_mb: 8 } }))).toContain(
      '8 Mo au plus',
    );
    expect(
      apiErrorMessage(refusal({ code: 'file_too_large', params: { max_mb: 8 } })),
    ).not.toContain('illisible');
    // A template formatted far down: its empty rows to delete, not to split.
    expect(
      apiErrorMessage(refusal({ code: 'too_many_blank_rows', params: { max: 100000 } })),
    ).toContain('supprimez-les');
    setLocale('en');
    expect(apiErrorMessage(refusal({ code: 'too_many_rows', params: { max: 5000 } }))).toContain(
      '5000 rows at most',
    );
  });
});

import { flushPromises, mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import { QForm, QInput, QSelect } from 'quasar';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { defineComponent, h, type Component } from 'vue';
import { createMemoryHistory, createRouter } from 'vue-router';

vi.mock('src/services/licenses', async (importOriginal) => ({
  ...(await importOriginal<typeof import('src/services/licenses')>()),
  listLicenses: vi.fn(),
  createLicense: vi.fn(),
  updateLicense: vi.fn(),
  deleteLicense: vi.fn(),
  previewLicense: vi.fn(),
}));

import {
  createLicense,
  deleteLicense,
  listLicenses,
  previewLicense,
  updateLicense,
  type License,
} from 'src/services/licenses';
import { useAuthStore } from 'src/stores/auth';
import LoadErrorBanner from 'src/components/LoadErrorBanner.vue';
import LicenseDialog from './LicenseDialog.vue';
import LicensesAttentionCard from './LicensesAttentionCard.vue';
import LicensesCard from './LicensesCard.vue';

const Stub = defineComponent({ render: () => h('div') });

function router() {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', component: Stub },
      { path: '/machines', name: 'machines', component: Stub },
      { path: '/software', name: 'software', component: Stub },
    ],
  });
}

function license(fields: Partial<License> = {}): License {
  return {
    id: '0b1c2d3e-4f50-4617-8899-aabbccddeeff',
    name: 'Office 2021',
    patterns: ['Microsoft Office'],
    publisher: null,
    seats: 30,
    expires_on: null,
    vendor: 'UGAP',
    reference: 'CMD-118',
    notes: null,
    installed: 32,
    over: true,
    expiry: 'none',
    created_at: '2026-11-24T00:00:00Z',
    updated_at: '2026-11-24T00:00:00Z',
    ...fields,
  };
}

function grant(permissions: string[]) {
  useAuthStore().user = { id: 'u', email: 'a@b.c', permissions } as never;
}

async function mountIt(component: Component) {
  const r = router();
  await r.push('/');
  const w = mount(component, { global: { plugins: [r] } });
  await flushPromises();
  return w;
}

describe('LicensesCard', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.mocked(listLicenses).mockReset();
    vi.mocked(createLicense).mockReset();
    vi.mocked(previewLicense).mockReset();
  });

  it('shows installations against seats, the count opening its postes', async () => {
    grant(['license:read', 'license:write', 'machine:read']);
    vi.mocked(listLicenses).mockResolvedValue({
      items: [license()],
      restricted: false,
      expiry_days: 60,
    });
    const w = await mountIt(LicensesCard);
    expect(w.text()).toContain('Office 2021');
    expect(w.text()).toContain('UGAP · CMD-118');
    expect(w.text()).toContain('32 pour 30');
    expect(w.text()).toContain('Dépassée');
    expect(w.text()).toContain('Sans échéance');
    // The list it opens leaves the retired postes out, as the count does.
    const link = w.find('a[href*="license_id"]');
    expect(link.attributes('href')).toBe(
      '/machines?license_id=0b1c2d3e-4f50-4617-8899-aabbccddeeff&in_parc=true',
    );
    expect(w.find('[data-test="license-add"]').exists()).toBe(true);
  });

  it('offers no writing to a reader limited to some places', async () => {
    grant(['license:read', 'license:write']);
    vi.mocked(listLicenses).mockResolvedValue({
      items: [
        license({
          over: null,
          installed: 3,
          seats: null,
          expiry: 'soon',
          expires_on: '2027-01-10',
        }),
      ],
      restricted: true,
      expiry_days: 60,
    });
    const w = await mountIt(LicensesCard);
    expect(w.find('[data-test="licenses-restricted"]').exists()).toBe(true);
    expect(w.find('[data-test="license-add"]').exists()).toBe(false);
    expect(w.text()).toContain('3 (sans limite)');
    expect(w.text()).toContain('10/01/2027');
    expect(w.text()).toContain('Bientôt échue');
    expect(w.text()).not.toContain('Dépassée');
    // Without machine:read, the count is text, not a link.
    expect(w.find('a[href*="license_id"]').exists()).toBe(false);
  });
});

describe('LicenseDialog', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.mocked(createLicense).mockReset();
    vi.mocked(previewLicense).mockReset();
    vi.useRealTimers();
  });

  it('refuses a licence without a program, and previews what patterns catch', async () => {
    grant(['license:write', 'machine:read']);
    vi.mocked(previewLicense).mockResolvedValue({
      programs: ['Microsoft Office LTSC'],
      installed: 4,
    });
    vi.mocked(createLicense).mockResolvedValue(license());
    document.body.innerHTML = '';
    const w = mount(LicenseDialog, {
      props: { modelValue: false, license: null },
      attachTo: document.body,
    });
    await w.setProps({ modelValue: true });
    await flushPromises();
    const input = (label: string) =>
      w.findAllComponents(QInput).find((i) => i.props('label') === label)!;
    const submit = async () => {
      await w.findComponent(QForm).trigger('submit');
      await flushPromises();
    };

    input('Nom').vm.$emit('update:modelValue', 'Office');
    await submit();
    expect(createLicense).not.toHaveBeenCalled();
    expect(document.body.textContent).toContain('Au moins un logiciel couvert');

    const select = w.findComponent(QSelect);
    // One character is not a pattern; two are.
    const added: (string | undefined)[] = [];
    select.vm.$emit('new-value', 'M', (item?: string) => added.push(item));
    expect(added).toEqual([undefined]);
    select.vm.$emit('update:modelValue', ['Microsoft Office']);
    await new Promise((resolve) => setTimeout(resolve, 350));
    await flushPromises();
    expect(previewLicense).toHaveBeenCalledWith(['Microsoft Office'], null);
    expect(document.body.textContent).toContain('Installés sur 4 poste(s).');

    input('Nombre de postes').vm.$emit('update:modelValue', '30');
    await submit();
    expect(createLicense).toHaveBeenCalledWith({
      name: 'Office',
      patterns: ['Microsoft Office'],
      publisher: null,
      seats: 30,
      expires_on: null,
      vendor: null,
      reference: null,
      notes: null,
    });
    w.unmount();
  });
});

describe('LicensesAttentionCard', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.mocked(listLicenses).mockReset();
  });

  it('lists only the licences to look at, and nothing when none is', async () => {
    vi.mocked(listLicenses).mockResolvedValue({
      items: [
        license(),
        license({
          id: 'b',
          name: 'Antidote',
          over: false,
          expiry: 'expired',
          expires_on: '2026-10-01',
        }),
        license({ id: 'c', name: 'Calm', over: false }),
      ],
      restricted: false,
      expiry_days: 45,
    });
    let w = await mountIt(LicensesAttentionCard);
    expect(w.text()).toContain('Office 2021');
    expect(w.text()).toContain('Antidote');
    expect(w.text()).toContain('Échue');
    expect(w.text()).toContain('sous 45 jours');
    expect(w.text()).not.toContain('Calm');

    vi.mocked(listLicenses).mockResolvedValue({
      items: [license({ over: false })],
      restricted: false,
      expiry_days: 60,
    });
    w = await mountIt(LicensesAttentionCard);
    expect(w.find('[data-test="licenses-attention"]').exists()).toBe(false);
  });
});

describe('LicensesCard — edit, delete, errors', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    document.body.innerHTML = '';
    vi.mocked(listLicenses).mockReset();
    vi.mocked(deleteLicense).mockReset();
  });

  it('opens the dialog filled for an edit, and deletes once confirmed', async () => {
    grant(['license:read', 'license:write', 'machine:read']);
    vi.mocked(listLicenses).mockResolvedValue({
      items: [license()],
      restricted: false,
      expiry_days: 60,
    });
    vi.mocked(deleteLicense).mockResolvedValue();
    const r = router();
    await r.push('/');
    const w = mount(LicensesCard, { global: { plugins: [r] }, attachTo: document.body });
    await flushPromises();

    await w.find('[aria-label="Modifier"]').trigger('click');
    await flushPromises();
    const dialog = w.findComponent(LicenseDialog);
    expect(dialog.props('modelValue')).toBe(true);
    expect(dialog.props('license')?.name).toBe('Office 2021');

    await w.find('[aria-label="Supprimer"]').trigger('click');
    await flushPromises();
    expect(document.body.textContent).toContain('Supprimer la licence « Office 2021 »');
    const ok = [...document.querySelectorAll('.q-dialog button')].find((b) =>
      b.textContent?.includes('Supprimer'),
    ) as HTMLButtonElement;
    ok.click();
    await flushPromises();
    expect(deleteLicense).toHaveBeenCalledWith('0b1c2d3e-4f50-4617-8899-aabbccddeeff');
    expect(listLicenses).toHaveBeenCalledTimes(2);
    w.unmount();
  });

  it('shows the error banner when the licences cannot be read', async () => {
    grant(['license:read']);
    vi.mocked(listLicenses).mockRejectedValue(new Error('down'));
    const w = await mountIt(LicensesCard);
    expect(w.findComponent(LoadErrorBanner).exists()).toBe(true);
  });
});

describe('LicenseDialog — what the reader meant', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    document.body.innerHTML = '';
    vi.mocked(createLicense).mockReset();
    vi.mocked(updateLicense).mockReset();
    vi.mocked(previewLicense).mockReset();
  });

  async function openDialog(lic: License | null) {
    const w = mount(LicenseDialog, {
      props: { modelValue: false, license: lic },
      attachTo: document.body,
    });
    await w.setProps({ modelValue: true });
    await flushPromises();
    const input = (label: string) =>
      w.findAllComponents(QInput).find((i) => i.props('label') === label)!;
    const submit = async () => {
      await w.findComponent(QForm).trigger('submit');
      await flushPromises();
    };
    return { w, input, submit, select: w.findComponent(QSelect) };
  }

  it('takes a pattern typed without Enter, and edits with what was there', async () => {
    vi.mocked(updateLicense).mockResolvedValue(license());
    const { w, select, submit } = await openDialog(license({ seats: null }));
    expect(select.props('modelValue')).toEqual(['Microsoft Office']);
    select.vm.$emit('input-value', ' Visio ');
    await submit();
    expect(updateLicense).toHaveBeenCalledWith(
      '0b1c2d3e-4f50-4617-8899-aabbccddeeff',
      expect.objectContaining({
        name: 'Office 2021',
        patterns: ['Microsoft Office', 'Visio'],
        seats: null,
        vendor: 'UGAP',
      }),
    );
    w.unmount();
  });

  it('refuses a number of postes that is not a whole number, and a pattern too long', async () => {
    const { w, input, select, submit } = await openDialog(null);
    input('Nom').vm.$emit('update:modelValue', 'X');
    select.vm.$emit('update:modelValue', ['Office']);
    for (const bad of ['3.5', '-1', '2000000']) {
      input('Nombre de postes').vm.$emit('update:modelValue', bad);
      await submit();
    }
    expect(createLicense).not.toHaveBeenCalled();
    expect(document.body.textContent).toContain('Un nombre entier de 0 à 1 000 000, ou vide');

    input('Nombre de postes').vm.$emit('update:modelValue', '');
    select.vm.$emit('input-value', 'x'.repeat(101));
    await submit();
    expect(createLicense).not.toHaveBeenCalled();
    expect(document.body.textContent).toContain('Cent caractères au plus');
    w.unmount();
  });

  it('does not ask the catalogue for an account that does not read the postes', async () => {
    grant(['license:read', 'license:write']);
    const { w, select } = await openDialog(null);
    select.vm.$emit('update:modelValue', ['Office']);
    await new Promise((resolve) => setTimeout(resolve, 350));
    await flushPromises();
    expect(previewLicense).not.toHaveBeenCalled();
    w.unmount();
  });
});

import { flushPromises, mount } from '@vue/test-utils';
import { QBtn, QChip, QInput, QSelect, QToggle } from 'quasar';
import { describe, expect, it, vi } from 'vitest';

// The software chip names its program from the server; offline by default,
// as the rest of these tests expect.
vi.mock('src/services/software', async (importOriginal) => ({
  ...(await importOriginal<typeof import('src/services/software')>()),
  getSoftware: vi.fn(() => Promise.reject(new Error('offline'))),
}));

import { getSoftware, type SoftwareRef } from 'src/services/software';
import MachinesFiltersBar from './MachinesFiltersBar.vue';
import {
  STATUS_OPTIONS,
  emptyMachineFilters,
  initialFleetOptions,
  type MachineFilters,
} from 'src/utils/machineListFilters';

/**
 * The bar holds no filter of its own: every widget change comes out as a whole
 * new set of filters, which the page writes into the URL. These tests drive
 * the real Quasar widgets and read what the bar emits.
 */

function mountBar(filters: Partial<MachineFilters> = {}) {
  const options = initialFleetOptions();
  options.antivirus.push({ label: 'ESET (12)', value: 'ESET' });
  return mount(MachinesFiltersBar, {
    props: {
      modelValue: { ...emptyMachineFilters(), ...filters },
      options,
      usageThresholds: { low: 10, high: 50 },
      usageWindowDays: 7,
    },
  });
}

function emitted(wrapper: ReturnType<typeof mountBar>): MachineFilters[] {
  return (wrapper.emitted('update:modelValue') ?? []).map((args) => args[0] as MachineFilters);
}

function filtersButton(wrapper: ReturnType<typeof mountBar>) {
  return wrapper.findAllComponents(QBtn).find((b) => b.props('label') === 'Filtres')!;
}

describe('MachinesFiltersBar', () => {
  it('emits the filters with the one a dropdown changed, the others kept', async () => {
    const wrapper = mountBar({ search: 'pc-12', onlineOnly: true });
    await filtersButton(wrapper).trigger('click');

    const status = wrapper
      .findAllComponents(QSelect)
      .find((s) => s.props('options') === STATUS_OPTIONS)!;
    status.vm.$emit('update:modelValue', 'outdated');

    expect(emitted(wrapper)).toEqual([
      { ...emptyMachineFilters(), search: 'pc-12', onlineOnly: true, status: 'outdated' },
    ]);
  });

  it('emits a toggle as a boolean on its own field', async () => {
    const wrapper = mountBar();
    const threats = wrapper
      .findAllComponents(QToggle)
      .find((t) => t.props('label') === 'Menaces actives')!;

    await threats.trigger('click');

    expect(emitted(wrapper)).toEqual([{ ...emptyMachineFilters(), threatsOnly: true }]);
  });

  it('reads a cleared search as an empty string, never null', () => {
    const wrapper = mountBar({ search: 'pc-12' });
    const search = wrapper.findAllComponents(QInput)[0]!;

    search.vm.$emit('update:modelValue', null);

    expect(emitted(wrapper)[0]!.search).toBe('');
  });

  it('names the folded filters in chips labelled like their dropdown entry', () => {
    const wrapper = mountBar({ antivirus: 'ESET', ramOp: 'min', ramGb: 16 });

    // The content only: the remove button's icon is a ligature, « cancel ».
    const labels = wrapper.findAllComponents(QChip).map((c) => c.find('.q-chip__content').text());

    expect(labels).toEqual(['ESET (12)', 'Mémoire ≥ 16 Gio']);
  });

  it('clears one facet when its chip is removed, the rest untouched', () => {
    const wrapper = mountBar({ antivirus: 'ESET', ramOp: 'min', ramGb: 16 });
    const ram = wrapper.findAllComponents(QChip).find((c) => c.text().includes('Mémoire'))!;

    ram.vm.$emit('remove');

    expect(emitted(wrapper)).toEqual([{ ...emptyMachineFilters(), antivirus: 'ESET' }]);
  });

  it('trades the chips for the panel when unfolded, its count on the badge otherwise', async () => {
    const wrapper = mountBar({ antivirus: 'ESET' });
    expect(filtersButton(wrapper).text()).toContain('1');

    await filtersButton(wrapper).trigger('click');

    expect(wrapper.findAllComponents(QChip)).toHaveLength(0);
    expect(wrapper.text()).toContain('1 filtre(s) actif(s)');
  });

  it('« Tout effacer » goes back to the whole parc, search and toggles included', async () => {
    const wrapper = mountBar({ search: 'pc', threatsOnly: true, antivirus: 'ESET' });
    await filtersButton(wrapper).trigger('click');

    const clearAll = wrapper
      .findAllComponents(QBtn)
      .find((b) => b.props('label') === 'Tout effacer')!;
    await clearAll.trigger('click');

    expect(emitted(wrapper)).toEqual([emptyMachineFilters()]);
  });

  describe('usage', () => {
    function usageSelect(wrapper: ReturnType<typeof mountBar>) {
      return wrapper
        .findAllComponents(QSelect)
        .find((s) =>
          (s.props('options') as { label: string }[]).some((o) => o.label === 'Personnalisé…'),
        )!;
    }

    it('writes a preset as its two bounds', async () => {
      const wrapper = mountBar();
      await filtersButton(wrapper).trigger('click');

      usageSelect(wrapper).vm.$emit('update:modelValue', 'mid');

      expect(emitted(wrapper)).toEqual([
        { ...emptyMachineFilters(), usageBelow: 50, usageAbove: 10 },
      ]);
    });

    it('opens the two bounds on « Personnalisé » without emitting anything yet', async () => {
      const wrapper = mountBar();
      await filtersButton(wrapper).trigger('click');
      const inputsBefore = wrapper.findAllComponents(QInput).length;

      usageSelect(wrapper).vm.$emit('update:modelValue', 'custom');
      await wrapper.vm.$nextTick();

      expect(emitted(wrapper)).toEqual([]);
      expect(wrapper.findAllComponents(QInput)).toHaveLength(inputsBefore + 2);
    });

    it('drops the window with the bounds on « toutes »', async () => {
      const wrapper = mountBar({ usageBelow: 10, usageDays: 30 });
      await filtersButton(wrapper).trigger('click');

      usageSelect(wrapper).vm.$emit('update:modelValue', null);

      expect(emitted(wrapper)).toEqual([emptyMachineFilters()]);
    });
  });

  describe('software', () => {
    const chipLabels = (wrapper: ReturnType<typeof mountBar>) =>
      wrapper.findAllComponents(QChip).map((c) => c.find('.q-chip__content').text());

    it('names the program on the chip', async () => {
      vi.mocked(getSoftware).mockResolvedValueOnce({
        id: 7,
        name: '7-Zip',
        version: '23.01',
      } as SoftwareRef);
      const wrapper = mountBar({ softwareId: 7 });
      await flushPromises();

      expect(chipLabels(wrapper)).toContain('Logiciel : 7-Zip 23.01');
    });

    // Audit T42: the answer for a program left behind must not name the next one.
    it('ignores the name of a program no longer filtered on', async () => {
      const pending: Record<number, (s: SoftwareRef) => void> = {};
      vi.mocked(getSoftware).mockImplementation(
        (id) => new Promise((resolve) => (pending[id] = resolve)),
      );
      const wrapper = mountBar({ softwareId: 7 });
      await wrapper.setProps({ modelValue: { ...emptyMachineFilters(), softwareId: 8 } });
      pending[8]!({ id: 8, name: 'Firefox', version: '140' } as SoftwareRef);
      await flushPromises();
      pending[7]!({ id: 7, name: '7-Zip', version: '23.01' } as SoftwareRef);
      await flushPromises();

      expect(chipLabels(wrapper)).toContain('Logiciel : Firefox 140');
      expect(chipLabels(wrapper).join(' ')).not.toContain('7-Zip');
    });
  });
});

describe('MachinesFiltersBar — every filter the URL carries has a chip (item 8)', () => {
  it('names a hand-typed domain and clears everything from the folded bar', async () => {
    const w = mountBar({ domain: 'CORP' });
    expect(w.findAllComponents(QChip).map((c) => c.find('.q-chip__content').text())).toContain(
      'Domaine : CORP',
    );
    const clearAll = w.findAllComponents(QBtn).find((b) => b.text().includes('Tout effacer'))!;
    await clearAll.trigger('click');
    expect(emitted(w).at(-1)).toEqual(emptyMachineFilters());
  });

  it('trims the search when the box is left', async () => {
    const w = mountBar({ search: ' PC-01  ' });
    w.findComponent(QInput).vm.$emit('blur');
    await flushPromises();
    expect(emitted(w).at(-1)!.search).toBe('PC-01');
  });

  // Review, « partial filter values »: `?hw_model=OptiPlex` typed by hand.
  describe('a value matched exactly that the parc does not hold', () => {
    function mountWith(listEmpty: boolean, model = 'OptiPlex') {
      const options = initialFleetOptions();
      options.model.push({ label: 'OptiPlex 7010 (20)', value: 'OptiPlex 7010' });
      return mount(MachinesFiltersBar, {
        props: {
          modelValue: { ...emptyMachineFilters(), model },
          options,
          usageThresholds: { low: 10, high: 50 },
          usageWindowDays: 7,
          listEmpty,
        },
      });
    }

    it('says why the list is empty, next to the chip', () => {
      const wrapper = mountWith(true);
      expect(wrapper.findAllComponents(QChip).map((c) => c.text())).toEqual(['OptiPlexcancel']);
      const hint = wrapper.find('[data-test="unmatched-filters"]');
      expect(hint.text()).toContain('Modèle « OptiPlex »');
      expect(hint.text()).toContain('valeur exacte — aucune correspondance dans le parc');
    });

    it('keeps saying it with the panel open, where the chips are folded away', async () => {
      const wrapper = mountWith(true);
      await filtersButton(wrapper).trigger('click');
      expect(wrapper.find('[data-test="unmatched-filters"]').text()).toContain(
        'Modèle « OptiPlex »',
      );
    });

    it('says nothing for a value of the parc, nor over a list that has rows', () => {
      expect(
        mountWith(true, 'OptiPlex 7010').find('[data-test="unmatched-filters"]').exists(),
      ).toBe(false);
      expect(mountWith(false).find('[data-test="unmatched-filters"]').exists()).toBe(false);
    });
  });
});

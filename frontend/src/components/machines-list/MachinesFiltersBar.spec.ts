import { mount } from '@vue/test-utils';
import { QBtn, QChip, QInput, QSelect, QToggle } from 'quasar';
import { describe, expect, it } from 'vitest';
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
});

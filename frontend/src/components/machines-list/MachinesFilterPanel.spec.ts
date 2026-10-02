import { mount } from '@vue/test-utils';
import { QInput, QSelect } from 'quasar';
import { describe, expect, it } from 'vitest';
import MachinesFilterPanel from './MachinesFilterPanel.vue';
import {
  CHECK_OPTIONS,
  DISK_OPTIONS,
  MAINTENANCE_OPTIONS,
  MISMATCH_OPTIONS,
  RAM_OP_OPTIONS,
  SCAN_OPTIONS,
  STATUS_OPTIONS,
  WU_OPTIONS,
  emptyMachineFilters,
  initialFleetOptions,
  type MachineFilters,
} from 'src/utils/machineListFilters';
import type { UsageThresholds } from 'src/utils/usageFilter';

function mountPanel(
  filters: Partial<MachineFilters> = {},
  extra: { usageCustom?: boolean; usageThresholds?: UsageThresholds | null } = {},
) {
  return mount(MachinesFilterPanel, {
    props: {
      modelValue: { ...emptyMachineFilters(), ...filters },
      options: initialFleetOptions(),
      usageThresholds:
        'usageThresholds' in extra ? (extra.usageThresholds ?? null) : { low: 10, high: 50 },
      usageWindowDays: 7,
      activeCount: 0,
      usageCustom: extra.usageCustom ?? false,
    },
  });
}

function emitted(wrapper: ReturnType<typeof mountPanel>): MachineFilters[] {
  return (wrapper.emitted('update:modelValue') ?? []).map((args) => args[0] as MachineFilters);
}

describe('MachinesFilterPanel', () => {
  // Seventeen widgets wired by hand: the one mistake worth guarding against is
  // a dropdown writing into its neighbour's field.
  it('has each dropdown write its own field, and only it', () => {
    const fleet = initialFleetOptions();
    const cases: [unknown[], keyof MachineFilters, unknown][] = [
      [fleet.antivirus, 'antivirus', 'ESET'],
      [STATUS_OPTIONS, 'status', 'outdated'],
      [WU_OPTIONS, 'wu', 'pending'],
      [SCAN_OPTIONS, 'scan', 'full:7'],
      [fleet.location, 'location', 'Papeete'],
      [fleet.building, 'building', 'b-1'],
      [fleet.room, 'room', 'r-1'],
      [MISMATCH_OPTIONS, 'mismatch', 'true'],
      [MAINTENANCE_OPTIONS, 'maintenance', 'overdue'],
      [CHECK_OPTIONS, 'checkOpen', 'true'],
      [fleet.os, 'os', 'Windows 11'],
      [fleet.agent, 'agent', 'outdated'],
      [fleet.manufacturer, 'manufacturer', 'Dell'],
      [fleet.model, 'model', 'OptiPlex'],
      [fleet.processor, 'processor', 'i5'],
      [fleet.chassis, 'chassis', 'laptop'],
      [RAM_OP_OPTIONS, 'ramOp', 'min'],
      [DISK_OPTIONS, 'diskFree', 20],
    ];
    const wrapper = mountPanel();
    const selects = wrapper.findAllComponents(QSelect);

    for (const [options, field, value] of cases) {
      // Matched on the entries rather than the instance: the fleet lists are
      // props, and arrive as copies.
      const select = selects.find(
        (s) => JSON.stringify(s.props('options')) === JSON.stringify(options),
      );
      expect(select, field).toBeDefined();
      select!.vm.$emit('update:modelValue', value);
      expect(emitted(wrapper).at(-1), field).toEqual({ ...emptyMachineFilters(), [field]: value });
    }
  });

  it('takes the memory figure as typed, and only once a bound is picked', () => {
    const ramBox = (w: ReturnType<typeof mountPanel>) =>
      w.findAllComponents(QInput).find((i) => i.props('suffix') === 'Gio')!;

    expect(ramBox(mountPanel()).props('disable')).toBe(true);

    const wrapper = mountPanel({ ramOp: 'min' });
    expect(ramBox(wrapper).props('disable')).toBe(false);
    ramBox(wrapper).vm.$emit('update:modelValue', '16');
    expect(emitted(wrapper)).toEqual([{ ...emptyMachineFilters(), ramOp: 'min', ramGb: '16' }]);
  });

  it('shows the two usage bounds under « Personnalisé », each writing its own', () => {
    const wrapper = mountPanel({ usageAbove: 2 }, { usageCustom: true });
    const box = (prefix: string) =>
      wrapper.findAllComponents(QInput).find((i) => i.props('prefix') === prefix)!;

    box('plus de').vm.$emit('update:modelValue', '4');
    box('moins de').vm.$emit('update:modelValue', '20');

    expect(emitted(wrapper)).toEqual([
      { ...emptyMachineFilters(), usageAbove: '4' },
      { ...emptyMachineFilters(), usageAbove: 2, usageBelow: '20' },
    ]);
  });

  it('reads bounds no preset matches as « Personnalisé »', () => {
    const wrapper = mountPanel({ usageBelow: 3 });
    const usage = wrapper
      .findAllComponents(QSelect)
      .find((s) => s.props('modelValue') === 'custom');
    expect(usage).toBeDefined();
  });

  it('shows the presets but keeps them out of reach until the thresholds are known', () => {
    const wrapper = mountPanel({}, { usageThresholds: null });
    const usage = wrapper
      .findAllComponents(QSelect)
      .find((s) =>
        (s.props('options') as { label: string }[]).some((o) => o.label === 'Personnalisé…'),
      )!;
    const options = usage.props('options') as { label: string; disable?: boolean }[];

    expect(options.filter((o) => o.disable).map((o) => o.label)).toEqual([
      'Peu utilisés',
      'Utilisation moyenne',
      'Toujours allumés',
    ]);

    // Were one picked anyway, it clears the filter rather than guess bounds.
    usage.vm.$emit('update:modelValue', 'low');
    expect(emitted(wrapper)).toEqual([emptyMachineFilters()]);
  });

  it('names the usage window the server answered with', () => {
    expect(mountPanel().text()).toContain('sur 7 jours');
  });
});

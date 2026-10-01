import { mount } from '@vue/test-utils';
import { QIcon, QLinearProgress, QTable } from 'quasar';
import { describe, expect, it } from 'vitest';
import MachinesTable from './MachinesTable.vue';
import type { Machine } from 'src/services/machines';
import { MACHINE_COLUMN_KEYS } from 'src/utils/machineColumns';
import { initialMachinePagination, visibleMachineColumns } from 'src/utils/machineListTable';
import { machineDetail } from 'src/test/fixtures';

function row(overrides: Partial<Machine> = {}): Machine {
  return { ...machineDetail(), ...overrides };
}

function mountTable(rows: Machine[]) {
  return mount(MachinesTable, {
    props: {
      rows,
      columns: visibleMachineColumns([...MACHINE_COLUMN_KEYS], 7),
      loading: false,
      agentLatest: '0.3.0',
      usageWindowDays: 7,
      selected: [],
      pagination: { ...initialMachinePagination(), rowsNumber: rows.length },
    },
  });
}

const iconNames = (wrapper: ReturnType<typeof mountTable>) =>
  wrapper.findAllComponents(QIcon).map((i) => i.props('name') as string);

describe('MachinesTable', () => {
  it('renders one line per poste, a dash where a figure is missing', () => {
    const wrapper = mountTable([
      row({ id: 'a', hostname: 'PC-01', room_name: 'B12' }),
      row({ id: 'b', hostname: null, machine_uuid: 'uuid-b', system_volume_total_mb: null }),
    ]);
    const lines = wrapper.findAll('tbody tr');

    expect(lines).toHaveLength(2);
    expect(lines[0]!.text()).toContain('PC-01');
    expect(lines[0]!.text()).toContain('B12');
    // No hostname reported yet: the UUID names the poste.
    expect(lines[1]!.text()).toContain('uuid-b');
    expect(lines[1]!.findComponent(QLinearProgress).exists()).toBe(false);
    expect(lines[0]!.findComponent(QLinearProgress).props('value')).toBe(0.5);
  });

  it('marks what needs a look: a check, a doubtful identity, a site, an old agent, a restart', () => {
    const quiet = iconNames(mountTable([row()]));
    for (const name of [
      'fact_check',
      'warning',
      'wrong_location',
      'system_update_alt',
      'restart_alt',
    ]) {
      expect(quiet).not.toContain(name);
    }

    const loud = iconNames(
      mountTable([
        row({
          check_open: true,
          needs_verification: true,
          location_mismatch: true,
          agent_version: '0.2.0',
          wu_reboot_required: true,
        }),
      ]),
    );
    expect(loud).toEqual(
      expect.arrayContaining([
        'fact_check',
        'warning',
        'wrong_location',
        'system_update_alt',
        'restart_alt',
      ]),
    );
  });

  it('reads a poste too new for the usage window as « récent »', () => {
    const wrapper = mountTable([row({ usage_hours: null })]);
    expect(wrapper.find('tbody tr').text()).toContain('récent');
    expect(wrapper.find('thead').text()).toContain('Allumé (7 j)');
  });

  it('opens a poste with its index on the page', async () => {
    const second = row({ id: 'b', hostname: 'PC-02' });
    const wrapper = mountTable([row({ id: 'a' }), second]);

    await wrapper.findAll('tbody tr')[1]!.trigger('click');

    expect(wrapper.emitted('open')).toEqual([[second, 1]]);
  });

  it('hands every sort to the page as a server request', () => {
    const wrapper = mountTable([row()]);
    const request = { pagination: { sortBy: 'hostname', descending: false, page: 1 } };

    wrapper.findComponent(QTable).vm.$emit('request', request);

    expect(wrapper.emitted('request')).toEqual([[request]]);
  });
});

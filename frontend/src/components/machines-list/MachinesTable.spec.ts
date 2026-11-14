import { mount } from '@vue/test-utils';
import { QBadge, QIcon, QLinearProgress, QTable } from 'quasar';
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

  // Audit U28: the column took its colour from Defender's state alone, so a
  // poste with no Security Center product read « Non relevé » in green.
  it('colours the antivirus badge as the fiche does, never green without a product', () => {
    const badge = (overrides: Partial<Machine>) =>
      mountTable([row(overrides)])
        .findAllComponents(QBadge)
        .find((b) => /Non relevé|Aucun|Windows Defender/.test(b.text()))!;

    expect(badge({ av_product_name: null, is_up_to_date: true }).props('color')).toBe('grey-6');
    expect(badge({ av_product_name: '', is_up_to_date: true }).props('color')).toBe('negative');
    expect(badge({ is_up_to_date: true }).props('color')).toBe('positive');
    expect(badge({ is_up_to_date: false }).props('color')).toBe('negative');
  });

  // Audit U25: the sticky name cell is capped at 260 px; only the name is cut,
  // the icons after it stay outside the ellipsis.
  it('cuts a long name, not the icons after it', () => {
    const wrapper = mountTable([
      row({ hostname: 'X'.repeat(80), check_open: true, needs_verification: true }),
    ]);
    const cell = wrapper.find('.machine-name');

    expect(cell.find('.machine-name__text').text()).toBe('X'.repeat(80));
    expect(cell.find('.machine-name__text').attributes('title')).toBe('X'.repeat(80));
    // Material icons render their name as the element's text.
    const icons = cell.findAll('.q-icon').map((i) => i.text());
    expect(icons).toEqual(expect.arrayContaining(['fact_check', 'warning']));
    // Siblings of the name, not inside it.
    expect(cell.find('.machine-name__text .q-icon').exists()).toBe(false);
  });
});

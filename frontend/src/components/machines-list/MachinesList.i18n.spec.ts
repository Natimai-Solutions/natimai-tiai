import { flushPromises, mount } from '@vue/test-utils';
import { QBtn, QIcon, QSelect, QTooltip } from 'quasar';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { nextTick } from 'vue';
import { setLocale } from 'src/i18n';
import MachineColumnsDialog from 'src/components/machine/MachineColumnsDialog.vue';
import type { Machine } from 'src/services/machines';
import type { Room } from 'src/services/rooms';
import { machineDetail } from 'src/test/fixtures';
import { DEFAULT_MACHINE_COLUMNS, type MachineColumnKey } from 'src/utils/machineColumns';
import {
  emptyMachineFilters,
  initialFleetOptions,
  type MachineFilters,
} from 'src/utils/machineListFilters';
import {
  MACHINE_COLUMN_LABELS,
  initialMachinePagination,
  visibleMachineColumns,
} from 'src/utils/machineListTable';
import MachinePlaceDialog from './MachinePlaceDialog.vue';
import MachinesBulkBar from './MachinesBulkBar.vue';
import MachinesFiltersBar from './MachinesFiltersBar.vue';
import MachinesTable from './MachinesTable.vue';
import MachinesToolbar from './MachinesToolbar.vue';

/**
 * The machine list's pieces in English (plan `dev/plan-console-bilingue.md`,
 * I6). Their French is what their own specs assert; here, the English reader
 * must find no French word of the list's own — and a change of language,
 * made while the list is open, must reach every text.
 */

// Accented letters and French quotes: the data mounted here has none.
const FRENCH = /[éèàùçêô«»]/;

afterEach(() => setLocale('fr'));

/** The text of a tooltip, shown: it renders in a portal on the body. */
async function tooltipText(tooltip: { vm: unknown }) {
  (tooltip.vm as { show: () => void }).show();
  await flushPromises();
  await vi.waitFor(() => expect(document.body.querySelector('.q-tooltip')).not.toBeNull());
  const text = document.body.querySelector('.q-tooltip')!.textContent.replace(/\s+/g, ' ').trim();
  (tooltip.vm as { hide: () => void }).hide();
  return text;
}

describe('MachinesToolbar in English', () => {
  it('names its buttons in English and switches live', async () => {
    const wrapper = mount(MachinesToolbar, {
      props: { loading: false, lastRefreshedAt: new Date(2026, 10, 18, 14, 5, 9) },
    });
    expect(wrapper.text()).toContain('Postes');
    setLocale('en');
    await nextTick();
    const text = wrapper.text();
    expect(text).toContain('Computers');
    expect(text).toContain('Refreshed at 14:05:09');
    expect(text).not.toMatch(FRENCH);
    const buttons = wrapper.findAllComponents(QBtn);
    expect(buttons.map((b) => b.props('label'))).toEqual(
      expect.arrayContaining(['Columns', 'Export']),
    );
    expect(buttons.some((b) => b.attributes('aria-label') === 'Refresh')).toBe(true);
  });
});

describe('MachinesBulkBar in English', () => {
  it('names its actions in English', () => {
    setLocale('en');
    const wrapper = mount(MachinesBulkBar, {
      props: {
        count: 3,
        canPlace: true,
        canCheck: true,
        canDeploy: true,
        canReenroll: true,
        actionGroups: [],
      },
    });
    expect(wrapper.text()).toContain('3 selected');
    expect(wrapper.findAllComponents(QBtn).map((b) => b.props('label'))).toEqual([
      'Assign to a room',
      'Request a check',
      'Install software',
      'Allow re-enrolment',
    ]);
    expect(wrapper.text()).not.toMatch(FRENCH);
  });
});

describe('MachinePlaceDialog in English', () => {
  it('words the dialog in English, the count as a plural', async () => {
    setLocale('en');
    const rooms = [{ id: 'r-2', name: 'Workshop', building: null }] as unknown as Room[];
    const wrapper = mount(MachinePlaceDialog, {
      props: { modelValue: false, count: 1, rooms, save: vi.fn() },
      attachTo: document.body,
    });
    await wrapper.setProps({ modelValue: true });
    await flushPromises();
    const options = wrapper.findComponent(QSelect).props('options') as { label: string }[];
    expect(options.map((o) => o.label)).toEqual(['No room (remove from its room)', 'Workshop']);
    const body = document.body.textContent;
    expect(body).toContain('Assign to a room');
    expect(body).toContain('1 computer selected');
    expect(wrapper.findAllComponents(QBtn).map((b) => b.props('label'))).toEqual([
      'Cancel',
      'Assign',
    ]);
    wrapper.unmount();
  });
});

describe('MachinesFiltersBar in English', () => {
  function mountBar(filters: Partial<MachineFilters> = {}, listEmpty = false) {
    const options = initialFleetOptions();
    options.antivirus.push({ label: 'ESET (12)', value: 'ESET' });
    options.model.push({ label: 'OptiPlex 7010 (3)', value: 'OptiPlex 7010' });
    return mount(MachinesFiltersBar, {
      props: {
        modelValue: { ...emptyMachineFilters(), ...filters },
        options,
        usageThresholds: { low: 10, high: 50 },
        usageWindowDays: 7,
        listEmpty,
      },
    });
  }

  it('words the bar, the folded panel and the chips in English', async () => {
    setLocale('en');
    const wrapper = mountBar({ ramOp: 'min', ramGb: 16, status: 'outdated' });
    await flushPromises();
    const text = wrapper.text();
    for (const expected of [
      'Switched on',
      'Active threats',
      'Filters',
      'Antivirus outdated',
      'Memory ≥ 16 GiB',
      'Clear all',
      // The folded panel, rendered while hidden.
      '2 active filters',
      'Security',
      'Hardware',
      'over 7 days',
    ]) {
      expect(text).toContain(expected);
    }
    expect(text).not.toMatch(FRENCH);
    expect(wrapper.html()).toContain('aria-label="Search for a computer"');
    expect(wrapper.html()).toContain('placeholder="Name, IP, MAC, antivirus or UUID…"');
    const usage = wrapper
      .findAllComponents(QSelect)
      .find((s) => (s.props('options') as { value: unknown }[]).some((o) => o.value === 'custom'))!;
    expect((usage.props('options') as { label: string }[]).map((o) => o.label)).toEqual([
      'Usage: all',
      'Rarely used (under 10 h)',
      'Between 10 and 50 h',
      'Always on (over 50 h)',
      'Custom…',
    ]);
  });

  it('says in English that an exact value matches nothing', async () => {
    setLocale('en');
    const wrapper = mountBar({ model: 'OptiPlex' }, true);
    await flushPromises();
    expect(wrapper.find('[data-test="unmatched-filters"]').text()).toContain(
      'Model “OptiPlex”: exact value — nothing in the fleet matches.',
    );
  });

  it('follows a change of language while open', async () => {
    const wrapper = mountBar({ status: 'outdated' });
    await flushPromises();
    expect(wrapper.text()).toContain('Antivirus périmé');
    setLocale('en');
    await nextTick();
    expect(wrapper.text()).toContain('Antivirus outdated');
    expect(wrapper.text()).not.toContain('Antivirus périmé');
  });
});

describe('MachinesTable in English', () => {
  // The columns whose cells the list words itself: the badges of the others
  // (antivirus, updates, session, maintenance) are the formatting helpers'.
  const columns: MachineColumnKey[] = [
    'hostname',
    'domain',
    'location',
    'room',
    'ip_address',
    'agent',
    'usage',
    'model',
    'disk',
  ];

  function mountTable(rows: Machine[]) {
    return mount(MachinesTable, {
      props: {
        rows,
        columns: visibleMachineColumns(columns, 7),
        loading: false,
        agentLatest: '0.3.0',
        usageWindowDays: 7,
        selected: [],
        pagination: { ...initialMachinePagination(), rowsNumber: rows.length },
      },
      attachTo: document.body,
    });
  }

  it('heads its columns and words its cells in English', () => {
    setLocale('en');
    const wrapper = mountTable([
      { ...machineDetail(), id: 'a', hostname: 'PC-01', room_name: 'B12', usage_hours: null },
    ]);
    expect(wrapper.find('thead').text()).toContain('Agent version');
    expect(wrapper.find('thead').text()).toContain('Hours on (7 d)');
    const body = wrapper.find('tbody').text();
    expect(body).toContain('recent');
    expect(body).toMatch(/free/);
    expect(wrapper.find('thead').text() + body).not.toMatch(FRENCH);
    wrapper.unmount();
  });

  it('writes its tooltips in English', async () => {
    setLocale('en');
    const wrapper = mountTable([
      {
        ...machineDetail(),
        id: 'a',
        hostname: 'PC-01',
        room_name: 'B12',
        location: 'Papeete',
        room_location: 'Taravao',
        location_mismatch: true,
        check_open: true,
        check_assigned_to: 'Alice',
        agent_version: '0.2.0',
      },
    ]);
    const tooltipOf = (icon: string) =>
      wrapper
        .findAllComponents(QIcon)
        .find((i) => i.props('name') === icon)!
        .findComponent(QTooltip);
    expect(await tooltipText(tooltipOf('wrong_location'))).toBe(
      'Location differs: the agent declares “Papeete”, the room is in “Taravao”',
    );
    await flushPromises();
    expect(await tooltipText(tooltipOf('fact_check'))).toBe('Check requested, assigned to Alice');
    wrapper.unmount();
  });
});

describe('MachineColumnsDialog in English', () => {
  it('lists the columns in English, and follows a change of language', async () => {
    const wrapper = mount(MachineColumnsDialog, {
      props: {
        open: false,
        columns: [...DEFAULT_MACHINE_COLUMNS],
        labels: MACHINE_COLUMN_LABELS,
        save: vi.fn(),
      },
      attachTo: document.body,
    });
    await wrapper.setProps({ open: true });
    await flushPromises();
    expect(document.body.textContent).toContain('Vu le');
    setLocale('en');
    await nextTick();
    const body = document.body.textContent;
    expect(body).toContain('List columns');
    expect(body).toContain('Last seen');
    expect(body).toContain('Hours on');
    expect(wrapper.findAllComponents(QBtn).map((b) => b.props('label'))).toEqual(
      expect.arrayContaining(['Default', 'Cancel', 'Apply']),
    );
    expect(document.body.querySelector('.q-dialog')!.textContent).not.toMatch(FRENCH);
    wrapper.unmount();
  });
});

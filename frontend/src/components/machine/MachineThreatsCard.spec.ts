import { mount } from '@vue/test-utils';
import { QBtn } from 'quasar';
import { describe, expect, it } from 'vitest';
import MachineThreatsCard from './MachineThreatsCard.vue';
import type { TablePagination } from './types';
import type { Threat } from 'src/services/threats';

function threat(overrides: Partial<Threat> = {}): Threat {
  return {
    id: 1,
    machine_id: 'm1',
    detection_id: null,
    threat_name: 'Trojan:Win32/Wacatac',
    severity: 'severe',
    category: null,
    status: 'quarantined',
    action_taken: null,
    detected_at: '2026-09-04T10:00:00Z',
    ...overrides,
  };
}

function mountCard(threats: Threat[], pagination: Partial<TablePagination> = {}) {
  return mount(MachineThreatsCard, {
    props: {
      threats,
      loading: false,
      pagination: { page: 1, rowsPerPage: 10, rowsNumber: threats.length, ...pagination },
    },
  });
}

describe('MachineThreatsCard', () => {
  it('renders a threat with its severity and status in words', () => {
    const text = mountCard([threat()]).text();

    expect(text).toContain('Trojan:Win32/Wacatac');
    expect(text).toContain('Grave');
    expect(text).toContain('En quarantaine');
  });

  it('says there is none rather than showing an empty table', () => {
    expect(mountCard([]).text()).toContain('Aucune menace détectée.');
  });

  // The language pack at work: the table's own words are Quasar's, and the
  // app installs them in French (quasar.config.ts, `framework.lang`).
  it('speaks French in the table’s own labels', () => {
    const text = mountCard([threat()], { rowsNumber: 25 }).text();

    expect(text).toContain('Lignes par page');
    expect(text).toContain('1-10 sur 25');
    expect(text).not.toContain('Records per page');
  });

  it('turns the page server-side: new pagination, then a refresh for the page to fetch', async () => {
    const wrapper = mountCard([threat()], { rowsNumber: 25 });
    const next = wrapper
      .findAllComponents(QBtn)
      .find((b) => b.attributes('aria-label') === 'Page suivante')!;

    await next.trigger('click');

    // QTable first completes the pagination it was given (sort fields); the
    // page turn is the last word.
    expect(wrapper.emitted('update:pagination')!.at(-1)).toEqual([
      expect.objectContaining({ page: 2, rowsPerPage: 10, rowsNumber: 25 }),
    ]);
    expect(wrapper.emitted('refresh')).toHaveLength(1);
  });
});

import { mount } from '@vue/test-utils';
import { describe, expect, it } from 'vitest';
import { machineDetail } from 'src/test/fixtures';
import MachinePendingUpdatesCard from './MachinePendingUpdatesCard.vue';

const update = {
  update_id: 'u1',
  title: 'KB5030211',
  kb_ids: ['5030211'],
  severity: 'important',
  is_downloaded: false,
  is_mandatory: false,
} as never;

describe('MachinePendingUpdatesCard (item 10)', () => {
  it('says when the list was read, and leaves out an empty date', () => {
    const dated = mount(MachinePendingUpdatesCard, {
      props: { machine: machineDetail({ pending_updates: [update] }), loading: false },
    }).text();
    expect(dated).toMatch(/Relevé au dernier passage de l'agent \(\d/);

    const undated = mount(MachinePendingUpdatesCard, {
      props: {
        machine: machineDetail({ pending_updates: [update], wu_last_search: null }),
        loading: false,
      },
    }).text();
    expect(undated).toContain("Relevé au dernier passage de l'agent —");
    expect(undated).not.toContain('(—)');
  });
});

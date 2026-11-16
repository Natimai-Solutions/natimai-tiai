import { mount } from '@vue/test-utils';
import { QBadge } from 'quasar';
import { describe, expect, it } from 'vitest';
import { createMemoryHistory, createRouter } from 'vue-router';
import type { InstalledSoftware } from 'src/services/machines';
import { machineDetail } from 'src/test/fixtures';
import MachineSoftwareCard from './MachineSoftwareCard.vue';

const NOTICE =
  'Relevé partiel : le plafond quotidien de nouveaux logiciels a été atteint ; le poste complétera son relevé automatiquement.';

const software = [
  { software_id: 1, name: 'Firefox', version: '131.0', publisher: 'Mozilla', install_date: null },
  { software_id: 2, name: '7-Zip', version: '24.08', publisher: 'Igor Pavlov', install_date: null },
] as unknown as InstalledSoftware[];

function mountCard(over: Parameters<typeof machineDetail>[0]) {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/machines', name: 'machines', component: { render: () => null } }],
  });
  return mount(MachineSoftwareCard, {
    props: { machine: machineDetail({ software, ...over }), loading: false },
    global: { plugins: [router] },
  });
}

/** The card's text on one line, as a reader sees it. */
function text(wrapper: ReturnType<typeof mountCard>): string {
  return wrapper.text().replace(/\s+/g, ' ');
}

describe('MachineSoftwareCard — a list the server cut short', () => {
  it('says the list is partial, and does not count it as a whole one', () => {
    const wrapper = mountCard({ software_truncated: true });

    expect(text(wrapper)).toContain(NOTICE);
    expect(wrapper.findComponent(QBadge).text()).toBe('2+');
  });

  it('says nothing of the kind for a complete list', () => {
    const wrapper = mountCard({ software_truncated: false });

    expect(text(wrapper)).not.toContain('Relevé partiel');
    expect(wrapper.findComponent(QBadge).text()).toBe('2');
  });

  it('says nothing either when an older server does not send the flag', () => {
    const wrapper = mountCard({});

    expect(text(wrapper)).not.toContain('Relevé partiel');
    expect(wrapper.findComponent(QBadge).text()).toBe('2');
  });
});

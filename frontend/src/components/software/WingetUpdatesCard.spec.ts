import { flushPromises, mount } from '@vue/test-utils';
import { QToggle } from 'quasar';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { defineComponent, h } from 'vue';
import { createMemoryHistory, createRouter } from 'vue-router';

vi.mock('src/services/compliance', async (importOriginal) => ({
  ...(await importOriginal<typeof import('src/services/compliance')>()),
  listWingetUpdates: vi.fn(),
}));

import { listWingetUpdates } from 'src/services/compliance';
import LoadErrorBanner from 'src/components/LoadErrorBanner.vue';
import WingetUpdatesCard from './WingetUpdatesCard.vue';

const Stub = defineComponent({ render: () => h('div') });

function router() {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', component: Stub },
      { path: '/machines', name: 'machines', component: Stub },
    ],
  });
}

async function mountCard() {
  const r = router();
  await r.push('/');
  const w = mount(WingetUpdatesCard, { global: { plugins: [r] } });
  await flushPromises();
  return w;
}

describe('WingetUpdatesCard', () => {
  beforeEach(() => vi.mocked(listWingetUpdates).mockReset());

  it('lists the programs to update, each count opening its postes', async () => {
    vi.mocked(listWingetUpdates).mockResolvedValue({
      reporting: 12,
      items: [
        {
          winget_id: 'Mozilla.Firefox',
          name: 'Firefox',
          installed: 10,
          outdated: 4,
          available: '131.0',
          up_to_date_percent: 60,
        },
      ],
    });
    const w = await mountCard();
    expect(listWingetUpdates).toHaveBeenCalledWith({ outdated_only: true });
    expect(w.text()).toContain('Sur 12 poste(s)');
    expect(w.text()).toContain('Firefox');
    expect(w.text()).toContain('131.0');
    expect(w.text()).toContain('60 %');
    const link = w.find('a[href*="winget_outdated"]');
    expect(link.attributes('href')).toBe('/machines?winget_outdated=Mozilla.Firefox');
  });

  it('says how to turn the collection on when no poste reports', async () => {
    vi.mocked(listWingetUpdates).mockResolvedValue({ reporting: 0, items: [] });
    const w = await mountCard();
    expect(w.find('[data-test="winget-none-reporting"]').text()).toContain('ReportWingetPackages');
  });

  it('asks for every program once the toggle is off', async () => {
    vi.mocked(listWingetUpdates).mockResolvedValue({ reporting: 1, items: [] });
    const w = await mountCard();
    w.findComponent(QToggle).vm.$emit('update:model-value', false);
    await flushPromises();
    expect(listWingetUpdates).toHaveBeenLastCalledWith({ outdated_only: false });
  });

  it('shows a failed load', async () => {
    vi.mocked(listWingetUpdates).mockRejectedValueOnce(new Error('boom'));
    const w = await mountCard();
    expect(w.findComponent(LoadErrorBanner).exists()).toBe(true);
  });
});

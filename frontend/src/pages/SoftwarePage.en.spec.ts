// The software catalogue in English (plan `dev/plan-console-bilingue.md`, I6),
// and following a change of language while it is open.
import { flushPromises, mount } from '@vue/test-utils';
import { QTable } from 'quasar';
import { createPinia, setActivePinia } from 'pinia';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { defineComponent, h, nextTick } from 'vue';
import { createMemoryHistory, createRouter } from 'vue-router';

vi.mock('src/services/software', async (importOriginal) => ({
  ...(await importOriginal<typeof import('src/services/software')>()),
  listSoftware: vi.fn(),
}));

import { setLocale } from 'src/i18n';
import { listSoftware } from 'src/services/software';
import SoftwarePage from './SoftwarePage.vue';

const Stub = defineComponent({ render: () => h('div') });

const entries = [
  {
    id: 1,
    name: '7-Zip',
    version: '23.01',
    publisher: 'Igor Pavlov',
    machine_count: 12,
    first_seen: '2026-10-06T05:00:00Z',
  },
  {
    id: 2,
    name: 'Notepad++',
    version: '8.6',
    publisher: 'Don Ho',
    machine_count: 1,
    first_seen: '2026-10-07T05:00:00Z',
  },
];

async function mountAt(path: string) {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/software', name: 'software', component: Stub },
      { path: '/machines', name: 'machines', component: Stub },
    ],
  });
  await router.push(path);
  // The page outside a layout: its `q-page` as a plain block.
  const wrapper = mount(SoftwarePage, {
    global: { plugins: [router], stubs: { QPage: { template: '<div><slot /></div>' } } },
  });
  await flushPromises();
  return wrapper;
}

const headers = (wrapper: Awaited<ReturnType<typeof mountAt>>) =>
  (wrapper.findComponent(QTable).props('columns') as { label: string }[]).map((c) => c.label);

describe('SoftwarePage in English', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.mocked(listSoftware).mockReset();
    vi.mocked(listSoftware).mockResolvedValue({
      items: entries,
      total: 2,
      page: 1,
      page_size: 25,
    });
  });
  afterEach(() => setLocale('fr'));

  it('shows the catalogue in English, and no French', async () => {
    setLocale('en');
    const wrapper = await mountAt('/software');
    const text = wrapper.text();
    expect(text).toContain('Fleet software');
    expect(text).toContain('Export');
    expect(text).toContain('12 computers');
    expect(text).toContain('1 computer');
    expect(headers(wrapper)).toEqual(['Name', 'Version', 'Publisher', 'Computers', 'Seen since']);
    expect(wrapper.find('input').attributes('placeholder')).toBe('Name or publisher…');
    expect(wrapper.find('[aria-label="Refresh"]').exists()).toBe(true);
    expect(text).not.toMatch(/[éèàùçêô«»]/);
  });

  it('says in English that nothing matches', async () => {
    vi.mocked(listSoftware).mockResolvedValue({ items: [], total: 0, page: 1, page_size: 25 });
    setLocale('en');
    const wrapper = await mountAt('/software?search=java');
    expect(wrapper.text()).toContain('No software matches “java”.');
  });

  it('switches language while it is open', async () => {
    const wrapper = await mountAt('/software');
    expect(wrapper.text()).toContain('Logiciels du parc');
    expect(wrapper.text()).toContain('12 poste(s)');
    expect(headers(wrapper)).toContain('Éditeur');
    setLocale('en');
    await nextTick();
    expect(wrapper.text()).toContain('Fleet software');
    expect(wrapper.text()).toContain('12 computers');
    expect(headers(wrapper)).toContain('Publisher');
  });
});

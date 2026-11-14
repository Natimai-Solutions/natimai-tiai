import { flushPromises, mount } from '@vue/test-utils';
import { QInput, QTable } from 'quasar';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { defineComponent, h } from 'vue';
import { createMemoryHistory, createRouter } from 'vue-router';

vi.mock('src/services/software', async (importOriginal) => ({
  ...(await importOriginal<typeof import('src/services/software')>()),
  listSoftware: vi.fn(),
}));

import { listSoftware, type ListSoftwareParams, type SoftwareList } from 'src/services/software';
import SoftwarePage from './SoftwarePage.vue';

const Stub = defineComponent({ render: () => h('div') });

const entry = {
  id: 1,
  name: '7-Zip',
  version: '23.01',
  publisher: 'Igor Pavlov',
  machine_count: 12,
  first_seen: '2026-10-06T05:00:00Z',
};

/** A catalogue of `total` entries, answered page by page. */
function catalogue(total: number) {
  vi.mocked(listSoftware).mockImplementation((params: ListSoftwareParams = {}) => {
    const page = params.page ?? 1;
    const size = params.page_size ?? 25;
    const count = Math.max(0, Math.min(size, total - (page - 1) * size));
    const items = Array.from({ length: count }, (_, k) => ({ ...entry, id: k + 1 }));
    return Promise.resolve({ items, total, page, page_size: size });
  });
}

async function mountAt(path: string) {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/software', name: 'software', component: Stub },
      { path: '/machines', name: 'machines', component: Stub },
    ],
  });
  await router.push(path);
  const wrapper = mount(SoftwarePage, {
    shallow: true,
    global: { plugins: [router], renderStubDefaultSlot: true },
  });
  await flushPromises();
  return { wrapper, router };
}

const lastParams = () => vi.mocked(listSoftware).mock.calls.at(-1)![0]!;
const tablePage = (wrapper: Awaited<ReturnType<typeof mountAt>>['wrapper']) =>
  (wrapper.findComponent(QTable).props('pagination') as { page: number }).page;

describe('SoftwarePage (audit T42)', () => {
  beforeEach(() => {
    vi.mocked(listSoftware).mockReset();
  });

  it('falls back to the last page when the URL points past the end', async () => {
    catalogue(120);
    const { wrapper, router } = await mountAt('/software?page=9');

    expect(lastParams().page).toBe(5);
    expect(tablePage(wrapper)).toBe(5);
    expect((wrapper.findComponent(QTable).props('rows') as unknown[]).length).toBe(20);
    expect(router.currentRoute.value.query.page).toBe('5');
  });

  it('follows the URL when it changes from outside the page', async () => {
    catalogue(120);
    const { wrapper, router } = await mountAt('/software?search=java&page=2');
    expect(lastParams()).toMatchObject({ search: 'java', page: 2 });
    const requests = vi.mocked(listSoftware).mock.calls.length;

    // The drawer's « Logiciels » link: the same page, the query dropped.
    await router.push({ name: 'software' });
    await flushPromises();

    expect(vi.mocked(listSoftware).mock.calls.length).toBe(requests + 1);
    expect(lastParams()).not.toHaveProperty('search');
    expect(lastParams().page).toBe(1);
    expect(wrapper.findComponent(QInput).props('modelValue')).toBe('');
    expect(tablePage(wrapper)).toBe(1);
  });

  it('does not reload on its own writes to the URL', async () => {
    catalogue(120);
    const { wrapper } = await mountAt('/software');
    const requests = vi.mocked(listSoftware).mock.calls.length;

    wrapper.findComponent(QTable).vm.$emit('request', {
      pagination: { page: 2, rowsPerPage: 25, sortBy: 'name', descending: false },
    });
    await flushPromises();

    expect(vi.mocked(listSoftware).mock.calls.length).toBe(requests + 1);
  });

  it('keeps the answer of the latest search, not of the slowest', async () => {
    const pending: ((v: SoftwareList) => void)[] = [];
    vi.mocked(listSoftware).mockImplementation(
      () => new Promise((resolve) => pending.push(resolve)),
    );
    const { wrapper } = await mountAt('/software');
    const input = wrapper.findComponent(QInput);
    input.vm.$emit('update:modelValue', 'java');
    await flushPromises();

    // The second search answers first, the first one last.
    pending[1]!({ items: [{ ...entry, name: 'Java' }], total: 1, page: 1, page_size: 25 });
    await flushPromises();
    pending[0]!({ items: [entry, entry], total: 2, page: 1, page_size: 25 });
    await flushPromises();

    const rows = wrapper.findComponent(QTable).props('rows') as { name: string }[];
    expect(rows.map((r) => r.name)).toEqual(['Java']);
  });
});

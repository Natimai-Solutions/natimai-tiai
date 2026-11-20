import { flushPromises, mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import { QBtnToggle, QTable } from 'quasar';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { defineComponent, h } from 'vue';
import { createMemoryHistory, createRouter } from 'vue-router';

vi.mock('src/services/assets', async (importOriginal) => ({
  ...(await importOriginal<typeof import('src/services/assets')>()),
  listAssets: vi.fn(),
}));

import { listAssets } from 'src/services/assets';
import AssetsPage from './AssetsPage.vue';

const Stub = defineComponent({ render: () => h('div') });

async function mountPage() {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/assets', name: 'assets', component: Stub },
      { path: '/assets/labels', name: 'asset-labels', component: Stub },
      { path: '/machines/:id', name: 'machine-detail', component: Stub },
    ],
  });
  await router.push('/assets');
  const wrapper = mount(AssetsPage, {
    shallow: true,
    global: { plugins: [router], renderStubDefaultSlot: true },
  });
  await flushPromises();
  return wrapper;
}

describe('AssetsPage', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.mocked(listAssets).mockReset();
    vi.mocked(listAssets).mockResolvedValue({ items: [], total: 0, page: 1, page_size: 50 });
  });

  it('reads the first page of every asset', async () => {
    const wrapper = await mountPage();
    expect(listAssets).toHaveBeenCalledWith({ page: 1, page_size: 50 });
    expect(wrapper.findComponent(QTable).exists()).toBe(true);
  });

  it('narrows to the equipment without an agent', async () => {
    const wrapper = await mountPage();
    wrapper.findComponent(QBtnToggle).vm.$emit('update:modelValue', 'equipment');
    await flushPromises();
    expect(listAssets).toHaveBeenLastCalledWith({ page: 1, page_size: 50, with_machine: false });
  });
});

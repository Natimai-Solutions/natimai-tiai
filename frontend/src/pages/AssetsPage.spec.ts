import { flushPromises, mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import { QBtn, QBtnToggle, QChip, QSelect, QTable } from 'quasar';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { defineComponent, h } from 'vue';
import { createMemoryHistory, createRouter } from 'vue-router';

vi.mock('src/services/assets', async (importOriginal) => ({
  ...(await importOriginal<typeof import('src/services/assets')>()),
  listAssets: vi.fn(),
}));
vi.mock('src/services/rooms', async (importOriginal) => ({
  ...(await importOriginal<typeof import('src/services/rooms')>()),
  listRooms: vi.fn(),
}));

import { listAssets } from 'src/services/assets';
import { listRooms, type Room } from 'src/services/rooms';
import { useAuthStore } from 'src/stores/auth';
import AssetsPage from './AssetsPage.vue';

const Stub = defineComponent({ render: () => h('div') });

async function mountPage(path = '/equipment', permissions: string[] = []) {
  useAuthStore().user = { id: 'u', email: 'a@b.c', permissions } as never;
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/equipment', name: 'assets', component: Stub },
      { path: '/equipment/labels', name: 'asset-labels', component: Stub },
      { path: '/machines', name: 'machines', component: Stub },
      { path: '/machines/:id', name: 'machine-detail', component: Stub },
    ],
  });
  await router.push(path);
  const wrapper = mount(AssetsPage, {
    shallow: true,
    global: { plugins: [router], renderStubDefaultSlot: true },
  });
  await flushPromises();
  return Object.assign(wrapper, { router });
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

  it('opens on a scanned label’s equipment, and lets it go from the drawer link', async () => {
    const wrapper = await mountPage('/equipment?ids=a-9');
    expect(listAssets).toHaveBeenLastCalledWith({ page: 1, page_size: 50, ids: 'a-9' });
    expect(wrapper.findComponent(QChip).exists()).toBe(true);
    // « Matériels » in the drawer: same page, the address without ?ids=.
    await wrapper.router.push({ name: 'assets' });
    await flushPromises();
    expect(listAssets).toHaveBeenLastCalledWith({ page: 1, page_size: 50 });
    expect(wrapper.findComponent(QChip).exists()).toBe(false);
  });

  it('prints a room’s labels, and opens its postes of a status in the list', async () => {
    vi.mocked(listRooms).mockResolvedValue([
      { id: 'r-1', name: 'A101', building: null } as unknown as Room,
    ]);
    const wrapper = await mountPage('/equipment?room=r-1', ['machine:read', 'room:read']);
    expect(listAssets).toHaveBeenLastCalledWith({ page: 1, page_size: 50, room_id: 'r-1' });
    const button = (icon: string) =>
      wrapper.findAllComponents(QBtn).find((b) => b.props('icon') === icon)!;
    expect(button('qr_code_2').props('to')).toEqual({
      name: 'asset-labels',
      query: { room_id: 'r-1' },
    });
    const status = wrapper.findAllComponents(QSelect).find((c) => c.props('label') === 'Statut')!;
    status.vm.$emit('update:modelValue', 'in_repair');
    await flushPromises();
    // The room goes along: the list opens on that room's postes only.
    expect(button('list').props('to')).toEqual({
      name: 'machines',
      query: { asset_status: 'in_repair', room: 'r-1' },
    });
  });
});

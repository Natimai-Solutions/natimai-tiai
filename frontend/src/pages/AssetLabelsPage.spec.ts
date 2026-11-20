import { flushPromises, mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import { QBtn } from 'quasar';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { defineComponent, h } from 'vue';
import { createMemoryHistory, createRouter } from 'vue-router';

vi.mock('src/services/assets', async (importOriginal) => ({
  ...(await importOriginal<typeof import('src/services/assets')>()),
  listAssets: vi.fn(),
  completeRoomAssets: vi.fn(),
}));

import { completeRoomAssets, labelUrl, listAssets, qrPath, type Asset } from 'src/services/assets';
import { useAuthStore } from 'src/stores/auth';
import AssetLabelsPage from './AssetLabelsPage.vue';

const Stub = defineComponent({ render: () => h('div') });

function asset(id: string, name: string, inventory: string | null): Asset {
  return {
    id,
    display_name: name,
    inventory_number: inventory,
    building_name: 'Bât. A',
    room_name: 'A101',
    public_token: `tok-${id}`,
  } as unknown as Asset;
}

async function mountAt(path: string, permissions = ['asset:read']) {
  const pinia = createPinia();
  setActivePinia(pinia);
  useAuthStore().user = { id: 'u', email: 'a@b.c', permissions } as never;
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/equipment/labels', name: 'asset-labels', component: Stub },
      { path: '/equipment', name: 'assets', component: Stub },
    ],
  });
  await router.push(path);
  const wrapper = mount(AssetLabelsPage, { global: { plugins: [pinia, router] } });
  await flushPromises();
  return wrapper;
}

describe('AssetLabelsPage', () => {
  beforeEach(() => {
    vi.mocked(listAssets).mockReset();
    vi.mocked(completeRoomAssets).mockReset();
    vi.mocked(listAssets).mockResolvedValue({
      items: [asset('x', 'PC-1', 'INV-1'), asset('y', 'Projecteur', null)],
      total: 2,
      page: 1,
      page_size: 500,
    });
  });

  it('prints one label per selected asset, its QR leading to the console', async () => {
    const wrapper = await mountAt('/equipment/labels?ids=x,y');
    expect(listAssets).toHaveBeenCalledWith({ ids: 'x,y', page_size: 500 });
    const labels = wrapper.findAll('.label');
    expect(labels).toHaveLength(2);
    expect(labels[0]!.text()).toContain('PC-1');
    expect(labels[0]!.text()).toContain('INV-1');
    expect(labels[0]!.text()).toContain('Bât. A — A101');
    expect(labels[0]!.find('path').attributes('d')).toBe(qrPath(labelUrl('tok-x')).path);
  });

  it('prints a room’s labels, and offers the records its postes lack', async () => {
    vi.mocked(completeRoomAssets).mockResolvedValue(3);
    const wrapper = await mountAt('/equipment/labels?room_id=r-1', ['asset:read', 'asset:write']);
    expect(listAssets).toHaveBeenCalledWith({ room_id: 'r-1', page_size: 500 });
    const complete = wrapper
      .findAllComponents(QBtn)
      .find((b) => b.props('label') === 'Créer les fiches qui manquent')!;
    await complete.trigger('click');
    await flushPromises();
    expect(completeRoomAssets).toHaveBeenCalledWith('r-1');
    // Read again, the new records' labels with them.
    expect(listAssets).toHaveBeenCalledTimes(2);
  });

  it('offers no records to an account that cannot write them', async () => {
    const wrapper = await mountAt('/equipment/labels?room_id=r-1');
    expect(wrapper.text()).toContain('n’a pas encore d’étiquette');
    expect(
      wrapper
        .findAllComponents(QBtn)
        .some((b) => b.props('label') === 'Créer les fiches qui manquent'),
    ).toBe(false);
  });

  it('asks for nothing without a selection or a room', async () => {
    const wrapper = await mountAt('/equipment/labels');
    expect(listAssets).not.toHaveBeenCalled();
    expect(wrapper.text()).toContain('Aucune étiquette à imprimer.');
  });
});

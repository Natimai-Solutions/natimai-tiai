import { flushPromises, mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { defineComponent, h } from 'vue';
import { createMemoryHistory, createRouter } from 'vue-router';

vi.mock('src/services/assets', async (importOriginal) => ({
  ...(await importOriginal<typeof import('src/services/assets')>()),
  resolveAssetToken: vi.fn(),
}));

import { resolveAssetToken } from 'src/services/assets';
import { useAuthStore } from 'src/stores/auth';
import AssetTokenPage from './AssetTokenPage.vue';

const Stub = defineComponent({ render: () => h('div') });

/** Every scanned label lands here: where does it go next? */
async function scan(permissions: string[]) {
  const pinia = createPinia();
  setActivePinia(pinia);
  useAuthStore().user = { id: 'u', email: 'a@b.c', permissions } as never;
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/a/:token', name: 'asset-token', component: Stub },
      { path: '/machines/:id', name: 'machine-detail', component: Stub },
      { path: '/equipment', name: 'assets', component: Stub },
    ],
  });
  await router.push('/a/tok-1');
  const wrapper = mount(AssetTokenPage, {
    global: { plugins: [pinia, router], stubs: { QPage: { template: '<div><slot /></div>' } } },
  });
  await flushPromises();
  return { wrapper, route: router.currentRoute.value };
}

describe('AssetTokenPage', () => {
  beforeEach(() => vi.mocked(resolveAssetToken).mockReset());

  it('opens the fiche of the poste a label names', async () => {
    vi.mocked(resolveAssetToken).mockResolvedValue({ machine_id: 'm-1', asset_id: 'a-1' });
    const { route } = await scan(['machine:read']);
    expect(resolveAssetToken).toHaveBeenCalledWith('tok-1');
    expect(route.name).toBe('machine-detail');
    expect(route.params.id).toBe('m-1');
  });

  it('opens the equipment list on that equipment alone', async () => {
    vi.mocked(resolveAssetToken).mockResolvedValue({ machine_id: null, asset_id: 'a-9' });
    const { route } = await scan(['machine:read', 'asset:read']);
    expect(route.name).toBe('assets');
    expect(route.query).toEqual({ ids: 'a-9' });
  });

  it('says so to a reader who cannot open Matériels, rather than leaving silently', async () => {
    vi.mocked(resolveAssetToken).mockResolvedValue({ machine_id: null, asset_id: 'a-9' });
    const { wrapper, route } = await scan(['machine:read']);
    expect(route.name).toBe('asset-token');
    expect(wrapper.text()).toContain('matériel sans agent');
  });

  it('says a label out of reach leads nowhere', async () => {
    vi.mocked(resolveAssetToken).mockRejectedValueOnce({ response: { status: 404 } });
    const { wrapper, route } = await scan(['machine:read']);
    expect(route.name).toBe('asset-token');
    expect(wrapper.text()).toContain('Cette étiquette ne mène à aucun matériel');
  });
});

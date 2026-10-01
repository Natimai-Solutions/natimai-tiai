import { mount } from '@vue/test-utils';
import { QBtn } from 'quasar';
import { describe, expect, it } from 'vitest';
import MachinesToolbar from './MachinesToolbar.vue';

function mountToolbar(lastRefreshedAt: Date | null = null) {
  return mount(MachinesToolbar, { props: { loading: false, lastRefreshedAt } });
}

describe('MachinesToolbar', () => {
  it('says how fresh the list is once it has loaded', () => {
    expect(mountToolbar().text()).not.toContain('Actualisé');
    const at = new Date(2026, 9, 1, 14, 5, 9);
    expect(mountToolbar(at).text()).toContain('Actualisé à 14:05:09');
  });

  it('says which button was pressed, the page owning what follows', async () => {
    const wrapper = mountToolbar();
    const buttons = wrapper.findAllComponents(QBtn);

    await buttons.find((b) => b.props('label') === 'Colonnes')!.trigger('click');
    await buttons.find((b) => b.props('label') === 'Exporter')!.trigger('click');
    await buttons.find((b) => b.attributes('aria-label') === 'Actualiser')!.trigger('click');

    expect(Object.keys(wrapper.emitted()).filter((e) => e !== 'click')).toEqual([
      'columns',
      'export',
      'refresh',
    ]);
  });
});

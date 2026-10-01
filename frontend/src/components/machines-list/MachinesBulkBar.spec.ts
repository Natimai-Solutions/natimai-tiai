import { mount } from '@vue/test-utils';
import { QBtn, QBtnDropdown, QItem } from 'quasar';
import { describe, expect, it } from 'vitest';
import MachinesBulkBar from './MachinesBulkBar.vue';
import { commandActionGroups, type CommandActionGroup } from 'src/services/commands';

function mountBar(
  props: Partial<{
    count: number;
    canPlace: boolean;
    canCheck: boolean;
    actionGroups: CommandActionGroup[];
  }> = {},
) {
  return mount(MachinesBulkBar, {
    props: { count: 3, canPlace: true, canCheck: true, actionGroups: [], ...props },
  });
}

const buttonLabels = (wrapper: ReturnType<typeof mountBar>) =>
  wrapper.findAllComponents(QBtn).map((b) => b.props('label') as string);

describe('MachinesBulkBar', () => {
  it('stays hidden without a selection', () => {
    expect(mountBar({ count: 0 }).html()).not.toContain('sélectionné');
  });

  it('stays hidden when the account may do nothing with the selection', () => {
    const wrapper = mountBar({ canPlace: false, canCheck: false, actionGroups: [] });
    expect(wrapper.html()).not.toContain('sélectionné');
  });

  it('offers only what the account may do', () => {
    expect(buttonLabels(mountBar({ canPlace: false }))).toEqual(['Demander une vérification']);
    expect(buttonLabels(mountBar({ canCheck: false }))).toEqual(['Affecter à une salle']);
    expect(mountBar().findComponent(QBtnDropdown).exists()).toBe(false);
  });

  it('counts the selection and says which button was pressed', async () => {
    const wrapper = mountBar();
    expect(wrapper.text()).toContain('3 sélectionné(s)');

    for (const label of ['Affecter à une salle', 'Demander une vérification']) {
      await wrapper
        .findAllComponents(QBtn)
        .find((b) => b.props('label') === label)!
        .trigger('click');
    }

    expect(wrapper.emitted('place')).toHaveLength(1);
    expect(wrapper.emitted('ask')).toHaveLength(1);
  });

  it('lists the bulk commands in their sections and runs the one picked', async () => {
    const groups = commandActionGroups({ bulkOnly: true });
    const wrapper = mountBar({ actionGroups: groups });

    await wrapper.findComponent(QBtnDropdown).trigger('click');
    const items = wrapper.findAllComponents(QItem);
    const first = groups[0]!.actions[0]!;
    expect(items.length).toBe(groups.reduce((n, g) => n + g.actions.length, 0));

    await items[0]!.trigger('click');

    expect(wrapper.emitted('run')).toEqual([[first]]);
  });
});

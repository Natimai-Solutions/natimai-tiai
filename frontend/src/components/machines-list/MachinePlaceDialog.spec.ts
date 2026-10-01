import { flushPromises, mount } from '@vue/test-utils';
import { QBtn, QSelect } from 'quasar';
import { describe, expect, it, vi } from 'vitest';
import MachinePlaceDialog from './MachinePlaceDialog.vue';
import type { Room } from 'src/services/rooms';

const rooms = [
  { id: 'r-1', name: 'B12', building: { id: 'b-1', name: 'Nord' } },
  { id: 'r-2', name: 'Atelier', building: null },
] as unknown as Room[];

/** Mounted closed, then opened: the dialog renders its content as it shows. */
async function mountDialog(save: (roomId: string | null) => Promise<void>) {
  const wrapper = mount(MachinePlaceDialog, {
    props: { modelValue: false, count: 4, rooms, save },
    attachTo: document.body,
  });
  await wrapper.setProps({ modelValue: true });
  await flushPromises();
  return wrapper;
}

const affecter = (wrapper: Awaited<ReturnType<typeof mountDialog>>) =>
  wrapper.findAllComponents(QBtn).find((b) => b.props('label') === 'Affecter')!;

describe('MachinePlaceDialog', () => {
  it('offers « Sans salle » first, then each room with its building', async () => {
    const wrapper = await mountDialog(vi.fn());
    const options = wrapper.findComponent(QSelect).props('options') as { label: string }[];

    expect(options.map((o) => o.label)).toEqual([
      'Sans salle (retirer de la salle)',
      'Nord › B12',
      'Atelier',
    ]);
    expect(document.body.textContent).toContain('4 poste(s) sélectionné(s)');
    wrapper.unmount();
  });

  it('hands the room picked to the caller, the button spinning meanwhile', async () => {
    let finish!: () => void;
    const save = vi.fn(() => new Promise<void>((resolve) => (finish = resolve)));
    const wrapper = await mountDialog(save);

    await wrapper.findComponent(QSelect).setValue('r-2');
    await affecter(wrapper).trigger('click');

    expect(save).toHaveBeenCalledWith('r-2');
    expect(affecter(wrapper).props('loading')).toBe(true);
    finish();
    await vi.waitFor(() => expect(affecter(wrapper).props('loading')).toBe(false));
    wrapper.unmount();
  });

  it('keeps « Affecter » disabled until a room is picked', async () => {
    const save = vi.fn(() => Promise.resolve());
    const wrapper = await mountDialog(save);

    expect(affecter(wrapper).props('disable')).toBe(true);
    await affecter(wrapper).trigger('click');
    expect(save).not.toHaveBeenCalled();
    expect(affecter(wrapper).props('loading')).toBe(false);

    await wrapper.findComponent(QSelect).setValue('r-1');
    expect(affecter(wrapper).props('disable')).toBe(false);
    wrapper.unmount();
  });
});

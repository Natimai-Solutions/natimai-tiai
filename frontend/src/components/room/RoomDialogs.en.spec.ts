import { flushPromises, mount } from '@vue/test-utils';
import { QInput, QSelect } from 'quasar';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { nextTick } from 'vue';

vi.mock('src/services/rooms', async (importOriginal) => ({
  ...(await importOriginal<typeof import('src/services/rooms')>()),
  createBuilding: vi.fn(),
  updateBuilding: vi.fn(),
  createRoom: vi.fn(),
}));

import { setLocale } from 'src/i18n';
import { createBuilding, createRoom, updateBuilding, type Building } from 'src/services/rooms';
import BuildingFormDialog from './BuildingFormDialog.vue';
import RoomFormDialog from './RoomFormDialog.vue';

const NO_FRENCH = /[éèàùç«»]|Annuler|Enregistrer|Nom\b|Salle/;

function bodyText(): string {
  return document.body.textContent ?? '';
}

const building: Building = {
  id: 'b-1',
  name: 'Science block',
  location: 'North campus',
  notes: null,
  room_count: 1,
  machine_count: 3,
  created_at: '',
  updated_at: '',
};

afterEach(() => {
  setLocale('fr');
  document.body.innerHTML = '';
});

describe('BuildingFormDialog in English', () => {
  beforeEach(() => {
    vi.mocked(createBuilding).mockReset().mockResolvedValue(building);
  });

  it('reads in English, and notifies in English', async () => {
    setLocale('en');
    const wrapper = mount(BuildingFormDialog, {
      props: { modelValue: false, building: null, locations: ['North campus'] },
      attachTo: document.body,
    });
    await wrapper.setProps({ modelValue: true });
    await flushPromises();
    const notify = vi.spyOn(wrapper.vm.$q, 'notify').mockImplementation(() => () => undefined);

    expect(bodyText()).toContain('New building');
    expect(bodyText()).toContain('In the words the agents report');
    expect(bodyText()).toContain('Cancel');
    expect(bodyText()).not.toMatch(NO_FRENCH);
    const labels = wrapper.findAllComponents(QInput).map((i) => i.props('label'));
    expect(labels).toEqual(['Name', 'Notes']);

    const name = wrapper.findAllComponents(QInput)[0]!;
    name.vm.$emit('update:modelValue', 'Library');
    await nextTick();
    document
      .querySelector('.q-dialog form')!
      .dispatchEvent(new Event('submit', { cancelable: true, bubbles: true }));
    await flushPromises();
    expect(notify).toHaveBeenCalledWith(
      expect.objectContaining({ type: 'positive', message: 'Building created' }),
    );
    wrapper.unmount();
  });
});

describe('BuildingFormDialog: its notification and a change of language', () => {
  it('rewords « Bâtiment mis à jour » on screen, after the dialog let the building go', async () => {
    vi.mocked(updateBuilding).mockReset().mockResolvedValue(building);
    const wrapper = mount(BuildingFormDialog, {
      props: { modelValue: false, building, locations: [] },
      attachTo: document.body,
    });
    await wrapper.setProps({ modelValue: true });
    await flushPromises();
    const notify = vi.spyOn(wrapper.vm.$q, 'notify').mockImplementation(() => () => undefined);
    document
      .querySelector('.q-dialog form')!
      .dispatchEvent(new Event('submit', { cancelable: true, bubbles: true }));
    await flushPromises();
    expect(notify).toHaveBeenLastCalledWith(
      expect.objectContaining({ type: 'positive', message: 'Bâtiment mis à jour' }),
    );

    // The page closes the dialog and forgets the building; then the language changes.
    await wrapper.setProps({ modelValue: false, building: null });
    setLocale('en');
    expect(notify).toHaveBeenLastCalledWith(
      expect.objectContaining({ type: 'positive', message: 'Building updated' }),
    );
    wrapper.unmount();
  });
});

describe('RoomFormDialog in English', () => {
  beforeEach(() => {
    vi.mocked(createRoom).mockReset();
  });

  it('reads in English, and follows a change of language', async () => {
    const wrapper = mount(RoomFormDialog, {
      props: { modelValue: false, room: null, buildings: [building], locations: [] },
      attachTo: document.body,
    });
    await wrapper.setProps({ modelValue: true });
    await flushPromises();
    expect(bodyText()).toContain('Nouvelle salle');

    setLocale('en');
    await nextTick();

    expect(bodyText()).toContain('New room');
    expect(bodyText()).toContain('The room takes the location of its building');
    expect(bodyText()).not.toMatch(NO_FRENCH);
    const [select] = wrapper.findAllComponents(QSelect);
    expect(select!.props('label')).toBe('Building');
    expect(select!.props('options')).toEqual([
      { label: 'No building', value: null },
      { label: 'Science block — North campus', value: 'b-1' },
    ]);
    wrapper.unmount();
  });
});

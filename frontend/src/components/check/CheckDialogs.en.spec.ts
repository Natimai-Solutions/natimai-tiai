import { flushPromises, mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import { QInput, QSelect } from 'quasar';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { nextTick } from 'vue';

vi.mock('src/services/checks', async (importOriginal) => ({
  ...(await importOriginal<typeof import('src/services/checks')>()),
  closeCheck: vi.fn(),
  listAssignableUsers: vi.fn(),
}));
vi.mock('src/composables/useTasksBadge', () => ({ notifyTasksChanged: vi.fn() }));

import { setLocale } from 'src/i18n';
import { closeCheck, listAssignableUsers, type Check } from 'src/services/checks';
import { useAuthStore } from 'src/stores/auth';
import CheckCloseDialog from './CheckCloseDialog.vue';
import CheckRequestDialog from './CheckRequestDialog.vue';

const NO_FRENCH = /[éèàùç«»]|Annuler|Enregistrer|Consignes|Clore/;

function bodyText(): string {
  return document.body.textContent ?? '';
}

afterEach(() => {
  setLocale('fr');
  document.body.innerHTML = '';
});

describe('CheckCloseDialog in English', () => {
  const check = {
    id: 'c-1',
    instructions: 'Screen flickers',
    created_at: new Date(Date.now() - 3600_000).toISOString(),
  };

  async function open() {
    const wrapper = mount(CheckCloseDialog, {
      props: { modelValue: false, check },
      attachTo: document.body,
    });
    await wrapper.setProps({ modelValue: true });
    await flushPromises();
    return wrapper;
  }

  beforeEach(() => {
    vi.mocked(closeCheck)
      .mockReset()
      .mockResolvedValue({} as never);
  });

  it('reads in English, with no French left', async () => {
    setLocale('en');
    const wrapper = await open();
    const text = bodyText();

    expect(text).toContain('Close the check');
    expect(text).toContain('Instructions: Screen flickers');
    expect(text).toContain('What was found');
    expect(text).toContain("Kept on the request and written to the computer's history");
    expect(text).toContain('Leave as is for now; backdating is allowed');
    expect(text).toContain('Cancel');
    expect(text).not.toMatch(NO_FRENCH);
    wrapper.unmount();
  });

  it('refuses a date in the future, and notifies the closing, in English', async () => {
    setLocale('en');
    const wrapper = await open();
    const notify = vi.spyOn(wrapper.vm.$q, 'notify').mockImplementation(() => () => undefined);
    const date = wrapper
      .findAllComponents(QInput)
      .find((i) => i.props('type') === 'datetime-local')!;
    date.vm.$emit('update:modelValue', '2999-01-01T10:00');
    await nextTick();
    expect(date.props('errorMessage')).toBe('Not in the future');

    date.vm.$emit('update:modelValue', '');
    await nextTick();
    document
      .querySelector('.q-dialog form')!
      .dispatchEvent(new Event('submit', { cancelable: true, bubbles: true }));
    await flushPromises();
    expect(notify).toHaveBeenCalledWith({ type: 'positive', message: 'Check closed' });
    wrapper.unmount();
  });

  it('switches language live', async () => {
    const wrapper = await open();
    expect(bodyText()).toContain('Clore la vérification');

    setLocale('en');
    await nextTick();

    expect(bodyText()).toContain('Close the check');
    expect(bodyText()).not.toContain('Clore la vérification');
    wrapper.unmount();
  });
});

describe('CheckRequestDialog in English', () => {
  const check = {
    id: 'c-1',
    machine_id: 'm-1',
    assigned_to: { id: 'u-2', name: 'Mary', reachable: false },
    instructions: 'Screen flickers',
  } as unknown as Check;

  beforeEach(() => {
    vi.mocked(listAssignableUsers)
      .mockReset()
      .mockResolvedValue([{ id: 'u-1', name: 'Alice' }]);
    setActivePinia(createPinia());
    useAuthStore().user = { id: 'me', email: 'a@b.c', permissions: [] } as never;
  });

  async function open(props: Record<string, unknown>) {
    const wrapper = mount(CheckRequestDialog, {
      props: { modelValue: false, check: null, save: vi.fn(), ...props },
      attachTo: document.body,
    });
    await wrapper.setProps({ modelValue: true });
    await flushPromises();
    return wrapper;
  }

  it('reads in English, with no French left', async () => {
    setLocale('en');
    const wrapper = await open({ machineId: 'm-1', subtitle: 'PC-01' });
    const text = bodyText();

    expect(text).toContain('Request a check');
    expect(text).toContain('Nobody: the request stays open for anyone to take');
    expect(text).toContain('What to look at, and why');
    expect(text).toContain('Save');
    const [assignee] = wrapper.findAllComponents(QSelect);
    expect(assignee!.props('label')).toBe('Assign to');
    expect(text).not.toMatch(NO_FRENCH);
    wrapper.unmount();
  });

  it('names an assignee who no longer sees the computer, and follows the language', async () => {
    const wrapper = await open({ check });
    const [assignee] = wrapper.findAllComponents(QSelect);
    expect(bodyText()).toContain('Modifier la demande');
    expect((assignee!.props('options') as unknown[])[0]).toEqual({
      label: 'Mary (ne voit plus ce poste)',
      value: 'u-2',
    });

    setLocale('en');
    await nextTick();

    expect(bodyText()).toContain('Edit the request');
    expect(assignee!.props('options')).toEqual([
      { label: 'Mary (can no longer see this computer)', value: 'u-2' },
      { label: 'Alice', value: 'u-1' },
    ]);
    wrapper.unmount();
  });
});

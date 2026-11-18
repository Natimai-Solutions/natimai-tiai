import { flushPromises, mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import { QForm, QInput, QSelect } from 'quasar';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('src/services/checks', async (importOriginal) => ({
  ...(await importOriginal<typeof import('src/services/checks')>()),
  closeCheck: vi.fn(),
  listAssignableUsers: vi.fn(),
}));

import type { User } from 'src/services/auth';
import { closeCheck, listAssignableUsers, type Check } from 'src/services/checks';
import { useAuthStore } from 'src/stores/auth';
import CheckCloseDialog from './CheckCloseDialog.vue';
import CheckRequestDialog from './CheckRequestDialog.vue';

describe('CheckRequestDialog — an assignee deactivated since (item 4)', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.mocked(listAssignableUsers).mockResolvedValue([{ id: 'u-1', name: 'Alice' }]);
  });

  it('names the assignee « (désactivé) » rather than showing its id', async () => {
    const check = {
      id: 'c-1',
      machine_id: 'm-1',
      instructions: 'Câble',
      assigned_to: { id: 'u-gone', name: 'Marie', active: false },
    } as unknown as Check;
    const wrapper = mount(CheckRequestDialog, {
      props: { modelValue: false, check, save: vi.fn() },
      attachTo: document.body,
    });
    await wrapper.setProps({ modelValue: true });
    await flushPromises();
    const picker = wrapper.findComponent(QSelect);
    expect(picker.props('modelValue')).toBe('u-gone');
    expect(picker.props('options')).toEqual([
      { label: 'Marie (désactivé)', value: 'u-gone' },
      { label: 'Alice', value: 'u-1' },
    ]);
    wrapper.unmount();
  });
});

describe('CheckRequestDialog — a session that ends mid-form (solidity item 7)', () => {
  beforeEach(() => {
    window.sessionStorage.clear();
    // A draft is kept for an account: the one logged in (the walk with two
    // accounts is in CheckRequestDialog.draft.spec.ts).
    setActivePinia(createPinia());
    useAuthStore().user = { id: 'u-me', email: 'me@x', permissions: [] } as unknown as User;
    vi.mocked(listAssignableUsers).mockResolvedValue([]);
  });

  async function openFor(machineId: string) {
    const wrapper = mount(CheckRequestDialog, {
      props: { modelValue: false, check: null, machineId, save: vi.fn() },
      attachTo: document.body,
    });
    await wrapper.setProps({ modelValue: true });
    await flushPromises();
    const text = wrapper.findAllComponents(QInput).find((i) => i.props('label') === 'Consignes')!;
    return { wrapper, text };
  }

  it('gives the text back when the page comes back, and on that poste only', async () => {
    const first = await openFor('m-1');
    first.text.vm.$emit('update:modelValue', 'Écran qui clignote depuis lundi');
    await flushPromises();
    // The session ends: the page goes, the dialog never closes.
    first.wrapper.unmount();

    const again = await openFor('m-1');
    expect(again.text.props('modelValue')).toBe('Écran qui clignote depuis lundi');
    again.wrapper.unmount();

    const other = await openFor('m-2');
    expect(other.text.props('modelValue')).toBe('');
    other.wrapper.unmount();
  });

  it('forgets the text once the dialog is closed by the reader', async () => {
    const first = await openFor('m-1');
    first.text.vm.$emit('update:modelValue', 'Brouillon');
    await flushPromises();
    await first.wrapper.setProps({ modelValue: false });
    await flushPromises();
    first.wrapper.unmount();

    const again = await openFor('m-1');
    expect(again.text.props('modelValue')).toBe('');
    again.wrapper.unmount();
  });
});

describe('CheckCloseDialog — an optional date (item 12)', () => {
  const check = { id: 'c-1', instructions: null, created_at: '2026-11-01T08:00:00Z' };

  beforeEach(() => {
    vi.useFakeTimers({ toFake: ['Date'] });
    vi.setSystemTime(new Date('2026-11-10T12:00:00Z'));
    vi.mocked(closeCheck).mockReset();
    vi.mocked(closeCheck).mockResolvedValue({} as never);
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  async function open() {
    const wrapper = mount(CheckCloseDialog, {
      props: { modelValue: false, check },
      attachTo: document.body,
    });
    await wrapper.setProps({ modelValue: true });
    await flushPromises();
    const date = wrapper.findAllComponents(QInput).find((i) => i.props('label') === 'Date')!;
    return { wrapper, date };
  }

  async function submit(wrapper: Awaited<ReturnType<typeof open>>['wrapper']) {
    wrapper.findComponent(QForm).vm.$emit('submit', new Event('submit'));
    await flushPromises();
  }

  it('sends no date when left at now', async () => {
    const { wrapper } = await open();
    await submit(wrapper);
    expect(closeCheck).toHaveBeenCalledWith('c-1', { note: null });
    wrapper.unmount();
  });

  it('sends a date picked in the past, after the request', async () => {
    const { wrapper, date } = await open();
    date.vm.$emit('update:modelValue', '2026-11-05T09:30');
    await flushPromises();
    await submit(wrapper);
    expect(closeCheck).toHaveBeenCalledWith('c-1', {
      note: null,
      closed_at: new Date('2026-11-05T09:30').toISOString(),
    });
    wrapper.unmount();
  });

  it('refuses a date before the request, or in the future', async () => {
    const { wrapper, date } = await open();
    date.vm.$emit('update:modelValue', '2026-10-30T09:30');
    await flushPromises();
    expect(date.props('error')).toBe(true);
    expect(date.props('errorMessage')).toBe('Pas avant la demande');
    date.vm.$emit('update:modelValue', '2026-12-30T09:30');
    await flushPromises();
    expect(date.props('errorMessage')).toBe('Pas dans le futur');
    wrapper.unmount();
  });
});

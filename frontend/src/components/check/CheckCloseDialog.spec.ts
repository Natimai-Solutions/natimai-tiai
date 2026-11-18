import { flushPromises, mount } from '@vue/test-utils';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('src/services/checks', async (importOriginal) => ({
  ...(await importOriginal<typeof import('src/services/checks')>()),
  closeCheck: vi.fn(),
}));
vi.mock('src/composables/useTasksBadge', () => ({ notifyTasksChanged: vi.fn() }));

import { closeCheck } from 'src/services/checks';
import CheckCloseDialog from './CheckCloseDialog.vue';

/** A datetime-local value: local time, to the minute. */
function toLocalInput(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

describe('CheckCloseDialog — the date of the closing', () => {
  // Requested ten minutes ago, thirty seconds into its minute.
  const created = new Date(Date.now() - 10 * 60 * 1000);
  created.setSeconds(30, 0);
  const check = { id: 'c-1', instructions: null, created_at: created.toISOString() };

  beforeEach(() => {
    vi.mocked(closeCheck)
      .mockReset()
      .mockResolvedValue({} as never);
  });
  afterEach(() => {
    document.body.innerHTML = '';
  });

  async function open() {
    const wrapper = mount(CheckCloseDialog, {
      props: { modelValue: false, check },
      attachTo: document.body,
    });
    await wrapper.setProps({ modelValue: true });
    await flushPromises();
    return wrapper;
  }

  function dateInput() {
    return document.querySelector<HTMLInputElement>('.q-dialog input[type="datetime-local"]')!;
  }

  async function pick(value: string) {
    const input = dateInput();
    input.value = value;
    input.dispatchEvent(new Event('input'));
    await flushPromises();
  }

  async function submit() {
    document
      .querySelector<HTMLFormElement>('.q-dialog form')!
      .dispatchEvent(new Event('submit', { cancelable: true, bubbles: true }));
    await flushPromises();
  }

  it('sends no date when the one shown is left as it is: now', async () => {
    const wrapper = await open();
    await submit();
    expect(closeCheck).toHaveBeenCalledWith('c-1', { note: null });
    wrapper.unmount();
  });

  it('sends the instant of the request when its own minute is picked, not thirty seconds before', async () => {
    const wrapper = await open();
    // The input counts in minutes: the request's minute reads as its first
    // second, which is before the request — and the server refuses that.
    await pick(toLocalInput(created));
    expect(document.body.textContent).not.toContain('Pas avant la demande');
    await submit();

    expect(closeCheck).toHaveBeenCalledTimes(1);
    const sent = vi.mocked(closeCheck).mock.calls[0]![1] as { closed_at: string };
    expect(sent.closed_at).toBe(created.toISOString());
    wrapper.unmount();
  });

  it('sends a later date as picked', async () => {
    const wrapper = await open();
    const later = new Date(created.getTime() + 3 * 60 * 1000);
    later.setSeconds(0, 0);
    await pick(toLocalInput(later));
    await submit();
    const sent = vi.mocked(closeCheck).mock.calls[0]![1] as { closed_at: string };
    expect(sent.closed_at).toBe(later.toISOString());
    wrapper.unmount();
  });

  it('refuses a date before the request, and one in the future', async () => {
    const wrapper = await open();
    await pick(toLocalInput(new Date(created.getTime() - 2 * 60 * 1000)));
    expect(document.body.textContent).toContain('Pas avant la demande');
    await pick(toLocalInput(new Date(Date.now() + 60 * 60 * 1000)));
    expect(document.body.textContent).toContain('Pas dans le futur');
    wrapper.unmount();
  });
});

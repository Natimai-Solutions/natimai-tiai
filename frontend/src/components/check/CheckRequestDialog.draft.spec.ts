import { flushPromises, mount } from '@vue/test-utils';
import { createPinia, setActivePinia, type Pinia } from 'pinia';
import { QInput } from 'quasar';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('src/services/checks', async (importOriginal) => ({
  ...(await importOriginal<typeof import('src/services/checks')>()),
  listAssignableUsers: vi.fn(() => Promise.resolve([])),
}));
vi.mock('src/services/auth', () => ({
  getMe: vi.fn(),
  login: vi.fn(() => Promise.resolve({ access_token: 't' })),
  logout: vi.fn(() => Promise.resolve()),
  updateMe: vi.fn(),
}));

import { getMe, type User } from 'src/services/auth';
import { endSession } from 'src/services/session';
import { useAuthStore } from 'src/stores/auth';
import CheckRequestDialog from './CheckRequestDialog.vue';

/**
 * Review finding 1, the reviewer's `draft.js` walk: two accounts, one tab.
 * The text typed by one — kept so that a session ending mid-form does not
 * lose it — must never open under the name of the other.
 */
describe('CheckRequestDialog — a draft belongs to its author', () => {
  let pinia: Pinia;

  beforeEach(() => {
    window.sessionStorage.clear();
    pinia = createPinia();
    setActivePinia(pinia);
  });
  afterEach(() => {
    endSession();
    document.body.innerHTML = '';
  });

  async function logIn(who: 'tech' | 'sitea') {
    vi.mocked(getMe).mockResolvedValue({
      id: `id-${who}`,
      email: `${who}@bench.local`,
      permissions: ['check:write'],
    } as unknown as User);
    await useAuthStore().login(`${who}@bench.local`, 'password');
  }

  async function open(props: { machineId?: string; machineIds?: string[] }) {
    const wrapper = mount(CheckRequestDialog, {
      props: { modelValue: false, check: null, save: vi.fn(), ...props },
      attachTo: document.body,
      global: { plugins: [pinia] },
    });
    await wrapper.setProps({ modelValue: true });
    await flushPromises();
    const text = wrapper.findAllComponents(QInput).find((i) => i.props('label') === 'Consignes')!;
    return { wrapper, text };
  }

  /** Type in the form, then lose the session: the page goes, the dialog never closes. */
  async function typeThenLoseSession(
    props: { machineId?: string; machineIds?: string[] },
    typed: string,
  ) {
    const form = await open(props);
    form.text.vm.$emit('update:modelValue', typed);
    await flushPromises();
    endSession();
    form.wrapper.unmount();
  }

  async function reopened(props: { machineId?: string; machineIds?: string[] }): Promise<unknown> {
    const form = await open(props);
    const value: unknown = form.text.props('modelValue');
    form.wrapper.unmount();
    return value;
  }

  it('gives the text back to its author after the session ended', async () => {
    await logIn('tech');
    await typeThenLoseSession({ machineId: 'm-5' }, 'Écran cassé, voir M. Dupont');
    await logIn('tech');
    expect(await reopened({ machineId: 'm-5' })).toBe('Écran cassé, voir M. Dupont');
  });

  it('shows nothing of it to another account logging in on the same tab', async () => {
    await logIn('tech');
    await typeThenLoseSession({ machineId: 'm-5' }, 'Écran cassé, voir M. Dupont');
    // No logout in between: the login page was reached by the session ending.
    await logIn('sitea');
    expect(await reopened({ machineId: 'm-5' })).toBe('');
    // Nor is it left behind for whoever reads the tab's storage.
    expect(JSON.stringify(window.sessionStorage)).not.toContain('Dupont');
  });

  it('forgets it when its author logs out', async () => {
    await logIn('tech');
    await typeThenLoseSession({ machineId: 'm-6' }, 'DRAFT-3 de tech');
    // Back in, the dialog is not reopened; then an explicit logout.
    await logIn('tech');
    await useAuthStore().logout();
    expect(JSON.stringify(window.sessionStorage)).not.toContain('DRAFT-3');
    await logIn('sitea');
    expect(await reopened({ machineId: 'm-6' })).toBe('');
    await useAuthStore().logout();
    await logIn('tech');
    expect(await reopened({ machineId: 'm-6' })).toBe('');
  });

  it('gives the text of a selection back on that very selection only', async () => {
    await logIn('tech');
    await typeThenLoseSession({ machineIds: ['m-2', 'm-1'] }, 'Les deux postes du fond');
    await logIn('tech');
    expect(await reopened({ machineIds: ['m-3', 'm-4'] })).toBe('');
    expect(await reopened({ machineIds: ['m-1'] })).toBe('');
    expect(await reopened({ machineIds: ['m-1', 'm-2', 'm-3'] })).toBe('');
  });

  it('finds it again on the same postes, whatever the order they were ticked in', async () => {
    await logIn('tech');
    await typeThenLoseSession({ machineIds: ['m-2', 'm-1'] }, 'Les deux postes du fond');
    await logIn('tech');
    expect(await reopened({ machineIds: ['m-1', 'm-2'] })).toBe('Les deux postes du fond');
  });

  // The list empties its selection as soon as the requests are made, before
  // the dialog closes: the draft sent must go all the same.
  it('forgets the text of a selection once the request was sent', async () => {
    await logIn('tech');
    const form = await open({ machineIds: ['m-1', 'm-2'] });
    form.text.vm.$emit('update:modelValue', 'Les deux postes du fond');
    await flushPromises();
    expect(JSON.stringify(window.sessionStorage)).toContain('du fond');

    await form.wrapper.setProps({ machineIds: [] });
    await form.wrapper.setProps({ modelValue: false });
    await flushPromises();
    expect(JSON.stringify(window.sessionStorage)).not.toContain('du fond');
    form.wrapper.unmount();
    expect(await reopened({ machineIds: ['m-1', 'm-2'] })).toBe('');
  });

  it('keeps nothing for a form that knows neither its poste nor its selection', async () => {
    await logIn('tech');
    const form = await open({});
    form.text.vm.$emit('update:modelValue', 'Nulle part où le ranger');
    await flushPromises();
    expect(JSON.stringify(window.sessionStorage)).not.toContain('Nulle part');
    form.wrapper.unmount();
  });
});

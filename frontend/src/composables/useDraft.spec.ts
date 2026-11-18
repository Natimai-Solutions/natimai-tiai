// @vitest-environment jsdom
import { createPinia, setActivePinia } from 'pinia';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { nextTick, ref } from 'vue';

// The store's services reach the server through the app's axios instance.
vi.mock('src/services/auth', () => ({
  getMe: vi.fn(),
  login: vi.fn(),
  logout: vi.fn(),
  updateMe: vi.fn(),
}));

import type { User } from 'src/services/auth';
import { useAuthStore } from 'src/stores/auth';
import { DRAFT_PREFIX, forgetDrafts, forgetDraftsOfOthers } from 'src/utils/drafts';
import { useDraft } from './useDraft';

const account = (id: string) => ({ id, email: `${id}@x`, permissions: [] }) as unknown as User;

function draftKeys(): string[] {
  return Object.keys(sessionStorage).filter((k) => k.startsWith(DRAFT_PREFIX));
}

describe('useDraft (item 7)', () => {
  beforeEach(() => {
    sessionStorage.clear();
    setActivePinia(createPinia());
    useAuthStore().user = account('u-tech');
  });

  it('keeps what is typed, and gives it back to the form opened again', async () => {
    const instructions = ref('Écran noir au démarrage, vérifier');
    const assignee = ref<string | null>('u-2');
    useDraft('check-request:m-1', { instructions, assignee });
    instructions.value += ' le câble';
    await nextTick();
    expect(sessionStorage.getItem(`${DRAFT_PREFIX}u-tech.check-request:m-1`)).toContain('le câble');

    // The page reloaded after the session ended: a fresh form, empty.
    const again = ref('');
    const who = ref<string | null>(null);
    const draft = useDraft('check-request:m-1', { instructions: again, assignee: who });
    expect(draft.restore()).toBe(true);
    expect(again.value).toBe('Écran noir au démarrage, vérifier le câble');
    expect(who.value).toBe('u-2');
  });

  it('forgets the draft once the form was sent, and keeps drafts apart by key', async () => {
    const text = ref('a');
    const draft = useDraft(() => 'check-request:m-1', { text });
    text.value = 'b';
    await nextTick();
    expect(useDraft('check-request:m-2', { text: ref('') }).restore()).toBe(false);
    draft.clear();
    expect(useDraft('check-request:m-1', { text: ref('') }).restore()).toBe(false);
  });

  // Review finding 1: a draft is its author's, on a tab two accounts share.
  it('never gives the draft of one account to another', async () => {
    const text = ref('');
    useDraft('check-request:m-1', { text });
    text.value = 'Voir M. Dupont';
    await nextTick();

    useAuthStore().user = account('u-sitea');
    const theirs = ref('');
    expect(useDraft('check-request:m-1', { text: theirs }).restore()).toBe(false);
    expect(theirs.value).toBe('');

    // And its author still finds it.
    useAuthStore().user = account('u-tech');
    const mine = ref('');
    expect(useDraft('check-request:m-1', { text: mine }).restore()).toBe(true);
    expect(mine.value).toBe('Voir M. Dupont');
  });

  it('keeps nothing while no account is known, nor without a key', async () => {
    useAuthStore().user = null;
    const text = ref('');
    const anonymous = useDraft('check-request:m-1', { text });
    text.value = 'x';
    await nextTick();
    expect(draftKeys()).toEqual([]);
    expect(anonymous.restore()).toBe(false);

    useAuthStore().user = account('u-tech');
    const other = ref('');
    const keyless = useDraft(() => null, { text: other });
    other.value = 'y';
    await nextTick();
    expect(draftKeys()).toEqual([]);
    expect(keyless.restore()).toBe(false);
  });

  // The bulk form: one slot, good for the selection it was typed for only.
  it('gives a scoped draft back to the very same scope only', async () => {
    const scope = ref('m-1,m-2');
    const text = ref('');
    useDraft('check-request:selection', { text }, { scope: () => scope.value });
    text.value = 'Les deux postes du fond';
    await nextTick();

    const reopen = (s: string) => {
      const again = ref('');
      const restored = useDraft(
        'check-request:selection',
        { text: again },
        { scope: () => s },
      ).restore();
      return { restored, value: again.value };
    };
    expect(reopen('m-1,m-3')).toEqual({ restored: false, value: '' });
    expect(reopen('m-1')).toEqual({ restored: false, value: '' });
    expect(reopen('m-1,m-2')).toEqual({ restored: true, value: 'Les deux postes du fond' });
  });

  it('forgets every draft, or those of the other accounts', async () => {
    const text = ref('');
    useDraft('a', { text });
    text.value = 'tech';
    await nextTick();
    useAuthStore().user = account('u-sitea');
    const theirs = ref('');
    useDraft('a', { text: theirs });
    theirs.value = 'sitea';
    await nextTick();
    // A draft written by the version before: no owner in its key.
    sessionStorage.setItem(`${DRAFT_PREFIX}check-request:m-9`, '{"instructions":"vieux"}');
    sessionStorage.setItem('other', 'kept');
    expect(draftKeys()).toHaveLength(3);

    forgetDraftsOfOthers('u-sitea');
    expect(draftKeys()).toEqual([`${DRAFT_PREFIX}u-sitea.a`]);
    forgetDrafts();
    expect(draftKeys()).toEqual([]);
    expect(sessionStorage.getItem('other')).toBe('kept');
  });
});

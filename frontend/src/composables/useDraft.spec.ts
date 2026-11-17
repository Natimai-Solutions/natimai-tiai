// @vitest-environment jsdom
import { beforeEach, describe, expect, it } from 'vitest';
import { nextTick, ref } from 'vue';
import { DRAFT_PREFIX, useDraft } from './useDraft';

describe('useDraft (item 7)', () => {
  beforeEach(() => sessionStorage.clear());

  it('keeps what is typed, and gives it back to the form opened again', async () => {
    const instructions = ref('Écran noir au démarrage, vérifier');
    const assignee = ref<string | null>('u-2');
    useDraft('check-request:m-1', { instructions, assignee });
    instructions.value += ' le câble';
    await nextTick();
    expect(sessionStorage.getItem(`${DRAFT_PREFIX}check-request:m-1`)).toContain('le câble');

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
});

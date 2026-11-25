import { flushPromises, mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import { QForm } from 'quasar';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const shown = vi.hoisted(() => [] as { type?: string; message?: string }[]);
vi.mock('src/utils/notify', () => ({
  notify: (_q: unknown, build: () => { type?: string; message?: string }) => {
    shown.push(build());
    return () => undefined;
  },
}));
const dialogs = vi.hoisted(() => [] as { message?: string }[]);
vi.mock('src/utils/liveDialog', () => ({
  liveDialog: (_q: unknown, build: () => { message?: string }) => {
    dialogs.push(build());
    return { onOk: (ok: () => void) => ok() };
  },
}));
vi.mock('src/services/procedures', async (importOriginal) => ({
  ...(await importOriginal<typeof import('src/services/procedures')>()),
  getMachineProcedure: vi.fn(),
  listProcedures: vi.fn(),
  createProcedure: vi.fn(),
  updateProcedure: vi.fn(),
  deleteProcedure: vi.fn(),
}));

import { setLocale } from 'src/i18n';
import {
  createProcedure,
  deleteProcedure,
  getMachineProcedure,
  updateProcedure,
  type MachineProcedure,
  type Procedure,
} from 'src/services/procedures';
import { useAuthStore } from 'src/stores/auth';
import MachineProcedureCard from './MachineProcedureCard.vue';

const NOTE: Procedure = {
  id: 'p1',
  hw_model: 'OptiPlex 7090',
  body: 'BIOS : F2 au démarrage\nBoot : F12',
  created_by: 'alice@x',
  created_at: '2026-11-20T08:00:00Z',
  updated_by: 'bob@x',
  updated_at: '2026-11-24T08:00:00Z',
};

function answer(fields: Partial<MachineProcedure> = {}): MachineProcedure {
  return { hw_model: 'OptiPlex 7090', procedure: NOTE, scope_limited: false, ...fields };
}

async function mountCard(permissions: string[] = ['procedure:read', 'procedure:write']) {
  setActivePinia(createPinia());
  useAuthStore().user = { id: 'me', email: 'a@b.c', permissions } as never;
  const wrapper = mount(MachineProcedureCard, {
    props: { machineId: 'm1' },
    attachTo: document.body,
  });
  await flushPromises();
  return wrapper;
}

beforeEach(() => {
  shown.length = 0;
  dialogs.length = 0;
  setLocale('fr');
  vi.mocked(getMachineProcedure).mockReset();
  vi.mocked(createProcedure).mockReset();
  vi.mocked(updateProcedure).mockReset();
  vi.mocked(deleteProcedure).mockReset();
});

describe('MachineProcedureCard', () => {
  it('shows the note of the model, line breaks kept, and who edited it last', async () => {
    vi.mocked(getMachineProcedure).mockResolvedValue(answer());
    const wrapper = await mountCard();
    expect(getMachineProcedure).toHaveBeenCalledWith('m1');
    expect(wrapper.text()).toContain('Procédure pour ce modèle — OptiPlex 7090');
    const body = wrapper.find('[data-test="procedure-body-text"]');
    expect(body.attributes('style')).toContain('white-space: pre-line');
    expect(body.text()).toContain('BIOS : F2 au démarrage');
    expect(wrapper.text()).toContain('Modifiée par bob@x le');
    expect(wrapper.find('[data-test="procedure-edit"]').exists()).toBe(true);
    wrapper.unmount();
  });

  it('without a note, offers to write it to whoever may', async () => {
    vi.mocked(getMachineProcedure).mockResolvedValue(answer({ procedure: null }));
    const wrapper = await mountCard();
    expect(wrapper.find('[data-test="procedure-none"]').text()).toBe(
      'Aucune procédure pour ce modèle.',
    );
    expect(wrapper.find('[data-test="procedure-write"]').exists()).toBe(true);
    wrapper.unmount();
  });

  it('without procedure:write, reads only', async () => {
    vi.mocked(getMachineProcedure).mockResolvedValue(answer({ procedure: null }));
    const wrapper = await mountCard(['procedure:read']);
    expect(wrapper.find('[data-test="procedure-write"]').exists()).toBe(false);
    wrapper.unmount();
    vi.mocked(getMachineProcedure).mockResolvedValue(answer());
    const other = await mountCard(['procedure:read']);
    expect(other.find('[data-test="procedure-edit"]').exists()).toBe(false);
    expect(other.find('[data-test="procedure-delete"]').exists()).toBe(false);
    other.unmount();
  });

  it('a confined account has no writing button, and is told why', async () => {
    vi.mocked(getMachineProcedure).mockResolvedValue(
      answer({ procedure: null, scope_limited: true }),
    );
    const wrapper = await mountCard();
    expect(wrapper.find('[data-test="procedure-write"]').exists()).toBe(false);
    expect(wrapper.find('[data-test="procedure-scope-limited"]').text()).toContain(
      'seuls les comptes sans limite de lieux les rédigent',
    );
    wrapper.unmount();
  });

  it('an unknown model: said so, and no button', async () => {
    vi.mocked(getMachineProcedure).mockResolvedValue({ hw_model: null, procedure: null });
    const wrapper = await mountCard();
    expect(wrapper.find('[data-test="procedure-unknown"]').text()).toContain(
      'Modèle inconnu (inventaire non remonté)',
    );
    expect(wrapper.find('[data-test="procedure-write"]').exists()).toBe(false);
    wrapper.unmount();
  });

  it('writes the first note of the model, warned against secrets', async () => {
    vi.mocked(getMachineProcedure).mockResolvedValue(answer({ procedure: null }));
    vi.mocked(createProcedure).mockResolvedValue(NOTE);
    const wrapper = await mountCard();
    await wrapper.find('[data-test="procedure-write"]').trigger('click');
    await flushPromises();
    expect(document.body.querySelector('[data-test="procedure-secrets"]')!.textContent).toContain(
      'N’écrivez ni mot de passe ni secret',
    );
    const textarea = document.body.querySelector('.q-dialog textarea') as HTMLTextAreaElement;
    textarea.value = '  F10 pour le BIOS  ';
    textarea.dispatchEvent(new Event('input'));
    await flushPromises();
    vi.mocked(getMachineProcedure).mockResolvedValue(answer());
    wrapper.findComponent(QForm).vm.$emit('submit', new Event('submit'));
    await flushPromises();
    expect(createProcedure).toHaveBeenCalledWith('OptiPlex 7090', 'F10 pour le BIOS');
    expect(shown.at(-1)!.message).toBe('Procédure enregistrée');
    // Read again: the card shows the note now.
    expect(getMachineProcedure).toHaveBeenCalledTimes(2);
    wrapper.unmount();
  });

  it('an edit from a version changed meanwhile reads it again and says so', async () => {
    vi.mocked(getMachineProcedure).mockResolvedValue(answer());
    vi.mocked(updateProcedure).mockRejectedValue({
      response: { status: 409, data: { error: { code: 'procedure.changed' } } },
    });
    const wrapper = await mountCard();
    await wrapper.find('[data-test="procedure-edit"]').trigger('click');
    await flushPromises();
    wrapper.findComponent(QForm).vm.$emit('submit', new Event('submit'));
    await flushPromises();
    expect(updateProcedure).toHaveBeenCalledWith('p1', NOTE.body, NOTE.updated_at);
    expect(shown.at(-1)).toEqual({
      type: 'warning',
      message: expect.stringContaining('modifiée ou supprimée entre-temps'),
    });
    expect(getMachineProcedure).toHaveBeenCalledTimes(2);
    wrapper.unmount();
  });

  it('deletes the note once confirmed, naming the version it was read at', async () => {
    vi.mocked(getMachineProcedure).mockResolvedValue(answer());
    vi.mocked(deleteProcedure).mockResolvedValue();
    const wrapper = await mountCard();
    vi.mocked(getMachineProcedure).mockResolvedValue(answer({ procedure: null }));
    await wrapper.find('[data-test="procedure-delete"]').trigger('click');
    await flushPromises();
    expect(dialogs[0]!.message).toContain('« OptiPlex 7090 »');
    expect(deleteProcedure).toHaveBeenCalledWith('p1', NOTE.updated_at);
    expect(wrapper.find('[data-test="procedure-none"]').exists()).toBe(true);
    wrapper.unmount();
  });

  it('reads in English', async () => {
    setLocale('en');
    vi.mocked(getMachineProcedure).mockResolvedValue(answer({ procedure: null }));
    const wrapper = await mountCard();
    expect(wrapper.text()).toContain('Procedure for this model — OptiPlex 7090');
    expect(wrapper.text()).toContain('No procedure for this model.');
    expect(wrapper.text()).toContain('Write the procedure');
    expect(wrapper.text()).toContain('All procedures');
    wrapper.unmount();
  });
});

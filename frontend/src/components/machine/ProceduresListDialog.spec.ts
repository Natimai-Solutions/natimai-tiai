import { flushPromises, mount } from '@vue/test-utils';
import { QExpansionItem } from 'quasar';
import { beforeEach, describe, expect, it, vi } from 'vitest';

// QExpansionItem slides open with the Web Animations API, which the test DOM
// lacks: a stand-in that finishes at once.
if (!('animate' in Element.prototype)) {
  Object.defineProperty(Element.prototype, 'animate', {
    configurable: true,
    value: () => ({ cancel: () => undefined, reverse: () => undefined, onfinish: null }),
  });
}

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
  listProcedures: vi.fn(),
  deleteProcedure: vi.fn(),
  updateProcedure: vi.fn(),
  createProcedure: vi.fn(),
}));

import { setLocale } from 'src/i18n';
import { QForm } from 'quasar';
import {
  createProcedure,
  deleteProcedure,
  listProcedures,
  updateProcedure,
  type ProcedureListItem,
} from 'src/services/procedures';
import ProcedureEditDialog from './ProcedureEditDialog.vue';
import ProceduresListDialog from './ProceduresListDialog.vue';

function note(fields: Partial<ProcedureListItem>): ProcedureListItem {
  return {
    id: 'p1',
    hw_model: 'OptiPlex 7090',
    body: 'F2 pour le BIOS',
    created_by: 'alice@x',
    created_at: '2026-11-20T08:00:00Z',
    updated_by: 'bob@x',
    updated_at: '2026-11-24T08:00:00Z',
    machine_count: 12,
    ...fields,
  };
}

const ACTIVE = note({});
const ORPHAN = note({ id: 'p2', hw_model: 'Vieux 1', body: 'Plus de poste', machine_count: 0 });

/** Open a row (the dialog is teleported: reached through its components). */
async function openRow(wrapper: ReturnType<typeof mountList>, index: number) {
  await wrapper.findAllComponents(QExpansionItem)[index]!.find('.q-item').trigger('click');
  await flushPromises();
}

function button(test: string): HTMLElement | null {
  const all = document.body.querySelectorAll<HTMLElement>(`[data-test="${test}"]`);
  return all.length ? all[all.length - 1]! : null;
}

function mountList(canWrite = true) {
  return mount(ProceduresListDialog, {
    props: { modelValue: true, canWrite },
    attachTo: document.body,
  });
}

beforeEach(() => {
  shown.length = 0;
  dialogs.length = 0;
  setLocale('fr');
  vi.mocked(listProcedures).mockReset();
  vi.mocked(deleteProcedure).mockReset();
  vi.mocked(updateProcedure).mockReset();
  vi.mocked(createProcedure).mockReset();
});

/** Open the first row's edit dialog and submit it. */
async function editAndSave(wrapper: ReturnType<typeof mountList>) {
  await openRow(wrapper, 0);
  button('procedure-row-edit')!.click();
  await flushPromises();
}

async function save(wrapper: ReturnType<typeof mountList>) {
  wrapper
    .findComponent(ProcedureEditDialog)
    .findComponent(QForm)
    .vm.$emit('submit', new Event('submit'));
  await flushPromises();
}

const CHANGED = {
  response: { status: 409, data: { error: { code: 'procedure.changed' } } },
};

describe('ProceduresListDialog', () => {
  it('lists every note with its postes in service and its last edit', async () => {
    vi.mocked(listProcedures).mockResolvedValue([ACTIVE, ORPHAN]);
    const wrapper = mountList();
    await flushPromises();
    const rows = wrapper.findAllComponents(QExpansionItem);
    expect(rows.map((r) => r.props('label'))).toEqual(['OptiPlex 7090', 'Vieux 1']);
    expect(rows[0]!.props('caption')).toContain('12 poste(s) en service');
    expect(rows[0]!.props('caption')).toContain('par bob@x');
    expect(rows[1]!.props('caption')).toContain('aucun poste');
    wrapper.unmount();
  });

  it('opens a note to read it, and its edit dialog from there', async () => {
    vi.mocked(listProcedures).mockResolvedValue([ACTIVE]);
    const wrapper = mountList();
    await flushPromises();
    await openRow(wrapper, 0);
    expect(document.body.textContent).toContain('F2 pour le BIOS');
    button('procedure-row-edit')!.click();
    await flushPromises();
    const edit = wrapper.findComponent(ProcedureEditDialog);
    expect(edit.props('procedure')).toEqual(ACTIVE);
    expect(edit.props('modelValue')).toBe(true);
    wrapper.unmount();
  });

  it('deletes the note of a model without a poste, and reads the list again', async () => {
    vi.mocked(listProcedures).mockResolvedValue([ACTIVE, ORPHAN]);
    vi.mocked(deleteProcedure).mockResolvedValue();
    const wrapper = mountList();
    await flushPromises();
    await openRow(wrapper, 1);
    vi.mocked(listProcedures).mockResolvedValue([ACTIVE]);
    button('procedure-row-delete')!.click();
    await flushPromises();
    expect(dialogs[0]!.message).toContain('« Vieux 1 »');
    expect(deleteProcedure).toHaveBeenCalledWith('p2', ORPHAN.updated_at);
    expect(shown.at(-1)!.message).toBe('Procédure supprimée');
    expect(listProcedures).toHaveBeenCalledTimes(2);
    expect(wrapper.findAllComponents(QExpansionItem)).toHaveLength(1);
    expect(wrapper.emitted('changed')).toHaveLength(1);
    wrapper.unmount();
  });

  it('offers no writing to whoever may not write', async () => {
    vi.mocked(listProcedures).mockResolvedValue([ACTIVE]);
    const wrapper = mountList(false);
    await flushPromises();
    await openRow(wrapper, 0);
    expect(document.body.textContent).toContain('F2 pour le BIOS');
    expect(button('procedure-row-edit')).toBeNull();
    expect(button('procedure-row-delete')).toBeNull();
    wrapper.unmount();
  });

  it('counts in English', async () => {
    setLocale('en');
    vi.mocked(listProcedures).mockResolvedValue([ACTIVE, note({ id: 'p3', machine_count: 1 })]);
    const wrapper = mountList();
    await flushPromises();
    const rows = wrapper.findAllComponents(QExpansionItem);
    expect(rows[0]!.props('caption')).toContain('12 computers in service');
    expect(rows[1]!.props('caption')).toContain('1 computer in service');
    expect(rows[0]!.props('caption')).toContain('edited on');
    wrapper.unmount();
  });

  it('after a 409, the next save names the version read again', async () => {
    vi.mocked(listProcedures).mockResolvedValue([ACTIVE]);
    const wrapper = mountList();
    await flushPromises();
    await editAndSave(wrapper);
    const newer = note({ updated_at: '2026-11-25T09:00:00Z', body: 'F12 pour le boot' });
    vi.mocked(listProcedures).mockResolvedValue([newer]);
    vi.mocked(updateProcedure).mockRejectedValueOnce(CHANGED).mockResolvedValueOnce(newer);
    await save(wrapper);
    expect(updateProcedure).toHaveBeenNthCalledWith(1, 'p1', ACTIVE.body, ACTIVE.updated_at);
    expect(shown.at(-1)!.type).toBe('warning');
    const edit = wrapper.findComponent(ProcedureEditDialog);
    expect(edit.props('modelValue')).toBe(true);
    expect(edit.props('procedure')).toEqual(newer);
    await save(wrapper);
    // What was typed is kept; the version named is the one read again.
    expect(updateProcedure).toHaveBeenNthCalledWith(2, 'p1', ACTIVE.body, newer.updated_at);
    expect(shown.at(-1)!.message).toBe('Procédure modifiée');
    wrapper.unmount();
  });

  it('a note deleted meanwhile is written anew for its model on the next save', async () => {
    vi.mocked(listProcedures).mockResolvedValue([ACTIVE]);
    const wrapper = mountList();
    await flushPromises();
    await editAndSave(wrapper);
    vi.mocked(listProcedures).mockResolvedValue([]);
    vi.mocked(updateProcedure).mockRejectedValueOnce({
      response: { status: 404, data: { error: { code: 'procedure.not_found' } } },
    });
    vi.mocked(createProcedure).mockResolvedValue(note({ id: 'p9' }));
    await save(wrapper);
    const edit = wrapper.findComponent(ProcedureEditDialog);
    expect(edit.props('modelValue')).toBe(true);
    expect(edit.props('procedure')).toBeNull();
    expect(edit.props('hwModel')).toBe('OptiPlex 7090');
    await save(wrapper);
    expect(updateProcedure).toHaveBeenCalledTimes(1);
    expect(createProcedure).toHaveBeenCalledWith('OptiPlex 7090', ACTIVE.body);
    wrapper.unmount();
  });
});

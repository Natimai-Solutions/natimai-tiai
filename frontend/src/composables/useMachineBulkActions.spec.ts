import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ref } from 'vue';

// `$q` is the composable's only window on the screen: a stand-in records what
// it was asked to say and to confirm, and lets a test press « OK ».
const q = vi.hoisted(() => {
  const state = { onOk: null as null | (() => void) };
  return {
    state,
    notify: vi.fn(),
    dialog: vi.fn(() => ({
      onOk: (fn: () => void) => {
        state.onOk = fn;
      },
    })),
  };
});
vi.mock('quasar', () => ({ useQuasar: () => q }));
vi.mock('boot/axios', () => ({ api: {} }));
vi.mock('src/services/checks', async (importOriginal) => ({
  ...(await importOriginal<typeof import('src/services/checks')>()),
  createChecksBulk: vi.fn(),
}));
vi.mock('src/services/commands', async (importOriginal) => ({
  ...(await importOriginal<typeof import('src/services/commands')>()),
  createCommands: vi.fn(),
}));
vi.mock('src/services/machines', async (importOriginal) => ({
  ...(await importOriginal<typeof import('src/services/machines')>()),
  wakeMachines: vi.fn(),
}));
vi.mock('src/services/rooms', async (importOriginal) => ({
  ...(await importOriginal<typeof import('src/services/rooms')>()),
  placeMachines: vi.fn(),
  unassignMachines: vi.fn(),
}));

import { createChecksBulk } from 'src/services/checks';
import { commandActions, createCommands, type CommandAction } from 'src/services/commands';
import { wakeMachines, type Machine } from 'src/services/machines';
import { placeMachines, unassignMachines } from 'src/services/rooms';
import { useMachineBulkActions } from './useMachineBulkActions';

const action = (pick: (a: CommandAction) => boolean) => commandActions.find(pick)!;

function setup(ids: string[] = ['m-1', 'm-2']) {
  const selected = ref(ids.map((id) => ({ id }) as Machine));
  const reload = vi.fn().mockResolvedValue(undefined);
  const onPlaced = vi.fn();
  const bulk = useMachineBulkActions({ selected, reload, onPlaced });
  return { selected, reload, onPlaced, ...bulk };
}

describe('useMachineBulkActions', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    q.state.onOk = null;
  });

  describe('runBulk', () => {
    it('sends an unconfirmed command at once, then empties the selection', async () => {
      vi.mocked(createCommands).mockResolvedValue({ count: 2, skipped: 0 } as never);
      const { selected, runBulk } = setup();
      const quick = action((a) => !a.confirm && !a.serverSide && a.bulk);

      runBulk(quick);
      await vi.waitFor(() => expect(selected.value).toEqual([]));

      expect(createCommands).toHaveBeenCalledWith({
        type: quick.type,
        machine_ids: ['m-1', 'm-2'],
      });
      expect(q.dialog).not.toHaveBeenCalled();
      expect(q.notify).toHaveBeenCalledWith({
        type: 'positive',
        message: '2 commande(s) envoyée(s)',
      });
    });

    it('asks first for a costly one, with the count — and sends nothing until « OK »', async () => {
      vi.mocked(createCommands).mockResolvedValue({ count: 2, skipped: 0 } as never);
      const { runBulk } = setup();
      const costly = action((a) => a.confirm && !a.serverSide && a.bulk);

      runBulk(costly);

      expect(q.dialog).toHaveBeenCalledWith(
        expect.objectContaining({
          title: costly.label,
          message: expect.stringContaining(`sur 2 poste(s) ?`),
          persistent: true,
        }),
      );
      expect(createCommands).not.toHaveBeenCalled();
      q.state.onOk!();
      await vi.waitFor(() => expect(createCommands).toHaveBeenCalledOnce());
    });

    it('wakes through the server rather than queueing a command', async () => {
      vi.mocked(wakeMachines).mockResolvedValue({ results: [] } as never);
      const { selected, runBulk } = setup();
      const wake = action((a) => !!a.serverSide);

      runBulk({ ...wake, confirm: false });
      await vi.waitFor(() => expect(selected.value).toEqual([]));

      expect(wakeMachines).toHaveBeenCalledWith(['m-1', 'm-2']);
      expect(createCommands).not.toHaveBeenCalled();
    });

    it('keeps the selection and says so when the server refuses', async () => {
      vi.mocked(createCommands).mockRejectedValue(new Error('down'));
      vi.mocked(wakeMachines).mockRejectedValue(new Error('down'));
      const { selected, runBulk } = setup();

      runBulk(action((a) => !a.confirm && !a.serverSide && a.bulk));
      runBulk({ ...action((a) => !!a.serverSide), confirm: false });
      await vi.waitFor(() => expect(q.notify).toHaveBeenCalledTimes(2));

      expect(q.notify.mock.calls.map(([n]) => (n as { type: string }).type)).toEqual([
        'negative',
        'negative',
      ]);
      expect(selected.value).toHaveLength(2);
    });

    it('does nothing without a selection', () => {
      const { runBulk } = setup([]);
      runBulk(action((a) => a.confirm));
      expect(q.dialog).not.toHaveBeenCalled();
    });
  });

  describe('askSelection', () => {
    it('asks on every selected poste, then empties the selection and reloads', async () => {
      vi.mocked(createChecksBulk).mockResolvedValue({ created: 2, skipped: 0 });
      const { selected, reload, askSelection } = setup();
      const payload = { assigned_to_id: null, instructions: 'Écran' };

      await askSelection(payload);

      expect(createChecksBulk).toHaveBeenCalledWith(['m-1', 'm-2'], payload);
      expect(selected.value).toEqual([]);
      expect(reload).toHaveBeenCalledOnce();
    });

    it('lets a failure reach the dialog, which says it and stays open', async () => {
      vi.mocked(createChecksBulk).mockRejectedValue(new Error('down'));
      const { askSelection } = setup();
      await expect(askSelection({ assigned_to_id: null, instructions: null })).rejects.toThrow();
    });
  });

  describe('placeSelection', () => {
    it('places the selection in a room, closes, reloads and recounts the rooms', async () => {
      vi.mocked(placeMachines).mockResolvedValue({ moved: 2, mismatched: [] });
      const { selected, reload, onPlaced, placeOpen, placeSelection } = setup();
      placeOpen.value = true;

      await placeSelection('r-1');

      expect(placeMachines).toHaveBeenCalledWith('r-1', ['m-1', 'm-2']);
      expect(q.notify).toHaveBeenCalledWith({ type: 'positive', message: '2 poste(s) affecté(s)' });
      expect(placeOpen.value).toBe(false);
      expect(selected.value).toEqual([]);
      expect(reload).toHaveBeenCalledOnce();
      expect(onPlaced).toHaveBeenCalledOnce();
    });

    it('unassigns on « Sans salle »', async () => {
      vi.mocked(unassignMachines).mockResolvedValue({ moved: 2, mismatched: [] });
      const { placeSelection } = setup();
      await placeSelection('none');
      expect(unassignMachines).toHaveBeenCalledWith(['m-1', 'm-2']);
      expect(placeMachines).not.toHaveBeenCalled();
    });

    it('says a refusal and keeps the dialog open on the selection', async () => {
      vi.mocked(placeMachines).mockRejectedValue(new Error('down'));
      const { selected, placeOpen, placeSelection } = setup();
      placeOpen.value = true;

      await placeSelection('r-1');

      expect(q.notify).toHaveBeenCalledWith(expect.objectContaining({ type: 'negative' }));
      expect(placeOpen.value).toBe(true);
      expect(selected.value).toHaveLength(2);
    });

    it('does nothing until a room is picked', async () => {
      const { placeSelection } = setup();
      await placeSelection(null);
      expect(placeMachines).not.toHaveBeenCalled();
      expect(unassignMachines).not.toHaveBeenCalled();
    });
  });
});

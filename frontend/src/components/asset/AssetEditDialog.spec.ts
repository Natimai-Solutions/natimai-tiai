import { flushPromises, mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import { QForm, QInput, QSelect } from 'quasar';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('src/services/assets', async (importOriginal) => ({
  ...(await importOriginal<typeof import('src/services/assets')>()),
  putMachineAsset: vi.fn(),
  updateAsset: vi.fn(),
  createEquipment: vi.fn(),
}));
vi.mock('src/services/rooms', async (importOriginal) => ({
  ...(await importOriginal<typeof import('src/services/rooms')>()),
  listRooms: vi.fn(),
}));

import {
  createEquipment,
  putMachineAsset,
  updateAsset,
  type Asset,
  type AssetPayload,
} from 'src/services/assets';
import { listRooms, type Room } from 'src/services/rooms';
import AssetEditDialog from './AssetEditDialog.vue';

type Props = { asset: Asset | null; machineId?: string | null };

async function open(props: Props) {
  const wrapper = mount(AssetEditDialog, {
    props: { modelValue: false, ...props },
    attachTo: document.body,
  });
  await wrapper.setProps({ modelValue: true });
  await flushPromises();
  const input = (label: string) =>
    wrapper.findAllComponents(QInput).find((i) => i.props('label') === label)!;
  const select = (label: string) =>
    wrapper.findAllComponents(QSelect).find((i) => i.props('label') === label)!;
  const type = async (label: string, value: string) => {
    input(label).vm.$emit('update:modelValue', value);
    await flushPromises();
  };
  const pick = async (label: string, value: string) => {
    select(label).vm.$emit('update:modelValue', value);
    await flushPromises();
  };
  const submit = async () => {
    await wrapper.findComponent(QForm).trigger('submit');
    await flushPromises();
  };
  return { wrapper, input, type, pick, submit };
}

function sent(fn: unknown): AssetPayload {
  const calls = vi.mocked(fn as (...args: unknown[]) => unknown).mock.calls;
  return calls[calls.length - 1]!.at(-1) as AssetPayload;
}

describe('AssetEditDialog', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    document.body.innerHTML = '';
    vi.mocked(putMachineAsset)
      .mockReset()
      .mockResolvedValue({} as Asset);
    vi.mocked(updateAsset)
      .mockReset()
      .mockResolvedValue({} as Asset);
    vi.mocked(createEquipment)
      .mockReset()
      .mockResolvedValue({} as Asset);
    vi.mocked(listRooms).mockResolvedValue([
      { id: 'r-1', name: 'A101', building: null } as unknown as Room,
    ]);
  });

  it('writes a poste’s asset under the poste, without the machine’s own fields', async () => {
    const { type, pick, submit, wrapper } = await open({ asset: null, machineId: 'm-1' });
    // Typed while on loan, then put back in service: the loan goes.
    await pick('Statut', 'on_loan');
    await type('Prêté à', 'M. Teva');
    await pick('Statut', 'in_service');
    await type('Prix d’achat', '749,90');
    await type('N° d’inventaire', '  INV-1 ');
    await submit();
    expect(putMachineAsset).toHaveBeenCalledWith('m-1', expect.any(Object));
    const body = sent(putMachineAsset);
    expect(body).toMatchObject({
      status: 'in_service',
      borrower: null,
      loan_due: null,
      purchase_price: '749.90',
      inventory_number: 'INV-1',
      supplier: null,
    });
    for (const key of ['name', 'kind', 'room_id', 'manufacturer', 'model', 'serial_number'])
      expect(body, key).not.toHaveProperty(key);
    expect(wrapper.emitted('saved')).toHaveLength(1);
    wrapper.unmount();
  });

  it('keeps the loan while on loan', async () => {
    const { type, pick, submit, wrapper } = await open({ asset: null, machineId: 'm-1' });
    await pick('Statut', 'on_loan');
    await type('Prêté à', 'M. Teva');
    await type('Retour prévu', '2026-12-01');
    await submit();
    expect(sent(putMachineAsset)).toMatchObject({ borrower: 'M. Teva', loan_due: '2026-12-01' });
    wrapper.unmount();
  });

  it('reads a price as typed, spaces and all, and refuses an ambiguous one', async () => {
    const first = await open({ asset: null, machineId: 'm-1' });
    await first.type('Prix d’achat', '1 200');
    await first.submit();
    expect(sent(putMachineAsset).purchase_price).toBe('1200');
    first.wrapper.unmount();

    vi.mocked(putMachineAsset).mockClear();
    const second = await open({ asset: null, machineId: 'm-1' });
    await second.type('Prix d’achat', '1.234,50');
    expect(second.input('Prix d’achat').props('error')).toBe(true);
    await second.submit();
    expect(putMachineAsset).not.toHaveBeenCalled();
    second.wrapper.unmount();
  });

  it('creates equipment with its name, type and room', async () => {
    const { type, pick, submit, wrapper } = await open({ asset: null });
    await type('Nom', '  Vidéoprojecteur A101 ');
    await pick('Type', 'projector');
    await pick('Salle', 'r-1');
    await type('N° de série', 'EPS-9');
    await submit();
    expect(createEquipment).toHaveBeenCalledTimes(1);
    expect(sent(createEquipment)).toMatchObject({
      name: 'Vidéoprojecteur A101',
      kind: 'projector',
      room_id: 'r-1',
      serial_number: 'EPS-9',
    });
    expect(putMachineAsset).not.toHaveBeenCalled();
    wrapper.unmount();
  });

  it('updates existing equipment by its id', async () => {
    const asset = {
      id: 'a-1',
      machine_id: null,
      kind: 'printer',
      name: 'Imprimante',
      room_id: 'r-1',
      status: 'in_service',
    } as unknown as Asset;
    const { pick, submit, wrapper } = await open({ asset });
    await pick('Statut', 'in_repair');
    await submit();
    expect(updateAsset).toHaveBeenCalledWith('a-1', expect.any(Object));
    expect(sent(updateAsset)).toMatchObject({
      name: 'Imprimante',
      kind: 'printer',
      status: 'in_repair',
    });
    wrapper.unmount();
  });
});

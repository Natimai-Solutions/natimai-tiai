import { mount } from '@vue/test-utils';
import { QBadge, QItem, QLinearProgress } from 'quasar';
import { describe, expect, it } from 'vitest';
import MachineStorageCard from './MachineStorageCard.vue';
import type { Disk, MachineDetail, Volume } from 'src/services/machines';
import { machineDetail } from 'src/test/fixtures';

function volume(overrides: Partial<Volume> = {}): Volume {
  return {
    id: 1,
    letter: 'C:',
    label: 'Système',
    filesystem: 'NTFS',
    total_mb: 512_000,
    free_mb: 51_200,
    is_system: true,
    encryption_status: 'FullyEncrypted',
    ...overrides,
  };
}

function disk(overrides: Partial<Disk> = {}): Disk {
  return {
    id: 1,
    device_id: 'PHYSICALDRIVE0',
    model: 'Samsung 980',
    serial: 'S123',
    firmware: null,
    media_type: 'SSD',
    bus_type: 'NVMe',
    size_mb: 512_000,
    health_status: 'Healthy',
    is_removable: false,
    ...overrides,
  };
}

function mountCard(overrides: Partial<MachineDetail>) {
  return mount(MachineStorageCard, { props: { machine: machineDetail(overrides) } });
}

const badges = (wrapper: ReturnType<typeof mountCard>) =>
  wrapper.findAllComponents(QBadge).map((b) => b.props('label') as string);

describe('MachineStorageCard', () => {
  it('shows each volume with its free space, as a figure and as a used bar', () => {
    const wrapper = mountCard({ volumes: [volume()], disks: [] });

    expect(wrapper.text()).toContain('C:');
    expect(wrapper.text()).toContain('50 Gio libres sur 500 Gio');
    expect(wrapper.text()).toContain('(10 %)');
    expect(wrapper.findComponent(QLinearProgress).props('value')).toBeCloseTo(0.9);
  });

  it('badges the system volume and its encryption', () => {
    const wrapper = mountCard({
      volumes: [
        volume(),
        volume({ id: 2, letter: 'D:', is_system: false, encryption_status: null }),
      ],
      disks: [],
    });

    expect(badges(wrapper)).toEqual(['Système', 'Chiffré', 'Non relevé']);
  });

  it('says so when no volume was inventoried, and shows no disk section', () => {
    const wrapper = mountCard({ volumes: [], disks: [] });

    expect(wrapper.text()).toContain('Aucun volume relevé sur ce poste.');
    expect(wrapper.text()).not.toContain('Disques physiques');
  });

  it('lists the physical disks, flagging only an unhealthy one', () => {
    const wrapper = mountCard({
      volumes: [],
      disks: [
        disk(),
        disk({ id: 2, model: null, device_id: 'PHYSICALDRIVE1', health_status: 'Warning' }),
      ],
    });
    const items = wrapper.findAllComponents(QItem);

    expect(wrapper.text()).toContain('Disques physiques');
    expect(items[0]!.text()).toContain('Samsung 980');
    // No model: the device id stands in, rather than a blank line.
    expect(items[1]!.text()).toContain('PHYSICALDRIVE1');
    expect(badges(wrapper)).toEqual(['Warning']);
  });
});

import { mount } from '@vue/test-utils';
import { QIcon, QItem, QLinearProgress } from 'quasar';
import { describe, expect, it } from 'vitest';
import MachineStatusCard from './MachineStatusCard.vue';
import type { MachineDetail } from 'src/services/machines';
import { machineDetail } from 'src/test/fixtures';

function mountCard(overrides: Partial<MachineDetail> = {}, activeThreats = 0) {
  return mount(MachineStatusCard, {
    props: { machine: machineDetail(overrides), activeThreats },
  });
}

describe('MachineStatusCard', () => {
  it('says there is nothing to report on a healthy poste', () => {
    const wrapper = mountCard();

    expect(wrapper.text()).toContain('Aucune alerte sur ce poste.');
    expect(wrapper.findAllComponents(QItem)).toHaveLength(0);
  });

  it('reads the five facts at a glance', () => {
    const text = mountCard().text();

    expect(text).toContain('Windows Defender');
    expect(text).toContain('À jour');
    expect(text).toContain('alice');
    // 250 000 Mio free out of 500 000: half the system disk.
    expect(text).toContain('244 Gio libres (50 %)');
    expect(text).toContain('Poste allumé');
  });

  it('fills the disk bar with what is used', () => {
    const bar = mountCard({ system_volume_free_mb: 125_000 }).findComponent(QLinearProgress);
    expect(bar.props('value')).toBe(0.75);
  });

  it('says « Non relevé » for a disk the agent never measured', () => {
    const wrapper = mountCard({ system_volume_total_mb: null, system_volume_free_mb: null });

    expect(wrapper.findComponent(QLinearProgress).exists()).toBe(false);
    expect(wrapper.text()).toContain('Non relevé');
  });

  it('flags a pending restart next to Windows Update', () => {
    const icons = (m: Partial<MachineDetail>) =>
      mountCard(m)
        .findAllComponents(QIcon)
        .map((i) => i.props('name'));

    expect(icons({ wu_reboot_required: false })).not.toContain('restart_alt');
    expect(icons({ wu_reboot_required: true })).toContain('restart_alt');
  });

  it('lists the findings, the active threats first', () => {
    const wrapper = mountCard({ is_up_to_date: false }, 2);
    const items = wrapper.findAllComponents(QItem);

    expect(items.length).toBeGreaterThanOrEqual(2);
    expect(items[0]!.text()).toContain('2 menaces actives');
    expect(wrapper.text()).not.toContain('Aucune alerte');
  });

  it('opens the tab behind a finding when it is clicked', async () => {
    const wrapper = mountCard({ wu_pending_count: 3 }, 1);
    const items = wrapper.findAllComponents(QItem);

    await items[0]!.trigger('click');
    await items[items.length - 1]!.trigger('click');

    expect(wrapper.emitted('open-tab')).toEqual([['antivirus'], ['windows_update']]);
  });
});

describe('MachineStatusCard — threats unread and the parc threshold', () => {
  it('claims no all-clear when the threats could not be read', async () => {
    const w = mount(MachineStatusCard, {
      props: { machine: machineDetail(), activeThreats: 0, threatsFailed: true },
    });
    expect(w.text()).not.toContain('Aucune alerte');
    expect(w.text()).toContain('Impossible de charger les menaces de ce poste');
    await w.find('button').trigger('click');
    expect(w.emitted('retry')).toHaveLength(1);
  });

  // Item 9: the threshold set in « Paramètres », not a hard-coded 10 %.
  it('raises the disk alert at the parc’s threshold', () => {
    // Half the system disk free, with the parc's threshold at 51 %.
    const w = mount(MachineStatusCard, {
      props: { machine: machineDetail(), activeThreats: 0, lowDiskPercent: 51 },
    });
    expect(w.text()).toContain('Disque système presque plein');
    expect(w.findComponent(QLinearProgress).props('color')).toBe('negative');
  });
});

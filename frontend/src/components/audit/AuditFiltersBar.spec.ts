import { mount } from '@vue/test-utils';
import { QBtn, QChip, QInput, QSelect } from 'quasar';
import { describe, expect, it } from 'vitest';
import AuditFiltersBar from './AuditFiltersBar.vue';
import { emptyAuditFilters, type AuditFilters } from 'src/utils/auditQuery';

function mountBar(filters: Partial<AuditFilters> = {}, actions = ['machine.merge']) {
  return mount(AuditFiltersBar, {
    props: { modelValue: { ...emptyAuditFilters(), ...filters }, actions },
  });
}

function emitted(wrapper: ReturnType<typeof mountBar>): AuditFilters[] {
  return (wrapper.emitted('update:modelValue') ?? []).map((args) => args[0] as AuditFilters);
}

const byLabel = <T extends { props: (key: 'label') => unknown }>(items: T[], label: string) =>
  items.find((c) => c.props('label') === label)!;

describe('AuditFiltersBar', () => {
  describe('period', () => {
    it('flags an end day before the start day on the end field', () => {
      const wrapper = mountBar({ from: '2026-09-30', to: '2026-09-01' });
      const to = byLabel(wrapper.findAllComponents(QInput), 'Au (inclus)');

      expect(to.props('error')).toBe(true);
      expect(to.text()).toContain('Antérieure à la date de début');
    });

    it('says nothing of a period in the right order, or open on one side', () => {
      for (const period of [
        { from: '2026-09-01', to: '2026-09-30' },
        { from: '2026-09-01', to: '2026-09-01' },
        { from: '2026-09-30' },
      ]) {
        const wrapper = mountBar(period);
        const to = byLabel(wrapper.findAllComponents(QInput), 'Au (inclus)');
        expect(to.props('error')).toBe(false);
        expect(to.text()).not.toContain('Antérieure');
      }
    });

    it('bounds each day picker by the other day', () => {
      const wrapper = mountBar({ from: '2026-09-01', to: '2026-09-30' });
      const inputs = wrapper.findAll('input[type="date"]');
      expect(inputs[0]!.attributes('max')).toBe('2026-09-30');
      expect(inputs[1]!.attributes('min')).toBe('2026-09-01');
    });
  });

  it('clears the resource id when the resource type changes', () => {
    const wrapper = mountBar({ resourceType: 'machine', resourceId: 'abc', actor: 'marie@' });
    const type = byLabel(wrapper.findAllComponents(QSelect), 'Type de ressource');

    type.vm.$emit('update:modelValue', 'user');

    expect(emitted(wrapper)).toEqual([
      { ...emptyAuditFilters(), actor: 'marie@', resourceType: 'user', resourceId: null },
    ]);
  });

  it('reads a cleared field as no filter', () => {
    const wrapper = mountBar({ action: 'machine.merge', actor: 'marie@' });

    byLabel(wrapper.findAllComponents(QSelect), 'Action').vm.$emit('update:modelValue', null);
    byLabel(wrapper.findAllComponents(QInput), 'Auteur').vm.$emit('update:modelValue', null);

    expect(emitted(wrapper).map((f) => [f.action, f.actor])).toEqual([
      [null, 'marie@'],
      ['machine.merge', ''],
    ]);
  });

  it('shows the resource id as a chip, removed without touching the type', () => {
    const wrapper = mountBar({ resourceType: 'machine', resourceId: 'abc' });
    const chip = wrapper.findComponent(QChip);
    expect(chip.find('.q-chip__content').text()).toBe('Poste abc');

    chip.vm.$emit('remove');

    expect(emitted(wrapper)).toEqual([{ ...emptyAuditFilters(), resourceType: 'machine' }]);
  });

  it('offers a reset only when a filter is set, and it clears them all', async () => {
    expect(mountBar().findAllComponents(QBtn)).toHaveLength(0);

    const wrapper = mountBar({ actor: 'marie@', from: '2026-09-01' });
    await byLabel(wrapper.findAllComponents(QBtn), 'Réinitialiser les filtres').trigger('click');

    expect(emitted(wrapper)).toEqual([emptyAuditFilters()]);
  });

  it('keeps offering a selected action the log no longer holds', () => {
    const wrapper = mountBar({ action: 'machine.purged' }, ['machine.merge']);
    const options = byLabel(wrapper.findAllComponents(QSelect), 'Action').props('options') as {
      value: string;
    }[];
    expect(options.map((o) => o.value).sort()).toEqual(['machine.merge', 'machine.purged']);
  });
});

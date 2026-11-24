import { mount } from '@vue/test-utils';
import { afterEach, describe, expect, it } from 'vitest';
import { setLocale } from 'src/i18n';
import type { MachineDetail } from 'src/services/machines';
import MachineComplianceCard from './MachineComplianceCard.vue';

function machine(fields: Partial<MachineDetail>): MachineDetail {
  return { compliance: [], ...fields } as MachineDetail;
}

const CHECKS: MachineDetail['compliance'] = [
  { check: 'encryption', state: 'not_applicable', detail: {} },
  { check: 'secure_boot', state: 'pass', detail: {} },
  { check: 'tpm', state: 'unknown', detail: {} },
  { check: 'firewall', state: 'fail', detail: { profiles: ['public', 'domain'] } },
  {
    check: 'patches',
    state: 'fail',
    detail: { count: 2, updates: ['KB1', 'KB2'], grace_days: 14 },
  },
  { check: 'local_admins', state: 'fail', detail: { count: 1, names: ['PC\\eleve'] } },
];

describe('MachineComplianceCard', () => {
  afterEach(() => setLocale('fr'));

  it('counts the known checks only, « 1 sur 4 », and words each detail', () => {
    const w = mount(MachineComplianceCard, { props: { machine: machine({ compliance: CHECKS }) } });
    expect(w.find('[data-test="compliance-summary"]').text()).toBe('1 sur 4');
    expect(w.find('[data-test="check-firewall"]').text()).toContain('Désactivé : public, domaine');
    expect(w.find('[data-test="check-patches"]').text()).toContain(
      '2 en attente, en retard depuis plus de 14 j : KB1, KB2',
    );
    expect(w.find('[data-test="check-local_admins"]').text()).toContain('En trop : PC\\eleve');
    expect(w.find('[data-test="check-encryption"]').text()).toContain('Non requis');
    expect(w.find('[data-test="check-tpm"]').text()).toContain('Non relevé');
  });

  it('says a poste has no TPM, rather than nothing', () => {
    const w = mount(MachineComplianceCard, {
      props: {
        machine: machine({
          compliance: [{ check: 'tpm', state: 'fail', detail: { absent: true } }],
        }),
      },
    });
    expect(w.find('[data-test="check-tpm"]').text()).toContain('Aucun TPM relevé sur ce poste');
  });

  it('says so when nothing was read, and shows no summary', () => {
    const w = mount(MachineComplianceCard, { props: { machine: machine({}) } });
    expect(w.find('[data-test="compliance-summary"]').exists()).toBe(false);
    expect(w.text()).toContain('Aucun contrôle relevé');
  });

  it('lists the administrators and the winget packages, those to update first', () => {
    const w = mount(MachineComplianceCard, {
      props: {
        machine: machine({
          local_admins: [{ name: 'PC\\Administrateur', sid: 'S-1-5-21-1-500' }],
          winget_reported_at: '2026-11-20T10:00:00Z',
          winget_packages: [
            { winget_id: '7zip.7zip', name: '7-Zip', version: '24.08', available: null },
            {
              winget_id: 'Mozilla.Firefox',
              name: 'Firefox',
              version: '128.0',
              available: '131.0',
            },
          ],
        }),
      },
    });
    expect(w.text()).toContain('PC\\Administrateur');
    const rows = w.findAll('[data-test^="winget-"]');
    expect(rows.map((r) => r.attributes('data-test'))).toEqual([
      'winget-Mozilla.Firefox',
      'winget-7zip.7zip',
    ]);
    expect(rows[0]!.text()).toContain('Disponible : 131.0');
    expect(rows[1]!.text()).toContain('À jour');
  });

  it('hides both lists when the agent does not report them', () => {
    const w = mount(MachineComplianceCard, { props: { machine: machine({ local_admins: null }) } });
    expect(w.text()).not.toContain('Administrateurs locaux');
    expect(w.text()).not.toContain('winget');
  });

  it('reads in English', () => {
    setLocale('en');
    const w = mount(MachineComplianceCard, { props: { machine: machine({ compliance: CHECKS }) } });
    expect(w.find('[data-test="compliance-summary"]').text()).toBe('1 of 4');
    expect(w.find('[data-test="check-firewall"]').text()).toContain('Off: public, domain');
  });
});

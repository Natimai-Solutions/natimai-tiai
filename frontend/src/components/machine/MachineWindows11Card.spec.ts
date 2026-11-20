import { mount } from '@vue/test-utils';
import { describe, expect, it } from 'vitest';
import type { MachineDetail } from 'src/services/machines';
import MachineWindows11Card from './MachineWindows11Card.vue';

function machine(windows11: MachineDetail['windows11']): MachineDetail {
  return { windows11 } as MachineDetail;
}

describe('MachineWindows11Card', () => {
  it('says nothing for an older server', () => {
    const wrapper = mount(MachineWindows11Card, { props: { machine: machine(undefined) } });
    expect(wrapper.text()).toBe('');
  });

  it('lists each part and leaves the processor to check', () => {
    const wrapper = mount(MachineWindows11Card, {
      props: {
        machine: machine({
          verdict: 'blocked',
          tpm: 'fail',
          ram: 'ok',
          disk: 'ok',
          architecture: 'ok',
          secure_boot: 'check',
          processor: 'check',
        }),
      },
    });
    expect(wrapper.text()).toContain('Matériel incompatible');
    expect(wrapper.text()).toContain('TPM 2.0');
    expect(wrapper.text()).toContain('non');
    expect(wrapper.text()).toContain('Processeur pris en charge');
  });

  it('keeps it short on a poste already on Windows 11', () => {
    const wrapper = mount(MachineWindows11Card, {
      props: {
        machine: machine({
          verdict: 'already',
          tpm: 'ok',
          ram: 'ok',
          disk: 'ok',
          architecture: 'ok',
          secure_boot: 'ok',
          processor: 'ok',
        }),
      },
    });
    expect(wrapper.text()).toContain('Déjà sous Windows 11');
    expect(wrapper.text()).not.toContain('TPM');
  });
});

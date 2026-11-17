// @vitest-environment jsdom
import { mount } from '@vue/test-utils';
import { Quasar, useQuasar } from 'quasar';
import { describe, expect, it } from 'vitest';
import { defineComponent, h } from 'vue';
import { createMemoryHistory, createRouter } from 'vue-router';
import App from './App.vue';

describe('App (item 12)', () => {
  it('marks an empty table with a neutral icon, not the warning triangle', async () => {
    Object.defineProperty(window.screen, 'orientation', {
      configurable: true,
      value: {
        type: 'landscape-primary',
        angle: 0,
        addEventListener() {},
        removeEventListener() {},
      },
    });
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: '/', component: { render: () => null } }],
    });
    await router.push('/');
    let icon = '';
    const Probe = defineComponent({
      setup() {
        icon = useQuasar().iconSet.table.warning;
        return () => h('div');
      },
    });
    mount({ render: () => [h(App), h(Probe)] }, { global: { plugins: [Quasar, router] } });
    expect(icon).toBe('info_outline');
  });
});

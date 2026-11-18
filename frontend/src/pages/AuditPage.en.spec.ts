import { flushPromises, mount } from '@vue/test-utils';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { defineComponent, h, nextTick } from 'vue';
import { createMemoryHistory, createRouter } from 'vue-router';
import { QSelect } from 'quasar';

vi.mock('src/services/audit', () => ({
  listAudit: vi.fn(),
  listAuditActions: vi.fn(() => Promise.resolve([])),
}));

import AuditDetailsDialog from 'src/components/audit/AuditDetailsDialog.vue';
import AuditFiltersBar from 'src/components/audit/AuditFiltersBar.vue';
import { setLocale } from 'src/i18n';
import { listAudit, type AuditEntry } from 'src/services/audit';
import { emptyAuditFilters } from 'src/utils/auditQuery';
import AuditPage from './AuditPage.vue';

const Stub = defineComponent({ render: () => h('div') });

const MACHINE_ID = '0d4c1a52-7e1b-4c4f-9a35-2b1f0c9e11aa';

const entries: AuditEntry[] = [
  {
    id: 'a1',
    at: '2026-11-10T10:00:00Z',
    actor: 'admin@x',
    action: 'machine.merge',
    resource_type: 'machine',
    resource_id: MACHINE_ID,
    details: { hostname: 'PC-A', source_hostname: 'PC-A-OLD', source_withheld: false },
    ip: '10.62.0.7',
  },
  {
    id: 'a2',
    at: '2026-11-10T09:00:00Z',
    actor: 'admin@x',
    action: 'room.place_machines',
    resource_type: 'room',
    resource_id: 'r-1',
    details: { name: 'CDI', machine_ids: ['a', 'b'] },
    ip: null,
  },
];

async function mountPage() {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/audit', name: 'audit', component: Stub },
      { path: '/machines/:id', name: 'machine-detail', component: Stub },
    ],
  });
  await router.push('/audit');
  const w = mount(AuditPage, {
    attachTo: document.body,
    global: { plugins: [router], stubs: { QPage: { template: '<div><slot /></div>' } } },
  });
  await flushPromises();
  return w;
}

afterEach(() => {
  setLocale('fr');
  document.body.innerHTML = '';
});

describe('AuditPage in English', () => {
  beforeEach(() => {
    vi.mocked(listAudit).mockResolvedValue({ items: entries, total: 2, page: 1, page_size: 50 });
  });

  it('reads in English, with no French left', async () => {
    setLocale('en');
    const w = await mountPage();
    const text = w.text();
    expect(text).toContain('Audit log');
    expect(text).toContain('Administrative actions, newest first.');
    for (const header of ['Date', 'Author', 'Address', 'Action', 'Resource', 'Details']) {
      expect(w.find('thead').text()).toContain(header);
    }
    expect(text).toContain('Two computer pages merged');
    expect(text).toContain('PC-A · absorbed “PC-A-OLD”');
    expect(text).toContain('Computers assigned to a room');
    expect(text).toContain('CDI · 2 computers');
    expect(text).toContain('Resource type');
    expect(text).toContain('1–2 of 2');
    expect(w.find('button[aria-label="View details"]').exists()).toBe(true);
    expect(text).not.toMatch(/[éèàùç«»]/);
    w.unmount();
  });

  it('switches language while open', async () => {
    const w = await mountPage();
    expect(w.text()).toContain("Journal d'audit");
    expect(w.text()).toContain('Fusion de deux fiches poste');
    expect(w.find('thead').text()).toContain('Auteur');

    setLocale('en');
    await nextTick();
    expect(w.text()).toContain('Audit log');
    expect(w.text()).toContain('Two computer pages merged');
    expect(w.find('thead').text()).toContain('Author');
    expect(w.find('thead').text()).not.toContain('Auteur');
    w.unmount();
  });

  it('says why the table is empty, in English', async () => {
    vi.mocked(listAudit).mockResolvedValue({ items: [], total: 0, page: 1, page_size: 50 });
    setLocale('en');
    const w = await mountPage();
    expect(w.text()).toContain('No administrative action recorded yet.');
    w.unmount();
  });
});

describe('AuditDetailsDialog in English', () => {
  it('words the entry, its resource and its details', async () => {
    setLocale('en');
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: '/machines/:id', name: 'machine-detail', component: Stub }],
    });
    const w = mount(AuditDetailsDialog, {
      attachTo: document.body,
      props: {
        modelValue: true,
        entry: {
          ...entries[0]!,
          details: { hostname: 'PC-A', generated: true, via: 'slow_attempts', custom_key: 1 },
        },
      },
      global: { plugins: [router] },
    });
    await flushPromises();
    const text = document.body.textContent ?? '';
    expect(text).toContain('Two computer pages merged');
    expect(text).toContain('from 10.62.0.7');
    expect(text).toContain('Resource');
    expect(text).toContain('Computer');
    expect(text).toContain('Computer name');
    expect(text).toContain('Generated password');
    expect(text).toContain('Yes');
    expect(text).toContain('Triggered by');
    expect(text).toContain('spaced-out attempts (24 h)');
    expect(text).toContain('custom_key');
    expect(text).toContain('Raw JSON');
    expect(text).toContain('Every action on this resource');
    expect(text).toContain('Copy');
    expect(text).toContain('Close');
    expect(text).not.toMatch(/[éèàùç«»]/);
    w.unmount();
  });
});

describe('AuditDetailsDialog — a test e-mail recorded with its code', () => {
  // Verification of 2026-11-18: the outcome showed the server's French.
  async function mountEntry(details: Record<string, unknown>) {
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: '/machines/:id', name: 'machine-detail', component: Stub }],
    });
    const w = mount(AuditDetailsDialog, {
      attachTo: document.body,
      props: {
        modelValue: true,
        entry: { ...entries[0]!, action: 'settings.email_test', details },
      },
      global: { plugins: [router] },
    });
    await flushPromises();
    return w;
  }
  const sent = {
    to: 'admin@lycee.pf',
    ok: 'oui',
    message: 'E-mail de test envoyé à admin@lycee.pf par le serveur SMTP smtp.x.fr:587.',
    message_code: 'sent',
    message_params: { to: 'admin@lycee.pf', provider: 'smtp', host: 'smtp.x.fr', port: 587 },
  };

  it('words the outcome in English, without rows for its code', async () => {
    setLocale('en');
    const w = await mountEntry(sent);
    // The rows, not the raw JSON below them: that one shows what is stored.
    const rows = [...document.querySelectorAll('tr')].map((r) => r.textContent ?? '').join('\n');
    expect(rows).not.toContain('E-mail de test envoyé');
    expect(rows).toContain('smtp.x.fr:587');
    expect(rows).not.toContain('message_code');
    w.unmount();
  });

  it('reads the server’s French in French, and keeps an older entry’s message', async () => {
    let w = await mountEntry(sent);
    expect(document.body.textContent).toContain(sent.message);
    w.unmount();
    setLocale('en');
    w = await mountEntry({ to: 'a@b.c', ok: 'non', message: 'Ancien message' });
    expect(document.body.textContent).toContain('Ancien message');
    w.unmount();
  });
});

describe('AuditFiltersBar in English', () => {
  it('labels its fields, and follows a change of language', async () => {
    const w = mount(AuditFiltersBar, {
      props: {
        modelValue: {
          ...emptyAuditFilters(),
          from: '2026-09-30',
          to: '2026-09-01',
          resourceType: 'machine',
          resourceId: 'abc',
        },
        actions: ['machine.merge'],
      },
    });
    expect(w.text()).toContain('Type de ressource');
    expect(w.text()).toContain('Poste abc');
    // The resource-type list is recomputed too, not frozen at setup.
    const typeOptions = () =>
      (
        w
          .findAllComponents(QSelect)
          .find((s) => s.props('options')?.some((o: { value?: unknown }) => o.value === 'machine'))!
          .props('options') as { value: string; label: string }[]
      ).find((o) => o.value === 'machine')!.label;
    expect(typeOptions()).toBe('Poste');

    setLocale('en');
    await nextTick();
    expect(typeOptions()).toBe('Computer');
    const text = w.text();
    expect(text).toContain('Resource type');
    expect(text).toContain('From');
    expect(text).toContain('To (included)');
    expect(text).toContain('Before the start date');
    expect(text).toContain('Computer abc');
    expect(text).toContain('Reset filters');
    expect(text).not.toMatch(/[éèàùç«»]/);
  });
});

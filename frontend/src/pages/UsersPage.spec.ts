import { flushPromises, mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import { QDialog, QInput } from 'quasar';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('src/services/users', async (importOriginal) => ({
  ...(await importOriginal<typeof import('src/services/users')>()),
  listUsers: vi.fn(),
  resetUserPassword: vi.fn(),
}));
vi.mock('src/services/groups', async (importOriginal) => ({
  ...(await importOriginal<typeof import('src/services/groups')>()),
  listGroups: vi.fn(),
}));

import { listGroups } from 'src/services/groups';
import { listUsers, resetUserPassword, type ConsoleUser } from 'src/services/users';
import { useAuthStore } from 'src/stores/auth';
import UsersPage from './UsersPage.vue';

/** What the page keeps to itself, reached the way a click on the row's menu would. */
interface ResetApi {
  openReset: (user: ConsoleUser) => void;
  submitReset: () => Promise<void>;
  resetOpen: boolean;
  resetResult: string | null;
}

let release!: (password: string) => void;

function mountPage() {
  const pinia = createPinia();
  setActivePinia(pinia);
  useAuthStore().user = {
    id: 'me',
    email: 'admin@example.org',
    permissions: ['user:read', 'user:write'],
  } as never;
  const wrapper = mount(UsersPage, {
    attachTo: document.body,
    global: { plugins: [pinia], stubs: { QPage: { template: '<div><slot /></div>' } } },
  });
  return { wrapper, vm: wrapper.vm as unknown as ResetApi };
}

/** The reset dialog: the page's last one. */
function resetDialog(wrapper: ReturnType<typeof mountPage>['wrapper']) {
  return wrapper.findAllComponents(QDialog).at(-1)!;
}

describe('UsersPage — password reset (audit T29, U13)', () => {
  beforeEach(() => {
    vi.mocked(listUsers).mockResolvedValue({ items: [], total: 0, page: 1, page_size: 25 });
    vi.mocked(listGroups).mockResolvedValue([]);
    vi.mocked(resetUserPassword).mockImplementation(
      () => new Promise<string>((resolve) => (release = resolve)),
    );
  });

  it('cannot be dismissed while the reset is in flight', async () => {
    const { wrapper, vm } = mountPage();
    await flushPromises();
    vm.openReset({ id: 'x', email: 'tech@example.org' } as ConsoleUser);
    await flushPromises();
    expect(resetDialog(wrapper).props('persistent')).toBe(false);

    const done = vm.submitReset();
    await flushPromises();

    expect(resetDialog(wrapper).props('persistent')).toBe(true);
    release('S3cret-Generated-Pw');
    await done;
    await flushPromises();
    expect(resetDialog(wrapper).props('persistent')).toBe(true);
    wrapper.unmount();
  });

  it('shows a password that arrives after the dialog was closed', async () => {
    const { wrapper, vm } = mountPage();
    await flushPromises();
    vm.openReset({ id: 'x', email: 'tech@example.org' } as ConsoleUser);
    await flushPromises();
    const done = vm.submitReset();
    await flushPromises();
    // However it went away meanwhile...
    vm.resetOpen = false;
    await flushPromises();

    release('S3cret-Generated-Pw');
    await done;
    await flushPromises();

    // ...the password the server applied is on screen.
    expect(vm.resetOpen).toBe(true);
    expect(vm.resetResult).toBe('S3cret-Generated-Pw');
    const shown = resetDialog(wrapper)
      .findAllComponents(QInput)
      .find((i) => i.props('modelValue') === 'S3cret-Generated-Pw');
    expect(shown).toBeDefined();
    wrapper.unmount();
  });
});

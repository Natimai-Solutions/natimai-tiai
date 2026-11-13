import { createPinia, setActivePinia } from 'pinia';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { getMe, type User } from 'src/services/auth';
import { useAuthStore } from './auth';

vi.mock('src/services/auth', () => ({
  getMe: vi.fn(),
  login: vi.fn(),
  logout: vi.fn(),
  updateMe: vi.fn(),
}));

const profile = { id: 'u1', email: 'a@b.c', permissions: ['threat:read'] } as unknown as User;

describe('ensureProfile', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.mocked(getMe).mockReset();
  });

  // After a reload the guard awaits this before the page: a page that tests
  // can() while it loads must see the real permissions.
  it('loads the profile when none is held, so can() answers', async () => {
    vi.mocked(getMe).mockResolvedValue(profile);
    const auth = useAuthStore();
    expect(auth.can('threat', 'read')).toBe(false);
    await auth.ensureProfile();
    expect(auth.can('threat', 'read')).toBe(true);
  });

  it('does not fetch again once the profile is there', async () => {
    vi.mocked(getMe).mockResolvedValue(profile);
    const auth = useAuthStore();
    await auth.ensureProfile();
    await auth.ensureProfile();
    expect(getMe).toHaveBeenCalledTimes(1);
  });

  it('never throws: a failed fetch leaves the page to report it', async () => {
    vi.mocked(getMe).mockRejectedValue(new Error('offline'));
    const auth = useAuthStore();
    await expect(auth.ensureProfile()).resolves.toBeUndefined();
    expect(auth.user).toBeNull();
  });
});

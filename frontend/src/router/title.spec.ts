// @vitest-environment jsdom
// The tab's title in the reader's language: a route's `meta.title` is a key
// of the catalogues, and the title follows a change of language — unless a
// page wrote its own (the poste's name), which no language changes.
import type { RouteRecordRaw, Router } from 'vue-router';
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { setLocale, t } from 'src/i18n';
import { CHUNK_LOAD_FAILED_MESSAGE, chunkLoadFailedMessage } from 'src/utils/staleChunks';

vi.mock('boot/axios', () => ({ refreshSession: vi.fn() }));
vi.mock('src/services/session', () => ({
  ensureSession: () => Promise.resolve(true),
  getAccessToken: () => 'token',
}));
vi.mock('src/stores/auth', () => ({
  useAuthStore: () => ({
    ensureProfile: () => Promise.resolve(),
    user: { permissions: ['machine:read', 'room:read'] },
  }),
  readCachedPermissions: () => [],
}));

function flatten(list: readonly RouteRecordRaw[]): RouteRecordRaw[] {
  return list.flatMap((r) => [r, ...flatten(r.children ?? [])]);
}

// The real routes' titles, on pages that load nothing.
vi.mock('./routes', async (importOriginal) => {
  const real = (await importOriginal<{ default: RouteRecordRaw[] }>()).default;
  const all = real.flatMap(function walk(r): RouteRecordRaw[] {
    return [r, ...(r.children ?? []).flatMap(walk)];
  });
  const title = (name: string) => all.find((r) => r.name === name)?.meta?.title;
  const page = { render: () => null };
  return {
    default: [
      { path: '/rooms', name: 'rooms', component: page, meta: { title: title('rooms') } },
      {
        path: '/machines/:id',
        name: 'machine-detail',
        component: page,
        meta: { title: title('machine-detail') },
      },
    ],
  };
});

let router: Router;

beforeAll(async () => {
  window.scrollTo = vi.fn();
  const createAppRouter = (await import('./index')).default as unknown as () => Router;
  router = createAppRouter();
});

beforeEach(async () => {
  await router.push('/machines/x');
});

afterEach(() => setLocale('fr'));

describe('route titles', () => {
  it('are keys of the catalogues, worded in both languages', async () => {
    const real = (await vi.importActual<{ default: RouteRecordRaw[] }>('./routes')).default;
    const keys = flatten(real)
      .map((r) => r.meta?.title)
      .filter((k): k is string => typeof k === 'string');
    expect(keys).toHaveLength(27);
    for (const key of keys) {
      expect(key).toMatch(/^layout\.pages\./);
      expect(t(key)).not.toBe(key);
      setLocale('en');
      expect(t(key)).not.toBe(key);
      setLocale('fr');
    }
  });

  it('is written in French, then follows the language', async () => {
    await router.push('/rooms');
    expect(document.title).toBe("Salles — Tia'i");
    setLocale('en');
    expect(document.title).toBe("Rooms — Tia'i");
    await router.push('/machines/y');
    expect(document.title).toBe("Computer — Tia'i");
    setLocale('fr');
    expect(document.title).toBe("Poste — Tia'i");
  });

  it('leaves alone a title a page wrote', async () => {
    await router.push('/rooms');
    document.title = "PC-01 — Tia'i";
    setLocale('en');
    expect(document.title).toBe("PC-01 — Tia'i");
  });
});

describe('a page that could not be loaded', () => {
  it('is said in the language shown', () => {
    expect(chunkLoadFailedMessage()).toBe(CHUNK_LOAD_FAILED_MESSAGE);
    setLocale('en');
    expect(chunkLoadFailedMessage()).toBe(
      'Could not load this page (connection lost or update in progress). Reload the page.',
    );
  });
});

import { beforeEach, describe, expect, it, vi } from 'vitest';

// Mock the axios boot module before importing the service under test.
vi.mock('boot/axios', () => ({
  api: { get: vi.fn() },
}));

import { api } from 'boot/axios';
import { auditQueryParams, listAudit, listAuditActions } from './audit';

const entry = {
  id: '6a1f0c2e-0000-4000-8000-000000000001',
  at: '2026-09-30T08:15:00Z',
  actor: 'marie@test.local',
  action: 'machine.revoke_token',
  resource_type: 'machine',
  resource_id: '0d4c1a52-0000-4000-8000-0000000000aa',
  details: { hostname: 'PC-CDI-01', machine_uuid: 'abc' },
};

describe('auditQueryParams', () => {
  it('keeps every supplied filter and the pagination', () => {
    expect(
      auditQueryParams({
        action: 'user.create',
        actor: 'marie',
        resource_type: 'user',
        resource_id: 'u-1',
        since: '2026-09-01T00:00:00.000Z',
        until: '2026-10-01T00:00:00.000Z',
        page: 2,
        page_size: 100,
      }),
    ).toEqual({
      action: 'user.create',
      actor: 'marie',
      resource_type: 'user',
      resource_id: 'u-1',
      since: '2026-09-01T00:00:00.000Z',
      until: '2026-10-01T00:00:00.000Z',
      page: 2,
      page_size: 100,
    });
  });

  // `?action=` would ask for the slug "" — no rows — where the reader meant "any".
  it('omits blank filters rather than sending them empty', () => {
    expect(auditQueryParams({ action: '', actor: '   ', resource_type: '', page: 1 })).toEqual({
      page: 1,
    });
  });

  it('trims the free-text filters', () => {
    expect(auditQueryParams({ actor: '  marie@ ' })).toEqual({ actor: 'marie@' });
  });
});

describe('listAudit', () => {
  beforeEach(() => {
    vi.mocked(api.get).mockReset();
  });

  it('calls GET /audit with the cleaned filters and returns the payload', async () => {
    const payload = { items: [entry], total: 1, page: 1, page_size: 50 };
    vi.mocked(api.get).mockResolvedValue({ data: payload });

    const result = await listAudit({ action: 'machine.revoke_token', actor: '', page: 1 });

    expect(api.get).toHaveBeenCalledWith('/audit', {
      params: { action: 'machine.revoke_token', page: 1 },
    });
    expect(result).toEqual(payload);
  });

  it('sends no parameters when none are given', async () => {
    vi.mocked(api.get).mockResolvedValue({ data: { items: [], total: 0, page: 1, page_size: 50 } });

    await listAudit();

    expect(api.get).toHaveBeenCalledWith('/audit', { params: {} });
  });

  // The page reads `details` as an object everywhere; a null (or anything
  // else) must not reach it.
  it('normalises missing or malformed details to an empty object', async () => {
    vi.mocked(api.get).mockResolvedValue({
      data: {
        items: [
          { ...entry, details: null },
          { ...entry, details: ['x'] },
        ],
        total: 2,
        page: 1,
        page_size: 50,
      },
    });

    const result = await listAudit();

    expect(result.items.map((i) => i.details)).toEqual([{}, {}]);
  });
});

describe('listAuditActions', () => {
  beforeEach(() => {
    vi.mocked(api.get).mockReset();
  });

  it('calls GET /audit/actions and returns the slugs', async () => {
    vi.mocked(api.get).mockResolvedValue({ data: ['machine.merge', 'user.create'] });

    const result = await listAuditActions();

    expect(api.get).toHaveBeenCalledWith('/audit/actions');
    expect(result).toEqual(['machine.merge', 'user.create']);
  });

  it('drops anything that is not a non-empty string', async () => {
    vi.mocked(api.get).mockResolvedValue({ data: ['user.create', '', null, 3] });
    expect(await listAuditActions()).toEqual(['user.create']);
  });

  it('answers an empty list to a malformed payload', async () => {
    vi.mocked(api.get).mockResolvedValue({ data: { detail: 'x' } });
    expect(await listAuditActions()).toEqual([]);
  });
});

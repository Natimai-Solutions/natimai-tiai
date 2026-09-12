import { beforeEach, describe, expect, it, vi } from 'vitest';

// Mock the axios boot module before importing the service under test.
vi.mock('boot/axios', () => ({
  api: { get: vi.fn(), post: vi.fn() },
}));

import { api } from 'boot/axios';
import { exportSoftware, listSoftware } from './software';

describe('listSoftware', () => {
  beforeEach(() => {
    vi.mocked(api.get).mockReset();
  });

  it('calls GET /software with the given filters and returns the payload', async () => {
    const payload = {
      items: [
        {
          id: 7,
          name: 'Java 8',
          version: '1.8.0_202',
          publisher: 'Oracle',
          machine_count: 148,
          first_seen: '2026-01-04T09:00:00Z',
        },
      ],
      total: 1,
      page: 1,
      page_size: 50,
    };
    vi.mocked(api.get).mockResolvedValue({ data: payload });

    const result = await listSoftware({ search: 'java', sort_by: 'machine_count', page: 2 });

    expect(api.get).toHaveBeenCalledWith('/software', {
      params: { search: 'java', sort_by: 'machine_count', page: 2 },
    });
    expect(result).toEqual(payload);
  });

  it('sends no parameters when none are given', async () => {
    vi.mocked(api.get).mockResolvedValue({ data: { items: [], total: 0, page: 1, page_size: 50 } });
    await listSoftware();
    expect(api.get).toHaveBeenCalledWith('/software', { params: {} });
  });
});

describe('exportSoftware', () => {
  beforeEach(() => {
    vi.mocked(api.get).mockReset();
  });

  // A blob and not text: the export is fetched rather than linked to, because
  // the API needs the Authorization header a plain <a href> would not carry.
  it('asks for a CSV blob and forwards the search', async () => {
    const blob = new Blob(['x']);
    vi.mocked(api.get).mockResolvedValue({ data: blob });

    const result = await exportSoftware('csv', { search: 'java' });

    expect(api.get).toHaveBeenCalledWith('/software/export.csv', {
      params: { search: 'java' },
      responseType: 'blob',
    });
    expect(result).toBe(blob);
  });

  it('asks the Excel route for the xlsx format', async () => {
    vi.mocked(api.get).mockResolvedValue({ data: new Blob(['x']) });

    await exportSoftware('xlsx');

    expect(api.get).toHaveBeenCalledWith('/software/export.xlsx', {
      params: {},
      responseType: 'blob',
    });
  });
});

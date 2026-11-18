import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('boot/axios', () => ({
  api: { get: vi.fn(), post: vi.fn() },
}));

import { api } from 'boot/axios';
import { setLocale } from 'src/i18n';
import { exportMachines, listExportColumns } from './machines';
import { exportSoftware } from './software';

/**
 * The exports are written by the server in the language the console asks
 * for (`lang`, plan I4). French is the server's default: in French the
 * request is the one an older console sent, word for word.
 */
describe('the language of the exports', () => {
  beforeEach(() => {
    vi.mocked(api.get).mockReset();
    vi.mocked(api.get).mockResolvedValue({ data: new Blob() });
  });

  afterEach(() => setLocale('fr'));

  it('asks nothing in French', async () => {
    await exportMachines({ online: true }, { format: 'csv' });
    await exportSoftware('xlsx', { search: 'java' });
    vi.mocked(api.get).mockResolvedValue({ data: [] });
    await listExportColumns();

    expect(api.get).toHaveBeenNthCalledWith(1, '/machines/export.csv', {
      params: { online: true },
      responseType: 'blob',
    });
    expect(api.get).toHaveBeenNthCalledWith(2, '/software/export.xlsx', {
      params: { search: 'java' },
      responseType: 'blob',
    });
    expect(api.get).toHaveBeenNthCalledWith(3, '/machines/export-columns');
  });

  it('asks for English when the console is in English', async () => {
    setLocale('en');
    await exportMachines(
      { online: true },
      { format: 'xlsx', columns: ['hostname'], tz: 'Pacific/Tahiti' },
    );
    await exportSoftware('csv');
    vi.mocked(api.get).mockResolvedValue({ data: [] });
    await listExportColumns();

    expect(api.get).toHaveBeenNthCalledWith(1, '/machines/export.xlsx', {
      params: { online: true, columns: 'hostname', tz: 'Pacific/Tahiti', lang: 'en' },
      responseType: 'blob',
    });
    expect(api.get).toHaveBeenNthCalledWith(2, '/software/export.csv', {
      params: { lang: 'en' },
      responseType: 'blob',
    });
    expect(api.get).toHaveBeenNthCalledWith(3, '/machines/export-columns', {
      params: { lang: 'en' },
    });
  });
});

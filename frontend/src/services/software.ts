import { api } from 'boot/axios';

/**
 * The parc's software catalogue — the reason the inventory module is worth
 * building. A fiche answers "what is on this poste"; this answers "qui a encore
 * Java 8", which is the question an administrator actually arrives with.
 *
 * There is deliberately no `listSoftwareMachines` here: the drill-down is the
 * machine list filtered by `software_id`, which already has pagination, sorting
 * and a dozen other filters — so "qui a Java 8 *et* est allumé" costs nothing.
 */

/** One catalogue entry and how much of the parc carries it. */
export interface SoftwareEntry {
  id: number;
  name: string;
  version: string;
  publisher: string;
  machine_count: number;
  /** When this exact version first appeared anywhere — is the rollout started, or done. */
  first_seen: string;
}

export interface SoftwareList {
  items: SoftwareEntry[];
  total: number;
  page: number;
  page_size: number;
}

/** Sortable columns, named after the API's own fields. */
export type SoftwareSortField = 'name' | 'version' | 'publisher' | 'machine_count';

export interface ListSoftwareParams {
  /** Free search over name and publisher. */
  search?: string;
  /** Server-side sort; the server defaults to most widespread first. */
  sort_by?: SoftwareSortField;
  sort_desc?: boolean;
  page?: number;
  page_size?: number;
}

export async function listSoftware(params: ListSoftwareParams = {}): Promise<SoftwareList> {
  const { data } = await api.get<SoftwareList>('/software', { params });
  return data;
}

export type SoftwareExportFormat = 'xlsx' | 'csv';

/**
 * The catalogue as a spreadsheet — Excel or CSV — honouring the same search
 * and without the pagination: an export of the first fifty rows is not an
 * export.
 *
 * Fetched as a blob rather than linked to: the API needs the Authorization
 * header, which a plain `<a href>` would not carry.
 */
export async function exportSoftware(
  format: SoftwareExportFormat,
  params: { search?: string } = {},
): Promise<Blob> {
  const { data } = await api.get<Blob>(`/software/export.${format}`, {
    params,
    responseType: 'blob',
  });
  return data;
}

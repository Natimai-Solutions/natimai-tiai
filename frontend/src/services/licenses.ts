import { api } from 'boot/axios';

/** Software licences (plan `dev/plan-evolutions-itil.md`, C6). Never the key. */

export type LicenseExpiry = 'none' | 'active' | 'soon' | 'expired';

export interface License {
  id: string;
  name: string;
  /** Substrings of the program names it covers, matched literally, any case. */
  patterns: string[];
  publisher: string | null;
  /** Postes it covers; null for a site licence without a count. */
  seats: number | null;
  expires_on: string | null;
  vendor: string | null;
  reference: string | null;
  notes: string | null;
  /** Postes carrying what it covers, in the reader's scope, once each. */
  installed: number;
  /** null when the reader's count is not the parc's (account limited to some places). */
  over: boolean | null;
  expiry: LicenseExpiry;
  created_at: string;
  updated_at: string;
}

export interface LicenseList {
  items: License[];
  restricted: boolean;
  expiry_days: number;
}

export interface LicenseDetail extends License {
  programs: string[];
}

export interface LicenseFields {
  name: string;
  patterns: string[];
  publisher: string | null;
  seats: number | null;
  expires_on: string | null;
  vendor: string | null;
  reference: string | null;
  notes: string | null;
}

export interface LicensePreview {
  programs: string[];
  installed: number;
}

export async function listLicenses(): Promise<LicenseList> {
  const { data } = await api.get<LicenseList>('/licenses');
  return data;
}

export async function getLicense(id: string): Promise<LicenseDetail> {
  const { data } = await api.get<LicenseDetail>(`/licenses/${id}`);
  return data;
}

export async function createLicense(fields: LicenseFields): Promise<License> {
  const { data } = await api.post<License>('/licenses', fields);
  return data;
}

export async function updateLicense(id: string, fields: LicenseFields): Promise<License> {
  const { data } = await api.patch<License>(`/licenses/${id}`, fields);
  return data;
}

export async function deleteLicense(id: string): Promise<void> {
  await api.delete(`/licenses/${id}`);
}

export async function previewLicense(
  patterns: string[],
  publisher: string | null,
): Promise<LicensePreview> {
  const { data } = await api.post<LicensePreview>('/licenses/preview', { patterns, publisher });
  return data;
}

/** Whether a licence needs looking at: over its count, or its contract ending or ended. */
export function needsAttention(lic: License): boolean {
  return lic.over === true || lic.expiry === 'soon' || lic.expiry === 'expired';
}

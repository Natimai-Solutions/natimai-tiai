import { api } from 'boot/axios';
import qrcode from 'qrcode-generator';
import { t } from 'src/i18n';

/**
 * Assets: purchase, warranty, status and loan of a poste, and the equipment
 * no agent runs on (a projector, a printer). `asset:read` / `asset:write`, a
 * right of its own so that a purchase price is not read by everyone.
 */

export const ASSET_STATUSES = [
  'in_stock',
  'in_service',
  'in_repair',
  'on_loan',
  'retired',
] as const;
export type AssetStatus = (typeof ASSET_STATUSES)[number];

/** The kinds a person picks for equipment; `computer` is a poste's. */
export const EQUIPMENT_KINDS = ['printer', 'projector', 'screen', 'network', 'other'] as const;
export type AssetKind = 'computer' | (typeof EQUIPMENT_KINDS)[number];

export interface AssetMachineRef {
  id: string;
  hostname: string | null;
  hw_manufacturer: string | null;
  hw_model: string | null;
  hw_serial: string | null;
}

export interface Asset {
  id: string;
  machine_id: string | null;
  kind: string;
  display_name: string | null;
  name: string | null;
  room_id: string | null;
  room_name: string | null;
  building_name: string | null;
  manufacturer: string | null;
  model: string | null;
  serial_number: string | null;
  inventory_number: string | null;
  status: string;
  purchase_date: string | null;
  supplier: string | null;
  order_reference: string | null;
  warranty_end: string | null;
  /**
   * Where the warranty stands, as the server reads it: « soon » over the days
   * the warranty alert is set to in Paramètres, so the fiche, the filter and
   * the alert agree. Absent from an older server.
   */
  warranty_state?: WarrantyState;
  /** A decimal, as text: « 749.90 ». */
  purchase_price: string | null;
  borrower: string | null;
  loan_due: string | null;
  notes: string | null;
  public_token: string;
  updated_at: string;
  updated_by: string | null;
  machine: AssetMachineRef | null;
}

export type WarrantyState = 'none' | 'active' | 'soon' | 'expired';

export interface AssetList {
  items: Asset[];
  total: number;
  page: number;
  page_size: number;
}

/** The fields a person writes: absent = unchanged, null = cleared. */
export interface AssetPayload {
  kind?: AssetKind;
  name?: string | null;
  room_id?: string | null;
  manufacturer?: string | null;
  model?: string | null;
  serial_number?: string | null;
  inventory_number?: string | null;
  status?: AssetStatus;
  purchase_date?: string | null;
  supplier?: string | null;
  order_reference?: string | null;
  warranty_end?: string | null;
  purchase_price?: string | null;
  borrower?: string | null;
  loan_due?: string | null;
  notes?: string | null;
}

export interface ListAssetsParams {
  search?: string;
  kind?: AssetKind;
  status?: AssetStatus;
  room_id?: string;
  with_machine?: boolean;
  warranty?: 'active' | 'soon' | 'expired' | 'none';
  /** Comma-separated asset ids: the labels page's own list. */
  ids?: string;
  page?: number;
  page_size?: number;
}

export async function listAssets(params: ListAssetsParams = {}): Promise<AssetList> {
  const { data } = await api.get<AssetList>('/assets', { params });
  return data;
}

export async function createEquipment(payload: AssetPayload & { name: string }): Promise<Asset> {
  const { data } = await api.post<Asset>('/assets', payload);
  return data;
}

export async function updateAsset(id: string, payload: AssetPayload): Promise<Asset> {
  const { data } = await api.patch<Asset>(`/assets/${id}`, payload);
  return data;
}

export async function deleteAsset(id: string): Promise<void> {
  await api.delete(`/assets/${id}`);
}

export async function renewAssetToken(id: string): Promise<Asset> {
  const { data } = await api.post<Asset>(`/assets/${id}/token`);
  return data;
}

export async function getMachineAsset(machineId: string): Promise<Asset | null> {
  const { data } = await api.get<Asset | null>(`/machines/${machineId}/asset`);
  return data;
}

export async function putMachineAsset(machineId: string, payload: AssetPayload): Promise<Asset> {
  const { data } = await api.put<Asset>(`/machines/${machineId}/asset`, payload);
  return data;
}

/**
 * Give each poste of a room that has none its asset — so that it has a label.
 * Returns how many were created.
 */
export async function completeRoomAssets(roomId: string): Promise<number> {
  const { data } = await api.post<{ created: number }>(`/assets/rooms/${roomId}/complete`);
  return data.created;
}

/** What a scanned label names: the poste to open, else the asset. */
export async function resolveAssetToken(
  token: string,
): Promise<{ machine_id: string | null; asset_id: string }> {
  const { data } = await api.get<{ machine_id: string | null; asset_id: string }>(
    `/assets/by-token/${encodeURIComponent(token)}`,
  );
  return data;
}

export type ImportAction =
  'create' | 'update' | 'unchanged' | 'unmatched' | 'ambiguous' | 'invalid';

export interface ImportRow {
  line: number;
  serial: string;
  action: ImportAction;
  machine_id: string | null;
  hostname: string | null;
  changes: Record<string, string | null>;
  errors: string[];
}

export interface ImportResult {
  dry_run: boolean;
  rows: ImportRow[];
  counts: Partial<Record<ImportAction, number>>;
}

export async function importAssets(file: File, dryRun: boolean): Promise<ImportResult> {
  const form = new FormData();
  form.append('file', file);
  const { data } = await api.post<ImportResult>('/assets/import', form, {
    params: { dry_run: dryRun },
  });
  return data;
}

export function assetStatusLabel(status: string): string {
  return (ASSET_STATUSES as readonly string[]).includes(status)
    ? t(`assets.status.${status}`)
    : status;
}

export function assetKindLabel(kind: string): string {
  return ['computer', ...EQUIPMENT_KINDS].includes(kind) ? t(`assets.kind.${kind}`) : kind;
}

export function assetStatusColor(status: string): string {
  switch (status) {
    case 'in_service':
      return 'positive';
    case 'in_repair':
      return 'warning';
    case 'on_loan':
      return 'primary';
    case 'retired':
      return 'grey-7';
    default:
      return 'blue-grey';
  }
}

/** The colour class of a warranty's state: over in red, ending in orange. */
export function warrantyClass(state: WarrantyState | undefined): string {
  return state === 'expired' ? 'text-negative' : state === 'soon' ? 'text-warn' : '';
}

/** The URL a label's QR code carries: the console's own address and the token. */
export function labelUrl(token: string, origin: string = window.location.origin): string {
  return `${origin}/a/${encodeURIComponent(token)}`;
}

/**
 * A QR code as an SVG path over a square of `size` modules (`viewBox`),
 * drawn from the modules rather than injected as markup: no `v-html`.
 */
export function qrPath(text: string): { size: number; path: string } {
  const qr = qrcode(0, 'M');
  qr.addData(text);
  qr.make();
  const count = qr.getModuleCount();
  const parts: string[] = [];
  for (let row = 0; row < count; row++) {
    for (let col = 0; col < count; col++) {
      if (qr.isDark(row, col)) parts.push(`M${col},${row}h1v1h-1z`);
    }
  }
  return { size: count, path: parts.join('') };
}

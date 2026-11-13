import { api } from 'boot/axios';
import type { Command, CommandList, CreateCommandsResponse } from './commands';

/**
 * Software packages the console deploys (dev/plan-deploiement-logiciel.md).
 *
 * Two kinds: a winget identifier, or files uploaded here with a command line.
 * Whether a poste runs one is decided on the poste, from what its GPO trusts:
 * winget switched on; the administrator's signature over the manifest
 * (method B); or, failing it, an executable signed by an approved publisher
 * (method A). The console shows which of these a package can rely on.
 */

export type PackageKind = 'winget' | 'files';

export interface PackageFile {
  name: string;
  sha256: string;
  size: number;
  /** Authenticode signer of the file, when it is a signed executable. */
  publisher_name: string | null;
}

export interface PackageProblem {
  code: string;
  message: string;
}

export interface Package {
  id: string;
  kind: PackageKind;
  name: string;
  version: string | null;
  notes: string | null;
  winget_id: string | null;
  winget_version: string | null;
  install_run: string | null;
  install_args: string[];
  uninstall_run: string | null;
  uninstall_args: string[];
  success_codes: number[];
  detect_name: string | null;
  files: PackageFile[];
  /** Method B: the administrator's signature is attached and valid. */
  signed: boolean;
  signer_subject: string | null;
  signer_thumbprint: string | null;
  signed_at: string | null;
  signed_by: string | null;
  /** Method A: the signer of the file that runs, if it is signed. */
  publisher_name: string | null;
  /** Why it cannot be deployed yet; empty when it can. */
  problems: PackageProblem[];
  /** Postes whose inventory shows the program; null without `detect_name`. */
  installed_count: number | null;
  created_by: string | null;
  created_at: string;
  updated_at: string;
  retired_at: string | null;
}

export interface PackageFields {
  name?: string;
  version?: string | null;
  notes?: string | null;
  winget_id?: string | null;
  winget_version?: string | null;
  install_run?: string | null;
  install_args?: string[];
  uninstall_run?: string | null;
  uninstall_args?: string[];
  success_codes?: number[];
  detect_name?: string | null;
}

export interface CreatePackagePayload extends PackageFields {
  kind: PackageKind;
  name: string;
}

/** Which way a package can reach a poste, as the console explains it. */
export type TrustMethod = 'winget' | 'signed' | 'publisher' | 'none';

/**
 * The same, for one step. `product_code`: an uninstall by
 * `msiexec /x {code produit}`, which method A runs without any file of the
 * package.
 */
export type StepTrust = TrustMethod | 'product_code';

export type DeployAction = 'install' | 'uninstall';

// What the agent refuses beside the executable under method A: Windows could
// load or run it from that folder (agent deploy.loadableExt, audit S02). The
// backend keeps a test that this list, its own and the agent's are equal.
const LOADABLE_EXTENSIONS = new Set(
  (
    '.dll .ocx .cpl .sys .drv .ax .acm .ime .tsp .mui .tlb .winmd .manifest .local .config ' +
    '.exe .com .scr .pif .msi .msp .mst .msu .appx .msix .bat .cmd .ps1 .psm1 .vbs .vbe .js ' +
    '.jse .wsf .wsh .hta .lnk .inf .jar .bpl .pyd .xll .node .rll .wsc .sct'
  ).split(' '),
);

// An MSI product code: the one argument method A lets msiexec take (agent
// deploy.productCode).
const PRODUCT_CODE =
  /^\{[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}\}$/;

function extension(name: string): string {
  const dot = name.lastIndexOf('.');
  return dot < 0 ? '' : name.slice(dot).toLowerCase();
}

export function trustMethod(p: Package): TrustMethod {
  const t = stepTrust(p, 'install');
  return t === 'product_code' ? 'none' : t;
}

/**
 * How a poste could run the package's installation — or uninstallation: the
 * agent's rule (deploy.go executeFiles / MethodAStep / MethodAFiles), as the
 * server applies it before queueing (manifest.runnable_somewhere). `none`:
 * every poste would refuse it (audit B30, U04).
 */
export function stepTrust(p: Package, action: DeployAction): StepTrust {
  if (p.kind === 'winget') return 'winget';
  if (p.signed) return 'signed';
  const run = (action === 'install' ? p.install_run : p.uninstall_run) ?? '';
  if (action === 'uninstall' && run === 'msiexec')
    // Method A rebuilds it as /x {code} /qn /norestart: nothing else is run.
    return p.uninstall_args.some((a) => PRODUCT_CODE.test(a)) ? 'product_code' : 'none';
  if (
    publisherOf(p, action) &&
    run.toLowerCase().endsWith('.exe') &&
    !(p.files ?? []).some((f) => f.name !== run && LOADABLE_EXTENSIONS.has(extension(f.name)))
  )
    return 'publisher';
  return 'none';
}

/** The Authenticode signer of the file the step runs, if it is one. */
export function publisherOf(p: Package, action: DeployAction = 'install'): string | null {
  if (action === 'install') return p.publisher_name;
  const run = p.uninstall_run;
  return (p.files ?? []).find((f) => f.name === run)?.publisher_name ?? null;
}

export const trustLabels: Record<TrustMethod, string> = {
  winget: 'winget',
  signed: 'Signé (méthode B)',
  publisher: 'Éditeur (méthode A)',
  none: 'Non signé',
};

/** Ready to deploy: complete, not retired. */
export function deployable(p: Package): boolean {
  return p.retired_at === null && p.problems.length === 0;
}

/**
 * A command line typed in one field, split into arguments the way the
 * Windows convention reads it: spaces separate, double quotes group, `\"` is
 * a literal quote. The agent passes the list as is — there is no shell.
 */
export function splitArgs(line: string): string[] {
  const out: string[] = [];
  let current = '';
  let quoted = false;
  let started = false;
  for (let i = 0; i < line.length; i++) {
    const c = line.charAt(i);
    if (c === '\\' && line.charAt(i + 1) === '"') {
      current += '"';
      i++;
      started = true;
    } else if (c === '"') {
      quoted = !quoted;
      started = true;
    } else if (/\s/.test(c) && !quoted) {
      if (started) out.push(current);
      current = '';
      started = false;
    } else {
      current += c;
      started = true;
    }
  }
  if (started) out.push(current);
  return out;
}

/** The inverse of `splitArgs`, for showing a stored list in one field. */
export function joinArgs(args: string[]): string {
  return args
    .map((a) => (a === '' || /[\s"]/.test(a) ? `"${a.replace(/"/g, '\\"')}"` : a))
    .join(' ');
}

export function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} o`;
  const units = ['Kio', 'Mio', 'Gio'];
  let value = bytes / 1024;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit++;
  }
  return `${value.toFixed(value < 10 ? 1 : 0)} ${units[unit]}`;
}

export async function listPackages(retired = false): Promise<Package[]> {
  const { data } = await api.get<Package[]>('/packages', { params: { retired } });
  return data;
}

export async function getPackage(id: string): Promise<Package> {
  const { data } = await api.get<Package>(`/packages/${id}`);
  return data;
}

export async function createPackage(payload: CreatePackagePayload): Promise<Package> {
  const { data } = await api.post<Package>('/packages', payload);
  return data;
}

export async function updatePackage(id: string, fields: PackageFields): Promise<Package> {
  const { data } = await api.patch<Package>(`/packages/${id}`, fields);
  return data;
}

/** Upload files, reporting progress as a fraction (0–1). */
/**
 * The server's default bound on one file (PACKAGE_MAX_BYTES, 2 Gio), checked
 * before sending: refused after the transfer, a large file costs minutes for
 * nothing. A server configured lower still answers 413 with its own figure.
 */
export const PACKAGE_FILE_MAX_BYTES = 2 * 1024 ** 3;

export async function uploadPackageFiles(
  id: string,
  files: File[],
  onProgress?: (fraction: number) => void,
  signal?: AbortSignal,
): Promise<Package> {
  const form = new FormData();
  for (const f of files) form.append('files', f, f.name);
  const { data } = await api.post<Package>(`/packages/${id}/files`, form, {
    // An installer is hundreds of megabytes: no request timeout here.
    timeout: 0,
    ...(signal ? { signal } : {}),
    onUploadProgress: (e) => {
      if (onProgress && e.total) onProgress(e.loaded / e.total);
    },
  });
  return data;
}

export async function deletePackageFile(id: string, name: string): Promise<Package> {
  const { data } = await api.delete<Package>(`/packages/${id}/files/${encodeURIComponent(name)}`);
  return data;
}

/** The manifest bytes, to save and sign on the administrator's machine. */
export async function downloadManifest(id: string): Promise<Blob> {
  const { data } = await api.get<Blob>(`/packages/${id}/manifest`, { responseType: 'blob' });
  return data;
}

/** Attach the JSON document Sign-TiaiPackage.ps1 produced. */
export async function attachSignature(id: string, document: unknown): Promise<Package> {
  const { data } = await api.put<Package>(`/packages/${id}/signature`, document);
  return data;
}

export async function removeSignature(id: string): Promise<Package> {
  const { data } = await api.delete<Package>(`/packages/${id}/signature`);
  return data;
}

export async function retirePackage(id: string): Promise<Package> {
  const { data } = await api.post<Package>(`/packages/${id}/retire`);
  return data;
}

export async function restorePackage(id: string): Promise<Package> {
  const { data } = await api.post<Package>(`/packages/${id}/restore`);
  return data;
}

export interface DeployTarget {
  machine_ids?: string[];
  target_all?: boolean;
  target_location?: string;
}

export async function deployPackage(
  id: string,
  action: DeployAction,
  target: DeployTarget,
): Promise<CreateCommandsResponse> {
  const { data } = await api.post<CreateCommandsResponse>('/commands', {
    type: action === 'install' ? 'package_install' : 'package_uninstall',
    package_id: id,
    ...target,
  });
  return data;
}

/** The deployments of a package, newest first, one page at a time. */
export async function listPackageCommands(
  id: string,
  page = 1,
  pageSize = 25,
  status: string | null = null,
): Promise<CommandList> {
  const { data } = await api.get<CommandList>('/commands', {
    params: { package_id: id, page, page_size: pageSize, ...(status ? { status } : {}) },
  });
  return data;
}

/** How the postes stand: each one's latest command for the package, counted. */
export interface PackageSummary {
  postes: number;
  by_status: Record<string, number>;
  by_action: Record<string, number>;
}

export async function getPackageSummary(id: string): Promise<PackageSummary> {
  const { data } = await api.get<PackageSummary>('/commands/package-summary', {
    params: { package_id: id },
  });
  return data;
}

export type { Command };

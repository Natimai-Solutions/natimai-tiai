import { api } from 'boot/axios';
import type { Command, CommandList, CreateCommandsResponse } from './commands';
import { frNumber } from 'src/utils/format';
import { intlTag, t } from 'src/i18n';

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
  /**
   * What fills the sentence the code names, worded by the console in its
   * reader's language (`utils/packageText`). Absent from an older server.
   */
  params?: Record<string, unknown>;
  /** The same sentence, in French, as the server writes it. */
  message: string;
  /**
   * Whether it stands in the way of an uninstallation too. Decided by the
   * server, which applies it itself when the command is queued: the agent
   * reads the whole manifest before either step, so most problems do — a
   * missing install step does not.
   */
  blocks_uninstall: boolean;
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
  /**
   * Method A: the files weigh more, together, than the postes download for an
   * unsigned package (their DeployMethodAMaxGB, the server's
   * PACKAGE_METHOD_A_MAX_GB). Computed by the server; `method_a_max_bytes` is
   * that bound, for the sentence that explains it.
   */
  method_a_too_large: boolean;
  method_a_max_bytes: number;
  /** The largest file an upload accepts (the server's PACKAGE_MAX_BYTES). */
  file_max_bytes: number;
  /** Why it cannot be deployed yet; empty when it can. */
  problems: PackageProblem[];
  /**
   * Why no poste would run an installation of it, one French sentence each:
   * what the server refuses a deployment with (409 package.not_ready) — the
   * problems above, or else why neither method B nor method A carries it,
   * naming the file in the way. Empty when some poste could install it. A
   * retirement is said by `retired_at`, not here.
   */
  install_blockers: string[];
  /** The same, as codes to word in the reader's language; absent from an older server. */
  install_blocker_problems?: PackageProblem[];
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
  if (action === 'uninstall' && p.uninstall_run === 'msiexec')
    // Method A rebuilds it as /x {code} /qn /norestart: nothing else is run,
    // and nothing is downloaded — the size of the files does not count.
    return p.uninstall_args.some((a) => PRODUCT_CODE.test(a)) ? 'product_code' : 'none';
  // The agent caps what an unsigned manifest may have it download
  // (deploy.MethodAFiles); the server says whether this package is over.
  return methodAExecutable(p, action) && !p.method_a_too_large ? 'publisher' : 'none';
}

/** An .exe of the package, signed by a publisher, nothing loadable beside it. */
function methodAExecutable(p: Package, action: DeployAction): boolean {
  const run = (action === 'install' ? p.install_run : p.uninstall_run) ?? '';
  return (
    !!publisherOf(p, action) &&
    run.toLowerCase().endsWith('.exe') &&
    loadableBeside(p, action).length === 0
  );
}

/**
 * The files beside the one the step runs that Windows could load or run from
 * that folder: what makes every poste refuse the step under method A, named
 * where the console explains why method A does not carry it.
 */
export function loadableBeside(p: Package, action: DeployAction = 'install'): string[] {
  const run = (action === 'install' ? p.install_run : p.uninstall_run) ?? '';
  return (p.files ?? [])
    .filter((f) => f.name !== run && LOADABLE_EXTENSIONS.has(extension(f.name)))
    .map((f) => f.name)
    .sort(compareFileNames);
}

/**
 * Method A would carry the step but for the weight of the files: the one
 * `none` whose way out is said differently — sign it, nothing else is wrong.
 */
export function tooLargeForMethodA(p: Package, action: DeployAction): boolean {
  return (
    p.kind === 'files' &&
    !p.signed &&
    p.method_a_too_large &&
    !(action === 'uninstall' && p.uninstall_run === 'msiexec') &&
    methodAExecutable(p, action)
  );
}

/** The Authenticode signer of the file the step runs, if it is one. */
export function publisherOf(p: Package, action: DeployAction = 'install'): string | null {
  if (action === 'install') return p.publisher_name;
  const run = p.uninstall_run;
  return (p.files ?? []).find((f) => f.name === run)?.publisher_name ?? null;
}

/** The method A bound as the sentences say it: whole Gio, as it is set. */
export function methodAMaxLabel(p: Package): string {
  return t('packagePages.size.gib', { n: Math.round(p.method_a_max_bytes / 1024 ** 3) });
}

/** How the package reaches a poste, in a word (a chip of the lists). */
export function trustLabel(method: TrustMethod): string {
  return t(`packagePages.trust.${method}`);
}

/**
 * File names as a French reader sorts them: case and accents aside, digits by
 * value (« setup2 » before « setup10 »). A plain sort put « Z.exe » before
 * « a.ini » and « été.txt » after « zip.cab ».
 */
export function compareFileNames(a: string, b: string): number {
  return (
    a.localeCompare(b, 'fr', { sensitivity: 'base', numeric: true }) || (a < b ? -1 : a > b ? 1 : 0)
  );
}

/** The package's files in that order. */
export function sortedFiles(p: Package): PackageFile[] {
  return [...(p.files ?? [])].sort((a, b) => compareFileNames(a.name, b.name));
}

function safeStem(text: string): string {
  return text.replace(/[^A-Za-z0-9._-]+/g, '-').replace(/^[-.]+|[-.]+$/g, '');
}

/**
 * The name the manifest is saved under: the server's (packages.py
 * manifest_file_stem). A name written in another script keeps no character a
 * file system takes everywhere: the package id stands in for it — never a
 * bare `.tiai-manifest.json`, which is a hidden file.
 */
export function manifestFileName(p: Package): string {
  const name = safeStem(p.name) || p.id;
  const version = safeStem(p.version ?? '');
  return `${version ? `${name}-${version}` : name}.tiai-manifest.json`;
}

/**
 * How a package reads in a list to choose from: name and version, and — when
 * another package reads the same — what tells them apart: its kind (winget
 * identifier, or the file it runs) and its creation date.
 */
export function packageChoiceLabel(p: Package, among: Package[]): string {
  const base = p.version ? `${p.name} ${p.version}` : p.name;
  const twins = among.filter(
    (o) => o.id !== p.id && (o.version ? `${o.name} ${o.version}` : o.name) === base,
  );
  if (!twins.length) return base;
  const kind =
    p.kind === 'winget'
      ? t('packagePages.choice.winget', { id: p.winget_id ?? '' }).trim()
      : t('packagePages.choice.files', {
          run: p.install_run ?? t('packagePages.choice.noRun'),
        });
  const created = new Date(p.created_at).toLocaleString(intlTag(), {
    dateStyle: 'short',
    timeStyle: 'short',
  });
  return t('packagePages.choice.label', { base, kind, created });
}

/** Ready to deploy: complete, not retired. */
export function deployable(p: Package): boolean {
  return p.retired_at === null && p.problems.length === 0;
}

/**
 * What stands in the way of the step. An uninstallation is held back only by
 * what the agent would refuse it for — the server's flag on each problem,
 * which it applies itself when the command is queued — and a retired package
 * is still uninstalled: taking it off the parc is what one does with it.
 */
export function blockingProblems(p: Package, action: DeployAction): PackageProblem[] {
  return action === 'install' ? p.problems : p.problems.filter((x) => x.blocks_uninstall);
}

/** Can be uninstalled: it says how, and nothing the agent would refuse. */
export function uninstallable(p: Package): boolean {
  if (p.kind === 'winget') return true;
  return !!p.uninstall_run && blockingProblems(p, 'uninstall').length === 0;
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
  if (bytes < 1024) return t('packagePages.size.bytes', { n: bytes });
  const units = ['kib', 'mib', 'gib'];
  let value = bytes / 1024;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit++;
  }
  return t(`packagePages.size.${units[unit]}`, { n: frNumber(value, value < 10 ? 1 : 0) });
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

/**
 * The files the server would refuse for their size, checked before sending:
 * refused after the transfer, a large file costs minutes for nothing. The
 * bound is the server's own (PACKAGE_MAX_BYTES, which a deployment sets
 * anywhere up to 8 Gio), as the package reports it — never a figure compiled
 * in here.
 */
export function tooLargeFiles(p: Package, files: File[]): File[] {
  return files.filter((f) => f.size > p.file_max_bytes);
}

/** Upload files, reporting progress as a fraction (0–1). */
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

/**
 * The deployments of a package, newest batch first, each batch by poste name,
 * one page at a time. `latest`: each poste's latest deployment only — the
 * rows the summary counts.
 */
export async function listPackageCommands(
  id: string,
  page = 1,
  pageSize = 25,
  status: string | null = null,
  latest = false,
): Promise<CommandList> {
  const { data } = await api.get<CommandList>('/commands', {
    params: {
      package_id: id,
      page,
      page_size: pageSize,
      ...(status ? { status } : {}),
      ...(latest ? { latest: true } : {}),
    },
  });
  return data;
}

/** How the postes stand: each one's latest command for the package, counted. */
export interface PackageSummary {
  postes: number;
  by_status: Record<string, number>;
  by_action: Record<string, number>;
  /** Installations no poste has received yet: what a retirement cancels. */
  pending_installs: number;
}

export async function getPackageSummary(id: string): Promise<PackageSummary> {
  const { data } = await api.get<PackageSummary>('/commands/package-summary', {
    params: { package_id: id },
  });
  return data;
}

export type { Command };

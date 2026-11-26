import type { AxiosError } from 'axios';
import { api } from 'boot/axios';
import { errorCodeMessage, t } from 'src/i18n';
import { apiErrorMessage, type ApiErrorBody } from 'src/services/errors';
import { downloadBlob, formatSize } from 'src/utils/format';

/**
 * Attachments of the journal (C11, dev/plan-procedures-pieces-jointes.md):
 * photos and PDFs on a line of a poste's journal. Read and downloaded with
 * `intervention:read`, added and deleted with `intervention:write`. The
 * server recognises the type from the content and always serves the file as
 * a download; the console checks size and type before sending, after the
 * server's own policy — it copies no limit — and the server stays the judge.
 */

export interface AttachmentOut {
  id: string;
  intervention_id: string;
  filename: string;
  /** As the server recognised it from the content: never the client's. */
  content_type: string;
  size: number;
  uploaded_by: string;
  created_at: string;
}

export interface AttachmentPolicy {
  max_bytes: number;
  max_per_intervention: number;
  types: string[];
  /** 0 = no quota. */
  quota_bytes: number;
  /** Null for an account confined to some sites: a total of the whole parc. */
  used_bytes: number | null;
  /** 0 = kept. */
  retention_days: number;
  /** False: the server's volume is not mounted, uploads are refused (503). */
  store_available: boolean;
}

/** What the file input offers: the four types the server accepts. */
export const ATTACHMENT_ACCEPT = 'image/jpeg,image/png,image/webp,application/pdf';

/** The longest side of a photo once redrawn. */
export const IMAGE_MAX_SIDE = 2560;
/** The JPEG quality a photo is redrawn at. */
export const JPEG_QUALITY = 0.85;
/** From this share of the quota the console warns. */
export const QUOTA_WARN_RATIO = 0.9;

export async function getAttachmentPolicy(): Promise<AttachmentPolicy> {
  const { data } = await api.get<AttachmentPolicy>('/attachments/policy');
  return data;
}

/** Upload one file to a line (one per request), reporting progress (0–1). */
export async function uploadAttachment(
  interventionId: string,
  file: File,
  onProgress?: (fraction: number) => void,
): Promise<AttachmentOut> {
  const form = new FormData();
  form.append('file', file, file.name);
  const { data } = await api.post<AttachmentOut>(
    `/interventions/${interventionId}/attachments`,
    form,
    {
      onUploadProgress: (e) => {
        if (onProgress && e.total) onProgress(e.loaded / e.total);
      },
    },
  );
  return data;
}

export async function deleteAttachment(id: string): Promise<void> {
  await api.delete(`/attachments/${id}`);
}

/**
 * An error answered to a `responseType: 'blob'` request carries its JSON
 * envelope as a Blob: read it back, so `apiErrorMessage` finds the code
 * (« fichier absent du serveur »).
 */
async function withJsonBody(err: unknown): Promise<unknown> {
  const response = (err as AxiosError<unknown>)?.response;
  const data = response?.data;
  if (response && typeof Blob !== 'undefined' && data instanceof Blob) {
    try {
      response.data = JSON.parse(await data.text()) as ApiErrorBody;
    } catch {
      // Not JSON: left as it was, the fallback message applies.
    }
  }
  return err;
}

async function fetchContent(a: AttachmentOut): Promise<Blob> {
  try {
    const { data } = await api.get<Blob>(`/attachments/${a.id}/content`, {
      responseType: 'blob',
    });
    return data;
  } catch (e) {
    throw await withJsonBody(e);
  }
}

/**
 * Download an attachment under its name. Fetched rather than linked: the
 * API needs the Authorization header, which a plain `<a href>` would not carry.
 */
export async function downloadAttachment(a: AttachmentOut): Promise<void> {
  downloadBlob(await fetchContent(a), a.filename);
}

/** Whether the console shows an attachment as an image preview. */
export function isPreviewable(a: Pick<AttachmentOut, 'content_type'>): boolean {
  return ['image/jpeg', 'image/png', 'image/webp'].includes(a.content_type);
}

/** A blob as a `data:` URL of the given type, read as bytes then base64. */
async function dataUrlOf(blob: Blob, type: string): Promise<string> {
  const bytes = new Uint8Array(await blob.arrayBuffer());
  let binary = '';
  // By slices: one call with millions of arguments would overflow the stack.
  for (let i = 0; i < bytes.length; i += 0x8000) {
    binary += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  }
  return `data:${type};base64,${btoa(binary)}`;
}

/**
 * An image attachment as a `data:` URL, for the preview. Not a `blob:` URL:
 * the console's CSP allows `'self'` and `data:` only in `img-src`
 * (deploy/Caddyfile). The type is the one the server recognised, never
 * anything else: a preview is only ever an image.
 */
export async function attachmentDataUrl(a: AttachmentOut): Promise<string> {
  if (!isPreviewable(a)) throw new Error('not an image');
  const blob = await fetchContent(a);
  return dataUrlOf(blob, a.content_type);
}

/** Why the console does not send a file, before sending it; null when it may. */
export type AttachmentRefusal = 'type' | 'size';

export function attachmentRefusal(file: File, policy: AttachmentPolicy): AttachmentRefusal | null {
  if (!policy.types.includes(file.type)) return 'type';
  if (file.size > policy.max_bytes) return 'size';
  return null;
}

/** The quota is nearly used up: the console says so beside the upload. */
export function quotaNearlyFull(policy: AttachmentPolicy): boolean {
  return (
    policy.quota_bytes > 0 &&
    policy.used_bytes !== null &&
    policy.used_bytes >= policy.quota_bytes * QUOTA_WARN_RATIO
  );
}

/** A refused upload in words. The proxy's own 413 has no envelope. */
export function attachmentErrorMessage(err: unknown): string {
  const response = (err as AxiosError<ApiErrorBody>)?.response;
  if (response?.status === 413 && !response.data?.error?.code) {
    return errorCodeMessage('attachment.too_large') ?? t('interventions.attachments.uploadFailed');
  }
  return apiErrorMessage(err, t('interventions.attachments.uploadFailed'));
}

/** `name` with the extension `ext` in place of its own. */
function withExtension(name: string, ext: string): string {
  const dot = name.lastIndexOf('.');
  const base = dot > 0 ? name.slice(0, dot) : name;
  return `${base}.${ext}`;
}

/** The canvas a photo is redrawn on; a function so the specs can replace it. */
export const canvasFactory = {
  create(width: number, height: number): HTMLCanvasElement {
    const canvas = document.createElement('canvas');
    canvas.width = width;
    canvas.height = height;
    return canvas;
  },
};

/** What the first bytes of a file say it is, whatever its extension. */
async function sniffImage(file: File): Promise<'photo' | 'png' | null> {
  let head: Uint8Array;
  try {
    head = new Uint8Array(await file.slice(0, 12).arrayBuffer());
  } catch {
    return null;
  }
  const ascii = (from: number, to: number) => String.fromCharCode(...head.subarray(from, to));
  if (head[0] === 0xff && head[1] === 0xd8 && head[2] === 0xff) return 'photo';
  if (ascii(0, 4) === 'RIFF' && ascii(8, 12) === 'WEBP') return 'photo';
  if (head[0] === 0x89 && ascii(1, 4) === 'PNG') return 'png';
  return null;
}

/**
 * A file as it is sent (plan §2.1): every JPEG and every WebP is redrawn —
 * which drops its EXIF metadata, a phone's GPS position included, even for a
 * small or cropped photo — at most 2 560 px a side, as a JPEG at 0.85; a PNG
 * stays a PNG while it fits the size limit and 2 560 px, else it is redrawn
 * as a JPEG too; a PDF, and anything else, is left as it is (the type check
 * then speaks). What a file is, is read from its first bytes as the server
 * does, the extension (the browser's type) only failing that. The server never touches a file it receives.
 */
export async function prepareImage(file: File, policy: AttachmentPolicy | null): Promise<File> {
  // The browser's type comes from the extension; the server's from the
  // content: a JPEG named `.png` or `.pdf` is a photo all the same.
  const sniffed = await sniffImage(file);
  const photo = sniffed === 'photo' || file.type === 'image/jpeg' || file.type === 'image/webp';
  if (!photo && sniffed !== 'png' && file.type !== 'image/png') return file;
  const bitmap = await createImageBitmap(file, { imageOrientation: 'from-image' });
  try {
    const { width, height } = bitmap;
    const longest = Math.max(width, height);
    const fits = policy === null || file.size <= policy.max_bytes;
    if (!photo && fits && longest <= IMAGE_MAX_SIDE) return file;
    const scale = longest > IMAGE_MAX_SIDE ? IMAGE_MAX_SIDE / longest : 1;
    const w = Math.max(1, Math.round(width * scale));
    const h = Math.max(1, Math.round(height * scale));
    const canvas = canvasFactory.create(w, h);
    const context = canvas.getContext('2d');
    if (!context) throw new Error('no 2d context');
    context.drawImage(bitmap, 0, 0, w, h);
    const blob = await new Promise<Blob>((resolve, reject) =>
      canvas.toBlob(
        (b) => (b ? resolve(b) : reject(new Error('toBlob failed'))),
        'image/jpeg',
        JPEG_QUALITY,
      ),
    );
    return new File([blob], withExtension(file.name, 'jpg'), { type: 'image/jpeg' });
  } finally {
    bitmap.close();
  }
}

/**
 * A picked file made ready to send — redrawn when it is a photo — or why it
 * is not sent, in words. `count` is how many files the line already holds
 * (queued ones included). Without a policy (the account cannot read it), the
 * photo is still redrawn and the server alone judges the rest.
 */
export async function prepareForUpload(
  file: File,
  policy: AttachmentPolicy | null,
  count: number,
): Promise<{ file: File } | { reason: string }> {
  if (policy && count >= policy.max_per_intervention) {
    return {
      reason: t('interventions.attachments.reasons.tooMany', { max: policy.max_per_intervention }),
    };
  }
  if (policy && !policy.types.includes(file.type)) {
    return { reason: t('interventions.attachments.reasons.type') };
  }
  let prepared: File;
  try {
    prepared = await prepareImage(file, policy);
  } catch {
    // Never the original instead: a photo would leave with its position.
    return { reason: t('interventions.attachments.reasons.unreadable') };
  }
  const refusal = policy ? attachmentRefusal(prepared, policy) : null;
  if (refusal === 'type') return { reason: t('interventions.attachments.reasons.type') };
  if (refusal === 'size') {
    return {
      reason: t('interventions.attachments.reasons.size', { max: formatSize(policy!.max_bytes) }),
    };
  }
  return { file: prepared };
}

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('boot/axios', () => ({
  api: { get: vi.fn(), post: vi.fn(), delete: vi.fn() },
}));
vi.mock('src/utils/format', async (importOriginal) => ({
  ...(await importOriginal<typeof import('src/utils/format')>()),
  downloadBlob: vi.fn(),
}));

import { api } from 'boot/axios';
import { setLocale } from 'src/i18n';
import { downloadBlob } from 'src/utils/format';
import {
  attachmentDataUrl,
  attachmentErrorMessage,
  canvasFactory,
  deleteAttachment,
  downloadAttachment,
  IMAGE_MAX_SIDE,
  JPEG_QUALITY,
  prepareForUpload,
  prepareImage,
  quotaNearlyFull,
  uploadAttachment,
  type AttachmentOut,
  type AttachmentPolicy,
} from './attachments';

const POLICY: AttachmentPolicy = {
  max_bytes: 5 * 1024 * 1024,
  max_per_intervention: 10,
  types: ['image/jpeg', 'image/png', 'image/webp', 'application/pdf'],
  quota_bytes: 2 * 1024 ** 3,
  used_bytes: 0,
  retention_days: 0,
  store_available: true,
};

const ATTACHMENT: AttachmentOut = {
  id: 'a1',
  intervention_id: 'i1',
  filename: 'panne écran.png',
  content_type: 'image/png',
  size: 2048,
  uploaded_by: 'tech@x',
  created_at: '2026-11-25T10:00:00Z',
};

function file(name: string, type: string, size = 1000): File {
  const f = new File([new Uint8Array(Math.min(size, 16))], name, { type });
  Object.defineProperty(f, 'size', { value: size });
  return f;
}

/** A bitmap of the given size, and the canvas it is drawn on. */
function fakeImage(width: number, height: number) {
  const bitmap = { width, height, close: vi.fn() };
  vi.stubGlobal(
    'createImageBitmap',
    vi.fn(() => Promise.resolve(bitmap)),
  );
  const drawImage = vi.fn();
  const canvas = {
    width: 0,
    height: 0,
    getContext: vi.fn(() => ({ drawImage })),
    toBlob: vi.fn((done: (b: Blob | null) => void, type: string) =>
      done(new Blob(['redrawn'], { type })),
    ),
  };
  const create = vi.spyOn(canvasFactory, 'create').mockImplementation((w, h) => {
    canvas.width = w;
    canvas.height = h;
    return canvas as unknown as HTMLCanvasElement;
  });
  return { bitmap, canvas, create, drawImage };
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  setLocale('fr');
});

describe('prepareImage', () => {
  it('redraws every JPEG, even a small one — its EXIF (GPS position) does not leave', async () => {
    const { canvas, create, bitmap } = fakeImage(800, 600);
    const out = await prepareImage(file('IMG_0001.JPG', 'image/jpeg', 30_000), POLICY);
    expect(createImageBitmap).toHaveBeenCalledWith(expect.any(File), {
      imageOrientation: 'from-image',
    });
    expect(create).toHaveBeenCalledWith(800, 600);
    expect(canvas.toBlob).toHaveBeenCalledWith(expect.any(Function), 'image/jpeg', JPEG_QUALITY);
    expect(out.type).toBe('image/jpeg');
    expect(out.name).toBe('IMG_0001.jpg');
    expect(bitmap.close).toHaveBeenCalled();
  });

  it('redraws every WebP as a JPEG', async () => {
    fakeImage(100, 100);
    const out = await prepareImage(file('capture.webp', 'image/webp', 500), POLICY);
    expect(out.type).toBe('image/jpeg');
    expect(out.name).toBe('capture.jpg');
  });

  it('scales a photo down to 2 560 px on its longest side', async () => {
    const { create } = fakeImage(4032, 3024);
    await prepareImage(file('photo.jpg', 'image/jpeg', 4_000_000), POLICY);
    expect(create).toHaveBeenCalledWith(IMAGE_MAX_SIDE, 1920);
  });

  it('keeps a small PNG as it is', async () => {
    const { create } = fakeImage(1200, 800);
    const png = file('ecran.png', 'image/png', 200_000);
    expect(await prepareImage(png, POLICY)).toBe(png);
    expect(create).not.toHaveBeenCalled();
  });

  it('redraws as a JPEG a PNG too large or too wide', async () => {
    fakeImage(1200, 800);
    const heavy = await prepareImage(file('lourd.png', 'image/png', 6 * 1024 * 1024), POLICY);
    expect(heavy.type).toBe('image/jpeg');
    fakeImage(5000, 800);
    const wide = await prepareImage(file('large.png', 'image/png', 100), POLICY);
    expect(wide.name).toBe('large.jpg');
  });

  it('never touches a PDF', async () => {
    const decode = vi.fn();
    vi.stubGlobal('createImageBitmap', decode);
    const pdf = file('facture.pdf', 'application/pdf', 3_000_000);
    expect(await prepareImage(pdf, POLICY)).toBe(pdf);
    expect(decode).not.toHaveBeenCalled();
  });
});

describe('prepareForUpload', () => {
  it('refuses, in words, a type the server does not take', async () => {
    const answer = await prepareForUpload(file('logo.svg', 'image/svg+xml'), POLICY, 0);
    expect(answer).toEqual({ reason: 'type non accepté (JPEG, PNG, WebP ou PDF seulement)' });
  });

  it('refuses a file still over the limit, naming the limit', async () => {
    const answer = await prepareForUpload(
      file('gros.pdf', 'application/pdf', 6 * 1024 * 1024),
      POLICY,
      0,
    );
    expect(answer).toEqual({ reason: 'plus de 5,0 Mio, même après réduction' });
  });

  it('refuses the eleventh file of a line', async () => {
    const answer = await prepareForUpload(file('a.pdf', 'application/pdf'), POLICY, 10);
    expect(answer).toEqual({ reason: '10 fichiers au plus par intervention' });
  });

  it('never sends the original of a photo the browser cannot read', async () => {
    vi.stubGlobal(
      'createImageBitmap',
      vi.fn(() => Promise.reject(new Error('decode'))),
    );
    const answer = await prepareForUpload(file('a.jpg', 'image/jpeg'), POLICY, 0);
    expect(answer).toEqual({ reason: 'image que le navigateur ne sait pas lire' });
  });

  it('without a policy, still redraws the photo and lets the server judge', async () => {
    fakeImage(10, 10);
    const answer = await prepareForUpload(file('a.jpg', 'image/jpeg'), null, 99);
    expect('file' in answer && answer.file.name).toBe('a.jpg');
  });
});

describe('the calls', () => {
  beforeEach(() => {
    vi.mocked(api.get).mockReset();
    vi.mocked(api.post).mockReset();
    vi.mocked(api.delete).mockReset();
  });

  it('sends one file per request, as the field `file`, with its progress', async () => {
    vi.mocked(api.post).mockResolvedValue({ data: ATTACHMENT });
    const progress = vi.fn();
    const out = await uploadAttachment('i1', file('a.pdf', 'application/pdf'), progress);
    expect(out).toEqual(ATTACHMENT);
    const [url, form, config] = vi.mocked(api.post).mock.calls[0]!;
    expect(url).toBe('/interventions/i1/attachments');
    expect((form as FormData).getAll('file')).toHaveLength(1);
    (config as { onUploadProgress: (e: object) => void }).onUploadProgress({
      loaded: 1,
      total: 4,
    });
    expect(progress).toHaveBeenCalledWith(0.25);
  });

  it('downloads under the attachment’s name', async () => {
    const blob = new Blob(['x'], { type: 'image/png' });
    vi.mocked(api.get).mockResolvedValue({ data: blob });
    await downloadAttachment(ATTACHMENT);
    expect(api.get).toHaveBeenCalledWith('/attachments/a1/content', { responseType: 'blob' });
    expect(downloadBlob).toHaveBeenCalledWith(blob, 'panne écran.png');
  });

  it('reads the error envelope a blob request got, to name it', async () => {
    const body = new Blob([JSON.stringify({ error: { code: 'attachment.file_missing' } })], {
      type: 'application/json',
    });
    vi.mocked(api.get).mockRejectedValue({ response: { status: 404, data: body } });
    const error = await downloadAttachment(ATTACHMENT).catch((e: unknown) => e);
    expect(attachmentErrorMessage(error)).toContain('Fichier absent du serveur');
  });

  it('previews an image as a data: URL of the recognised type, never a blob: URL', async () => {
    vi.mocked(api.get).mockResolvedValue({ data: new Blob(['png'], { type: 'text/html' }) });
    const url = await attachmentDataUrl(ATTACHMENT);
    expect(url.startsWith('data:image/png;base64,')).toBe(true);
    await expect(
      attachmentDataUrl({ ...ATTACHMENT, content_type: 'application/pdf' }),
    ).rejects.toThrow();
  });

  it('deletes by id', async () => {
    vi.mocked(api.delete).mockResolvedValue({});
    await deleteAttachment('a1');
    expect(api.delete).toHaveBeenCalledWith('/attachments/a1');
  });
});

describe('the words around a refusal', () => {
  it('names the proxy’s own 413 as a file too large', () => {
    expect(attachmentErrorMessage({ response: { status: 413, data: '<html>' } })).toBe(
      'Fichier trop volumineux pour une pièce jointe',
    );
    setLocale('en');
    expect(attachmentErrorMessage({ response: { status: 413 } })).toBe(
      'File too large for an attachment',
    );
  });

  it('says the quota is nearly used up from 90 %', () => {
    expect(quotaNearlyFull({ ...POLICY, quota_bytes: 100, used_bytes: 89 })).toBe(false);
    expect(quotaNearlyFull({ ...POLICY, quota_bytes: 100, used_bytes: 90 })).toBe(true);
    // No quota, or a total the account is not told.
    expect(quotaNearlyFull({ ...POLICY, quota_bytes: 0, used_bytes: 90 })).toBe(false);
    expect(quotaNearlyFull({ ...POLICY, quota_bytes: 100, used_bytes: null })).toBe(false);
  });
});

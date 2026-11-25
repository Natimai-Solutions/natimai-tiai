import { flushPromises, mount } from '@vue/test-utils';
import { QFile } from 'quasar';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const shown = vi.hoisted(() => [] as { type?: string; message?: string }[]);
vi.mock('src/utils/notify', () => ({
  notify: (_q: unknown, build: () => { type?: string; message?: string }) => {
    shown.push(build());
    return () => undefined;
  },
}));
const dialogs = vi.hoisted(() => [] as { message?: string }[]);
vi.mock('src/utils/liveDialog', () => ({
  liveDialog: (_q: unknown, build: () => { message?: string }) => {
    dialogs.push(build());
    return { onOk: (ok: () => void) => ok() };
  },
}));
vi.mock('src/services/attachments', async (importOriginal) => ({
  ...(await importOriginal<typeof import('src/services/attachments')>()),
  uploadAttachment: vi.fn(),
  deleteAttachment: vi.fn(),
  downloadAttachment: vi.fn(),
  attachmentDataUrl: vi.fn(),
}));

import {
  attachmentDataUrl,
  deleteAttachment,
  downloadAttachment,
  uploadAttachment,
  type AttachmentOut,
  type AttachmentPolicy,
} from 'src/services/attachments';
import { setLocale } from 'src/i18n';
import InterventionAttachments from './InterventionAttachments.vue';

const POLICY: AttachmentPolicy = {
  max_bytes: 5 * 1024 * 1024,
  max_per_intervention: 10,
  types: ['image/jpeg', 'image/png', 'image/webp', 'application/pdf'],
  quota_bytes: 2 * 1024 ** 3,
  used_bytes: 1024 ** 3,
  retention_days: 0,
  store_available: true,
};

function attachment(fields: Partial<AttachmentOut> = {}): AttachmentOut {
  return {
    id: 'a1',
    intervention_id: 'i1',
    filename: 'ecran.png',
    content_type: 'image/png',
    size: 1536,
    uploaded_by: 'tech@x',
    created_at: '2026-11-25T10:00:00Z',
    ...fields,
  };
}

const PDF = attachment({
  id: 'a2',
  filename: 'facture.pdf',
  content_type: 'application/pdf',
  size: 250 * 1024 * 1024,
});

function file(name: string, type: string, size = 1000): File {
  const f = new File(['x'], name, { type });
  Object.defineProperty(f, 'size', { value: size });
  return f;
}

function mountList(props: Record<string, unknown> = {}) {
  return mount(InterventionAttachments, {
    props: { attachments: [attachment(), PDF], ...props },
    attachTo: document.body,
  });
}

async function pick(wrapper: ReturnType<typeof mountList>, files: File[]) {
  wrapper.findComponent(QFile).vm.$emit('update:modelValue', files);
  await flushPromises();
}

beforeEach(() => {
  shown.length = 0;
  dialogs.length = 0;
  vi.mocked(uploadAttachment).mockReset();
  vi.mocked(deleteAttachment).mockReset();
  vi.mocked(downloadAttachment).mockReset();
  vi.mocked(attachmentDataUrl).mockReset();
});

describe('InterventionAttachments — reading', () => {
  it('shows a chip per file, with its icon and size', () => {
    const wrapper = mountList();
    const chips = wrapper.findAll('[data-test="attachment-chip"]');
    expect(chips).toHaveLength(2);
    expect(chips[0]!.text()).toContain('ecran.png');
    expect(chips[0]!.text()).toContain('1,5 Kio');
    expect(chips[0]!.html()).toContain('image');
    expect(chips[1]!.text()).toContain('250 Mio');
    expect(chips[1]!.html()).toContain('picture_as_pdf');
    wrapper.unmount();
  });

  it('downloads a file on a click', async () => {
    vi.mocked(downloadAttachment).mockResolvedValue();
    const wrapper = mountList();
    await wrapper.findAll('[data-test="attachment-chip"]')[1]!.trigger('click');
    await flushPromises();
    expect(downloadAttachment).toHaveBeenCalledWith(PDF);
    wrapper.unmount();
  });

  it('says why a download failed — a file missing from the server', async () => {
    vi.mocked(downloadAttachment).mockRejectedValue({
      response: { status: 404, data: { error: { code: 'attachment.file_missing' } } },
    });
    const wrapper = mountList();
    await wrapper.findAll('[data-test="attachment-chip"]')[0]!.trigger('click');
    await flushPromises();
    expect(shown.at(-1)!.message).toContain('Fichier absent du serveur');
    wrapper.unmount();
  });

  it('previews an image as a data: URL, and offers no preview for a PDF', async () => {
    vi.mocked(attachmentDataUrl).mockResolvedValue('data:image/png;base64,eA==');
    const wrapper = mountList();
    const buttons = wrapper.findAll('[data-test="attachment-preview"]');
    expect(buttons).toHaveLength(1);
    await buttons[0]!.trigger('click');
    await flushPromises();
    // The click on the preview does not download as well.
    expect(downloadAttachment).not.toHaveBeenCalled();
    const img = document.body.querySelector(
      '[data-test="attachment-preview-image"]',
    ) as HTMLImageElement;
    expect(img.getAttribute('src')).toBe('data:image/png;base64,eA==');
    wrapper.unmount();
  });

  it('has neither deletion nor upload in reading', () => {
    const wrapper = mountList();
    expect(wrapper.find('.q-chip__icon--remove').exists()).toBe(false);
    expect(wrapper.findComponent(QFile).exists()).toBe(false);
    wrapper.unmount();
  });
});

describe('InterventionAttachments — in the line’s dialog', () => {
  it('deletes a file once confirmed, and says the line changed', async () => {
    vi.mocked(deleteAttachment).mockResolvedValue();
    const wrapper = mountList({ editable: true, interventionId: 'i1', policy: POLICY });
    await wrapper.findAll('.q-chip__icon--remove')[1]!.trigger('click');
    await flushPromises();
    expect(dialogs[0]!.message).toContain('« facture.pdf »');
    expect(deleteAttachment).toHaveBeenCalledWith('a2');
    expect(wrapper.findAll('[data-test="attachment-chip"]')).toHaveLength(1);
    expect(wrapper.emitted('changed')).toHaveLength(1);
    wrapper.unmount();
  });

  it('refuses before sending a type or a size out of the policy', async () => {
    const wrapper = mountList({ editable: true, interventionId: 'i1', policy: POLICY });
    await pick(wrapper, [
      file('logo.svg', 'image/svg+xml'),
      file('gros.pdf', 'application/pdf', 6 * 1024 * 1024),
    ]);
    expect(uploadAttachment).not.toHaveBeenCalled();
    expect(shown.map((n) => n.message)).toEqual([
      '« logo.svg » non envoyé : type non accepté (JPEG, PNG, WebP ou PDF seulement)',
      '« gros.pdf » non envoyé : plus de 5,0 Mio, même après réduction',
    ]);
    wrapper.unmount();
  });

  it('sends a file to an existing line at once', async () => {
    vi.mocked(uploadAttachment).mockResolvedValue(
      attachment({ id: 'a3', filename: 'bon.pdf', content_type: 'application/pdf' }),
    );
    const wrapper = mountList({ editable: true, interventionId: 'i1', policy: POLICY });
    await pick(wrapper, [file('bon.pdf', 'application/pdf')]);
    expect(uploadAttachment).toHaveBeenCalledWith('i1', expect.any(File), expect.any(Function));
    expect(wrapper.findAll('[data-test="attachment-chip"]')).toHaveLength(3);
    expect(wrapper.emitted('changed')).toHaveLength(1);
    wrapper.unmount();
  });

  it('shows the server’s refusal', async () => {
    vi.mocked(uploadAttachment).mockRejectedValue({
      response: { status: 409, data: { error: { code: 'attachment.duplicate' } } },
    });
    const wrapper = mountList({ editable: true, interventionId: 'i1', policy: POLICY });
    await pick(wrapper, [file('bon.pdf', 'application/pdf')]);
    expect(shown.at(-1)!.message).toBe(
      '« bon.pdf » non envoyé : Ce fichier est déjà joint à cette ligne',
    );
    expect(wrapper.emitted('changed')).toBeUndefined();
    wrapper.unmount();
  });

  it('keeps the files of a line not created yet, to send once it is', async () => {
    const wrapper = mountList({ attachments: [], editable: true, policy: POLICY });
    await pick(wrapper, [file('bon.pdf', 'application/pdf')]);
    expect(uploadAttachment).not.toHaveBeenCalled();
    const queued = wrapper.emitted('update:queued')!.at(-1)![0] as File[];
    expect(queued.map((f) => f.name)).toEqual(['bon.pdf']);
    expect(wrapper.findAll('[data-test="attachment-queued"]')).toHaveLength(1);
    wrapper.unmount();
  });

  it('greys the upload out, and says why, when the server has no volume', () => {
    const wrapper = mountList({
      editable: true,
      interventionId: 'i1',
      policy: { ...POLICY, store_available: false },
    });
    expect(wrapper.find('[data-test="attachment-store-unavailable"]').text()).toContain(
      'n’est pas monté sur le serveur',
    );
    expect(wrapper.findComponent(QFile).props('disable')).toBe(true);
    wrapper.unmount();
  });

  it('warns from 90 % of the quota, and states the retention', () => {
    const wrapper = mountList({
      editable: true,
      interventionId: 'i1',
      policy: { ...POLICY, used_bytes: 1.9 * 1024 ** 3, retention_days: 1825 },
    });
    expect(wrapper.find('[data-test="attachment-quota"]').text()).toBe(
      'Pièces jointes : 1,9 Gio sur 2,0 Gio ; supprimez des pièces jointes ou demandez une hausse du quota.',
    );
    expect(wrapper.text()).toContain('Pièces jointes conservées 1825 jours.');
    wrapper.unmount();
  });

  it('does not warn below 90 %', () => {
    const wrapper = mountList({ editable: true, interventionId: 'i1', policy: POLICY });
    expect(wrapper.find('[data-test="attachment-quota"]').exists()).toBe(false);
    expect(wrapper.text()).toContain('sans limite de durée');
    wrapper.unmount();
  });
});

describe('InterventionAttachments — in English', () => {
  it('words the sizes, the limits, the quota and the retention', () => {
    setLocale('en');
    try {
      const wrapper = mountList({
        editable: true,
        interventionId: 'i1',
        policy: { ...POLICY, used_bytes: 1.9 * 1024 ** 3, retention_days: 1 },
      });
      expect(wrapper.text()).toContain('1.5 KiB');
      expect(wrapper.text()).toContain('JPEG, PNG, WebP or PDF; 5.0 MiB at most per file');
      expect(wrapper.text()).toContain('Attachments kept 1 day.');
      expect(wrapper.find('[data-test="attachment-quota"]').text()).toBe(
        'Attachments: 1.9 GiB of 2.0 GiB; delete attachments or ask for a larger quota.',
      );
      wrapper.unmount();
    } finally {
      setLocale('fr');
    }
  });
});

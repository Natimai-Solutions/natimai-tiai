import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('boot/axios', () => ({
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));

import { api } from 'boot/axios';
import {
  createIntervention,
  deleteIntervention,
  INTERVENTION_KINDS,
  interventionHeading,
  interventionKindLabel,
  listInterventions,
  updateIntervention,
} from './interventions';

describe('interventions service', () => {
  beforeEach(() => {
    vi.mocked(api.get).mockReset();
    vi.mocked(api.post).mockReset();
    vi.mocked(api.patch).mockReset();
    vi.mocked(api.delete).mockReset();
  });

  it('lists a machine journal with its page', async () => {
    vi.mocked(api.get).mockResolvedValue({ data: { items: [], total: 0, page: 2, page_size: 25 } });
    await listInterventions('m-1', { page: 2, page_size: 25 });
    expect(api.get).toHaveBeenCalledWith('/machines/m-1/interventions', {
      params: { page: 2, page_size: 25 },
    });
  });

  it('creates under the machine, edits and deletes by id', async () => {
    vi.mocked(api.post).mockResolvedValue({ data: {} });
    vi.mocked(api.patch).mockResolvedValue({ data: {} });
    vi.mocked(api.delete).mockResolvedValue({ data: undefined });
    await createIntervention('m-1', { kind: 'incident', title: 'Écran noir' });
    await updateIntervention('i-1', { note: 'Câble remplacé' });
    await deleteIntervention('i-1');
    expect(api.post).toHaveBeenCalledWith('/machines/m-1/interventions', {
      kind: 'incident',
      title: 'Écran noir',
    });
    expect(api.patch).toHaveBeenCalledWith('/interventions/i-1', { note: 'Câble remplacé' });
    expect(api.delete).toHaveBeenCalledWith('/interventions/i-1');
  });
});

describe('intervention kinds', () => {
  it('covers the backend list exactly once, with a label each', () => {
    expect(INTERVENTION_KINDS.map((k) => k.value).sort()).toEqual(
      ['incident', 'maintenance', 'other', 'software_install', 'upgrade', 'verification'].sort(),
    );
    expect(interventionKindLabel('incident')).toBe('Panne / incident');
    expect(interventionKindLabel('unknown')).toBe('unknown');
  });
});

describe('interventionHeading (journal titles without the kind twice)', () => {
  it('drops a title that only repeats the kind', () => {
    expect(interventionHeading({ kind: 'verification', title: 'Vérification' })).toBe(
      'Vérification',
    );
    expect(interventionHeading({ kind: 'maintenance', title: 'Maintenance' })).toBe('Maintenance');
  });

  it('drops the kind at the head of an old title', () => {
    expect(interventionHeading({ kind: 'maintenance', title: 'Maintenance — A101' })).toBe(
      'Maintenance — A101',
    );
  });

  it('keeps a title of its own, and a word that only starts like the kind', () => {
    expect(interventionHeading({ kind: 'maintenance', title: 'A101' })).toBe('Maintenance — A101');
    expect(interventionHeading({ kind: 'maintenance', title: 'Maintenance non faite' })).toBe(
      'Maintenance — Maintenance non faite',
    );
    expect(interventionHeading({ kind: 'other', title: 'Maintenance non faite — B12' })).toBe(
      'Autre — Maintenance non faite — B12',
    );
    expect(interventionHeading({ kind: 'incident', title: null })).toBe('Panne / incident');
  });
});

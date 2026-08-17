import { describe, expect, it } from 'vitest';
import { boolLabel, formatDateTime, sessionColor, sessionLabel, sessionTypeLabel } from './format';

describe('formatDateTime', () => {
  it('renders a dash when there is no timestamp', () => {
    expect(formatDateTime(null)).toBe('—');
    expect(formatDateTime(undefined)).toBe('—');
    expect(formatDateTime('')).toBe('—');
  });

  it('formats an ISO timestamp in the French locale', () => {
    // Asserted through the same API the helper uses, so the test does not
    // depend on the runner's timezone.
    const iso = '2026-08-17T09:12:03Z';
    expect(formatDateTime(iso)).toBe(new Date(iso).toLocaleString('fr-FR'));
  });
});

describe('boolLabel', () => {
  it('distinguishes unknown from false', () => {
    expect(boolLabel(null)).toBe('Inconnu');
    expect(boolLabel(undefined)).toBe('Inconnu');
    expect(boolLabel(true)).toBe('Oui');
    expect(boolLabel(false)).toBe('Non');
  });
});

describe('sessionLabel', () => {
  it('reports unknown when the agent never sent a session', () => {
    expect(sessionLabel(null, null)).toBe('Inconnu');
    expect(sessionLabel(undefined, undefined)).toBe('Inconnu');
    // A stale name must not leak through an unknown presence.
    expect(sessionLabel(null, 'CORP\\jdupont')).toBe('Inconnu');
  });

  it('reports nobody when no session is open', () => {
    expect(sessionLabel(false, null)).toBe('Aucun utilisateur');
  });

  it('shows the name when the agent reports it', () => {
    expect(sessionLabel(true, 'CORP\\jdupont')).toBe('CORP\\jdupont');
  });

  it('falls back to a presence-only label when the name is withheld', () => {
    expect(sessionLabel(true, null)).toBe('Utilisateur connecté');
    expect(sessionLabel(true, '')).toBe('Utilisateur connecté');
  });
});

describe('sessionColor', () => {
  it('greys out unknown and empty machines, highlights occupied ones', () => {
    expect(sessionColor(null)).toBe('grey-6');
    expect(sessionColor(undefined)).toBe('grey-6');
    expect(sessionColor(false)).toBe('grey-5');
    expect(sessionColor(true)).toBe('primary');
  });
});

describe('sessionTypeLabel', () => {
  it('renders a dash when the state is unknown', () => {
    expect(sessionTypeLabel(null, null)).toBe('—');
    expect(sessionTypeLabel(undefined, false)).toBe('—');
    expect(sessionTypeLabel('', true)).toBe('—');
  });

  it('combines connection state and session kind', () => {
    expect(sessionTypeLabel('active', false)).toBe('Active (console)');
    expect(sessionTypeLabel('active', true)).toBe('Active (Bureau à distance)');
    expect(sessionTypeLabel('disconnected', false)).toBe('Déconnectée (console)');
    expect(sessionTypeLabel('disconnected', true)).toBe('Déconnectée (Bureau à distance)');
  });

  it('treats an unrecognised state as disconnected rather than guessing', () => {
    expect(sessionTypeLabel('shadow', false)).toBe('Déconnectée (console)');
  });
});

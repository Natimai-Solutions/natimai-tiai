// The shared labels in English, and the French they still give by default
// (plan `dev/plan-console-bilingue.md`, I6). Every label is worded when it is
// asked for: a change of language reaches the next call.
import { afterEach, describe, expect, it, vi } from 'vitest';
import { setLocale } from 'src/i18n';
import {
  EMAIL_PREFERENCE_OPTIONS,
  antivirusLabel,
  antivirusStatusLabel,
  boolLabel,
  chassisLabel,
  cpuLabel,
  emailPreferenceLabel,
  encryptionLabel,
  linkSpeedLabel,
  mediaTypeLabel,
  nicTypeLabel,
  onlineLabel,
  protectionBadgeLabel,
  protectionLabel,
  ramLabel,
  runningModeLabel,
  sessionLabel,
  sessionTypeLabel,
  sizeLabel,
  threatNameLabel,
  threatSeverityLabel,
  threatStatusLabel,
  timeAgoLabel,
  wuPendingLabel,
  wuSeverityLabel,
  wuSizeLabel,
  wuTypeLabel,
} from './format';

afterEach(() => {
  setLocale('fr');
  vi.useRealTimers();
});

describe('format in English', () => {
  it('says how long ago', () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-11-18T12:00:00Z'));
    setLocale('en');
    expect(timeAgoLabel('2026-11-18T11:59:30Z')).toBe('just now');
    expect(timeAgoLabel('2026-11-18T11:58:00Z')).toBe('2 min ago');
    expect(timeAgoLabel('2026-11-18T09:00:00Z')).toBe('3 h ago');
    expect(timeAgoLabel('2026-11-17T12:00:00Z')).toBe('1 day ago');
    expect(timeAgoLabel('2026-11-15T12:00:00Z')).toBe('3 days ago');
  });

  it('words presence, booleans and sessions', () => {
    setLocale('en');
    expect(onlineLabel(true)).toBe('Computer on');
    expect(onlineLabel(false)).toBe('Computer off or unreachable');
    expect(boolLabel(null)).toBe('Unknown');
    expect(boolLabel(true)).toBe('Yes');
    expect(boolLabel(false)).toBe('No');
    expect(sessionLabel(null, null)).toBe('Unknown');
    expect(sessionLabel(false, null)).toBe('No user');
    expect(sessionLabel(true, '')).toBe('User logged on');
    expect(sessionTypeLabel('active', true)).toBe('Active (Remote Desktop)');
    expect(sessionTypeLabel('disconnected', false)).toBe('Disconnected (console)');
  });

  it('words the antivirus and the protection', () => {
    setLocale('en');
    expect(antivirusLabel(null)).toBe('Not reported');
    expect(antivirusLabel('')).toBe('None');
    expect(antivirusStatusLabel('ESET', true, false)).toBe(
      'ESET — protection on, signatures outdated',
    );
    expect(antivirusStatusLabel('ESET', null, true)).toBe(
      'ESET — protection state unknown, signatures up to date',
    );
    expect(antivirusStatusLabel(null, null, null)).toContain('Security Center never reported');
    expect(antivirusStatusLabel('', null, null)).toBe('No antivirus registered');
    expect(protectionLabel(null)).toBe('State unknown');
    expect(protectionLabel(true)).toBe('Up to date');
    expect(protectionLabel(false)).toBe('Not up to date');
    expect(protectionBadgeLabel('Defender', false)).toBe('Defender · not up to date');
    expect(protectionBadgeLabel('Defender', null)).toBe('Defender · state unknown');
    expect(runningModeLabel('Passive')).toBe('Passive (another antivirus protects the computer)');
    expect(runningModeLabel('EDR Block Mode')).toBe('EDR in block mode');
  });

  it('words Windows Update and threats', () => {
    setLocale('en');
    expect(wuPendingLabel(null)).toBe('Unknown');
    expect(wuPendingLabel(0)).toBe('Up to date');
    expect(wuPendingLabel(3)).toBe('3');
    expect(wuSeverityLabel('critical')).toBe('Critical');
    expect(wuSeverityLabel('moderate')).toBe('Moderate');
    expect(wuSeverityLabel('unrated')).toBe('unrated');
    expect(wuTypeLabel('driver')).toBe('Driver');
    expect(wuSizeLabel(1234)).toBe('≤ 1,234 MiB');
    expect(threatSeverityLabel('high')).toBe('High');
    expect(threatSeverityLabel('moderate')).toBe('Medium');
    expect(threatStatusLabel('quarantine_failed')).toBe('Quarantine failed');
    expect(threatStatusLabel('allow_failed')).toBe('Allow failed');
    expect(threatStatusLabel('new_status')).toBe('new_status');
    expect(threatNameLabel(' ', null)).toBe('(no name)');
  });

  it('words the inventory', () => {
    setLocale('en');
    expect(sizeLabel(512)).toBe('512 MiB');
    expect(sizeLabel(3584)).toBe('3.5 GiB');
    expect(sizeLabel(2 * 1024 * 1024)).toBe('2.0 TiB');
    expect(mediaTypeLabel('HDD')).toBe('Hard disk');
    expect(mediaTypeLabel('Tape')).toBe('Tape');
    expect(chassisLabel('desktop')).toBe('Desktop');
    expect(chassisLabel('all-in-one')).toBe('All-in-one');
    expect(encryptionLabel(null)).toBe('Not reported');
    expect(encryptionLabel('FullyDecrypted')).toBe('Not encrypted');
    expect(nicTypeLabel('other')).toBe('Other');
    expect(linkSpeedLabel(2500)).toBe('2.5 Gb/s');
    expect(cpuLabel('i7', 8, 16, 2)).toBe('i7 (2 processors, 8 cores, 16 threads)');
    expect(ramLabel(32768, 2, 4)).toBe('32 GiB (2 of 4 slots used)');
  });

  it('words the e-mail cadences, the shared list included', () => {
    setLocale('en');
    expect(emailPreferenceLabel('none')).toBe('No email');
    expect(EMAIL_PREFERENCE_OPTIONS[3]!.label).toBe('Daily summary, every day');
    expect(EMAIL_PREFERENCE_OPTIONS[0]!.hint).toContain('Nothing will be sent to you');
  });
});

describe('format follows a change of language', () => {
  it('gives French, then English, then French again', () => {
    expect(onlineLabel(true)).toBe('Poste allumé');
    expect(EMAIL_PREFERENCE_OPTIONS[0]!.label).toBe('Aucun e-mail');
    expect(ramLabel(32768, 2, 4)).toBe('32 Gio (2 barrette(s) sur 4)');
    setLocale('en');
    expect(onlineLabel(true)).toBe('Computer on');
    expect(EMAIL_PREFERENCE_OPTIONS[0]!.label).toBe('No email');
    setLocale('fr');
    expect(onlineLabel(true)).toBe('Poste allumé');
    expect(threatStatusLabel('allow_failed')).toBe("Échec d'autorisation");
    expect(sessionTypeLabel('active', true)).toBe('Active (Bureau à distance)');
  });
});

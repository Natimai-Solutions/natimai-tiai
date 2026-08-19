import { describe, expect, it } from 'vitest';
import {
  antivirusColor,
  antivirusLabel,
  antivirusStatusLabel,
  boolLabel,
  formatDateTime,
  onlineColor,
  onlineIcon,
  onlineLabel,
  protectionColor,
  protectionLabel,
  runningModeLabel,
  sessionColor,
  sessionLabel,
  sessionTypeLabel,
  timeAgoLabel,
  threatSeverityColor,
  threatSeverityLabel,
  threatStatusColor,
  threatStatusLabel,
  wuPendingColor,
  wuPendingLabel,
  wuSeverityColor,
  wuSeverityLabel,
  wuSizeLabel,
  wuTypeLabel,
} from './format';

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

describe('timeAgoLabel', () => {
  /** An ISO timestamp `seconds` in the past, relative to the test's own clock. */
  const ago = (seconds: number) => new Date(Date.now() - seconds * 1000).toISOString();

  it('renders a dash for a missing or unparseable timestamp', () => {
    expect(timeAgoLabel(null)).toBe('—');
    expect(timeAgoLabel(undefined)).toBe('—');
    expect(timeAgoLabel('')).toBe('—');
    expect(timeAgoLabel('pas une date')).toBe('—');
  });

  it('scales the unit to the age', () => {
    expect(timeAgoLabel(ago(5))).toBe("à l'instant");
    expect(timeAgoLabel(ago(59))).toBe("à l'instant");
    expect(timeAgoLabel(ago(60))).toBe('il y a 1 min');
    expect(timeAgoLabel(ago(45 * 60))).toBe('il y a 45 min');
    expect(timeAgoLabel(ago(3 * 3600))).toBe('il y a 3 h');
    expect(timeAgoLabel(ago(5 * 86400))).toBe('il y a 5 j');
  });

  it('reads a clock skewed into the future as just now, not as a negative age', () => {
    expect(timeAgoLabel(ago(-30))).toBe("à l'instant");
  });
});

describe('onlineIcon / onlineColor / onlineLabel', () => {
  it('encodes presence in shape as well as colour', () => {
    expect(onlineIcon(true)).toBe('circle');
    expect(onlineIcon(false)).toBe('radio_button_unchecked');
    expect(onlineColor(true)).toBe('positive');
    expect(onlineColor(false)).toBe('grey-5');
  });

  it('speaks of the machine, not of a logged-on user', () => {
    // The session column owns "utilisateur connecté"; a poste sitting at its
    // login screen is on with nobody on it, and both must stay readable.
    expect(onlineLabel(true)).toBe('Poste allumé');
    // Names both causes the server cannot tell apart.
    expect(onlineLabel(false)).toBe('Poste éteint ou injoignable');
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

describe('antivirusLabel', () => {
  it('distinguishes "never reported" from "none installed"', () => {
    // "Non relevé", not "Inconnu": the difference an administrator reads next to
    // a live Defender column.
    expect(antivirusLabel(null)).toBe('Non relevé');
    expect(antivirusLabel(undefined)).toBe('Non relevé');
    // The registry was read and holds nothing: a finding, not a missing measure.
    expect(antivirusLabel('')).toBe('Aucun');
  });

  it('shows the product name as reported', () => {
    expect(antivirusLabel('ESET Endpoint Security')).toBe('ESET Endpoint Security');
  });
});

describe('antivirusColor', () => {
  it('greys out what it does not know', () => {
    expect(antivirusColor(null, null)).toBe('grey-6');
    expect(antivirusColor(undefined, true)).toBe('grey-6');
    // A product is installed but its bitfield was unreadable — no claim made.
    expect(antivirusColor('Trellix Endpoint Security', null)).toBe('grey-7');
  });

  it('flags no antivirus and stopped protection', () => {
    expect(antivirusColor('', null)).toBe('negative');
    expect(antivirusColor('ESET Endpoint Security', false)).toBe('negative');
  });

  it('marks a running product as healthy', () => {
    expect(antivirusColor('ESET Endpoint Security', true)).toBe('positive');
  });
});

describe('antivirusStatusLabel', () => {
  it('names the two absent cases apart', () => {
    expect(antivirusStatusLabel(null, null, null)).toBe(
      'Security Center jamais relevé (agent antérieur, ou hôte sans Security Center)',
    );
    expect(antivirusStatusLabel('', null, null)).toBe('Aucun antivirus enregistré');
  });

  it('combines the product, its protection and its signature freshness', () => {
    expect(antivirusStatusLabel('ESET Endpoint Security', true, true)).toBe(
      'ESET Endpoint Security — protection active, signatures à jour',
    );
    expect(antivirusStatusLabel('Avast Business Antivirus', true, false)).toBe(
      'Avast Business Antivirus — protection active, signatures périmées',
    );
    expect(antivirusStatusLabel('Sophos Endpoint', false, true)).toBe(
      'Sophos Endpoint — protection désactivée, signatures à jour',
    );
  });

  it('says nothing about a freshness bit the product never filled in', () => {
    expect(antivirusStatusLabel('Kaspersky Endpoint Security', true, null)).toBe(
      'Kaspersky Endpoint Security — protection active',
    );
    expect(antivirusStatusLabel('Kaspersky Endpoint Security', null, null)).toBe(
      'Kaspersky Endpoint Security — protection à l’état inconnu',
    );
  });
});

describe('protectionLabel', () => {
  it('keeps unknown apart from measured-and-behind', () => {
    expect(protectionLabel(null)).toBe('État inconnu');
    expect(protectionLabel(undefined)).toBe('État inconnu');
    expect(protectionLabel(true)).toBe('À jour');
    expect(protectionLabel(false)).toBe('Non à jour');
  });
});

describe('protectionColor', () => {
  it('greys unknown, colours the two measured states', () => {
    expect(protectionColor(null)).toBe('grey-6');
    expect(protectionColor(undefined)).toBe('grey-6');
    expect(protectionColor(true)).toBe('positive');
    expect(protectionColor(false)).toBe('negative');
  });
});

describe('runningModeLabel', () => {
  it('renders a dash when Defender reported no mode', () => {
    expect(runningModeLabel(null)).toBe('—');
    expect(runningModeLabel(undefined)).toBe('—');
    expect(runningModeLabel('')).toBe('—');
  });

  it('spells out why the Defender flags read off', () => {
    expect(runningModeLabel('Passive')).toBe('Passif (un antivirus tiers protège le poste)');
    expect(runningModeLabel('SxS Passive Mode')).toBe(
      'Passif (un antivirus tiers protège le poste)',
    );
    expect(runningModeLabel('Normal')).toBe('Normal');
    expect(runningModeLabel('EDR Block Mode')).toBe('EDR en mode blocage');
  });

  it('surfaces a mode it does not know rather than hiding it', () => {
    expect(runningModeLabel('Some Future Mode')).toBe('Some Future Mode');
  });
});

describe('wuPendingLabel', () => {
  // The distinction the whole column rests on: a machine that has never
  // reported a Windows Update search is not a machine with nothing to install.
  it('distinguishes never-reported from up-to-date', () => {
    expect(wuPendingLabel(null)).toBe('Inconnu');
    expect(wuPendingLabel(undefined)).toBe('Inconnu');
    expect(wuPendingLabel(0)).toBe('À jour');
    expect(wuPendingLabel(12)).toBe('12');
  });

  it('colours unknown apart from both other states', () => {
    expect(wuPendingColor(null)).toBe('grey-6');
    expect(wuPendingColor(0)).toBe('positive');
    expect(wuPendingColor(3)).toBe('warning');
  });
});

describe('wuSeverityLabel', () => {
  it('translates the MSRC ratings', () => {
    expect(wuSeverityLabel('critical')).toBe('Critique');
    expect(wuSeverityLabel('important')).toBe('Importante');
    expect(wuSeverityLabel('moderate')).toBe('Modérée');
    expect(wuSeverityLabel('low')).toBe('Faible');
  });

  it('shows a dash for the many updates carrying no rating', () => {
    expect(wuSeverityLabel(null)).toBe('—');
    expect(wuSeverityLabel('')).toBe('—');
  });

  it('surfaces a rating it does not know rather than swallowing it', () => {
    expect(wuSeverityLabel('unspecified')).toBe('unspecified');
  });

  it('only colours what Microsoft actually rates', () => {
    expect(wuSeverityColor('critical')).toBe('negative');
    expect(wuSeverityColor('important')).toBe('warning');
    // No invented ranking for an unrated update.
    expect(wuSeverityColor(null)).toBe('grey-5');
    expect(wuSeverityColor('unspecified')).toBe('grey-5');
  });
});

describe('wuTypeLabel', () => {
  it('names the distinction the two install commands hinge on', () => {
    expect(wuTypeLabel('software')).toBe('Logicielle');
    expect(wuTypeLabel('driver')).toBe('Pilote');
  });

  it('falls back to the raw value', () => {
    expect(wuTypeLabel('firmware')).toBe('firmware');
    expect(wuTypeLabel(null)).toBe('—');
  });
});

describe('wuSizeLabel', () => {
  it('renders a dash when Windows Update reported no size', () => {
    expect(wuSizeLabel(null)).toBe('—');
    expect(wuSizeLabel(undefined)).toBe('—');
  });

  it('formats the size in the French locale', () => {
    expect(wuSizeLabel(620.5)).toBe(`${(620.5).toLocaleString('fr-FR')} Mio`);
    // Zero is a real reading here, unlike null: the server already turned
    // "WUA reported nothing" into null upstream.
    expect(wuSizeLabel(0)).toBe('0 Mio');
  });
});

describe('threatSeverityLabel', () => {
  it('translates the ratings the agent emits', () => {
    expect(threatSeverityLabel('low')).toBe('Faible');
    expect(threatSeverityLabel('medium')).toBe('Moyenne');
    // Microsoft's own spelling of the same rating.
    expect(threatSeverityLabel('moderate')).toBe('Moyenne');
    expect(threatSeverityLabel('high')).toBe('Élevée');
    expect(threatSeverityLabel('severe')).toBe('Grave');
    expect(threatSeverityLabel('unknown')).toBe('Inconnue');
  });

  it('surfaces an unmapped rating rather than swallowing it', () => {
    expect(threatSeverityLabel('catastrophic')).toBe('catastrophic');
    expect(threatSeverityLabel(null)).toBe('—');
  });
});

describe('threatSeverityColor', () => {
  it('ranks only the ratings Defender publishes', () => {
    expect(threatSeverityColor('severe')).toBe('negative');
    expect(threatSeverityColor('high')).toBe('warning');
    expect(threatSeverityColor('low')).toBe('grey-7');
    expect(threatSeverityColor('catastrophic')).toBe('grey-5');
    expect(threatSeverityColor(null)).toBe('grey-5');
  });
});

describe('threatStatusLabel', () => {
  it('translates the statuses the agent emits, failures included', () => {
    expect(threatStatusLabel('active')).toBe('Active');
    expect(threatStatusLabel('quarantined')).toBe('En quarantaine');
    expect(threatStatusLabel('removed')).toBe('Supprimée');
    expect(threatStatusLabel('remove_failed')).toBe('Échec de suppression');
    expect(threatStatusLabel('unknown')).toBe('Inconnu');
  });

  it('surfaces an unmapped status rather than swallowing it', () => {
    expect(threatStatusLabel('detected_offline')).toBe('detected_offline');
    expect(threatStatusLabel(null)).toBe('—');
  });
});

describe('threatStatusColor', () => {
  it('flags the statuses needing a human', () => {
    expect(threatStatusColor('active')).toBe('negative');
    // A remediation Defender failed to carry out is as bad as an untreated one.
    expect(threatStatusColor('quarantine_failed')).toBe('negative');
    expect(threatStatusColor('quarantined')).toBe('positive');
    expect(threatStatusColor('allowed')).toBe('warning');
    expect(threatStatusColor(null)).toBe('grey-5');
  });
});

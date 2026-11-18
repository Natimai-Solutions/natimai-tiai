import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join, relative } from 'node:path';
import { describe, expect, it } from 'vitest';
import { scanSource } from './scan';

/**
 * No interface text in French outside the catalogues (plan
 * `dev/plan-console-bilingue.md`, I6): an English reader would read it.
 *
 * `PENDING` lists the files not translated yet, one block per batch of the
 * work; a batch removes its block once its files are clean. A file not
 * listed must stay clean. English is offered (`ENGLISH_AVAILABLE`) once the
 * list is empty.
 */
const PENDING = new Set<string>([
  // --- Lot C1 : Paramètres
  'pages/SettingsPage.vue',
  'utils/emailSettings.ts',
  'utils/numberField.ts',
  'utils/settingsSchedule.ts',

  // --- Lot D : salles, maintenance, vérifications, tâches
  'components/check/CheckCloseDialog.vue',
  'components/check/CheckRequestDialog.vue',
  'components/machine/MachineHistoryCard.vue',
  'components/machine/MachineMaintenanceCard.vue',
  'components/maintenance/MaintenanceSessionDialog.vue',
  'components/maintenance/MaintenanceSessionViewDialog.vue',
  'components/maintenance/MaintenanceSettingsDialog.vue',
  'components/room/BuildingFormDialog.vue',
  'components/room/RoomFormDialog.vue',
  'pages/RoomDetailPage.vue',
  'pages/RoomsPage.vue',
  'pages/TasksPage.vue',
  'services/checks.ts',
  'services/interventions.ts',
  'services/maintenance.ts',
  'services/rooms.ts',

  // --- Lot F : commandes
  'components/machine/CommandOutputDialog.vue',
  'components/machine/MachineCommandsCard.vue',
  'services/commands.ts',

  // --- Lot G : exports
  'components/machine/MachineExportDialog.vue',
]);

const SRC = new URL('..', import.meta.url).pathname;

function sources(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return sources(path);
    return /\.(vue|ts)$/.test(name) && !name.endsWith('.spec.ts') ? [path] : [];
  });
}

// The catalogues hold the French on purpose; the test tooling is not shown.
const SKIPPED = ['i18n/', 'test/'];

describe('no French text outside the catalogues', () => {
  const files = sources(SRC)
    .map((path) => relative(SRC, path))
    .filter((file) => !SKIPPED.some((dir) => file.startsWith(dir)));

  it.each(files.filter((f) => !PENDING.has(f)))('%s', (file) => {
    const found = scanSource(readFileSync(join(SRC, file), 'utf-8'), file);
    expect(found.map((f) => `${f.line}: ${f.text}`)).toEqual([]);
  });

  it('lists no pending file that is clean or gone', () => {
    const stale = [...PENDING].filter(
      (file) =>
        !files.includes(file) ||
        scanSource(readFileSync(join(SRC, file), 'utf-8'), file).length === 0,
    );
    expect(stale).toEqual([]);
  });
});

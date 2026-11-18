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
  // --- Lot B : liste des postes
  'components/machine/MachineColumnsDialog.vue',
  'components/machines-list/MachinePlaceDialog.vue',
  'components/machines-list/MachinesBulkBar.vue',
  'components/machines-list/MachinesFilterPanel.vue',
  'components/machines-list/MachinesFiltersBar.vue',
  'components/machines-list/MachinesTable.vue',
  'components/machines-list/MachinesToolbar.vue',
  'composables/useMachineBulkActions.ts',
  'composables/useMachineColumnLayout.ts',
  'composables/useMachineFleetOptions.ts',
  'pages/MachinesPage.vue',
  'services/machines.ts',
  'utils/machineListFilters.ts',
  'utils/machineListTable.ts',
  'utils/machineQuery.ts',
  'utils/usageFilter.ts',

  // --- Lot C1 : Paramètres
  'pages/SettingsPage.vue',
  'utils/emailSettings.ts',
  'utils/numberField.ts',
  'utils/settingsSchedule.ts',

  // --- Lot C2 : comptes, groupes, audit
  'components/audit/AuditDetailsDialog.vue',
  'components/audit/AuditFiltersBar.vue',
  'composables/usePasswordPolicy.ts',
  'pages/AccountPage.vue',
  'pages/AuditPage.vue',
  'pages/GroupsPage.vue',
  'pages/UsersPage.vue',
  'utils/auditLabels.ts',
  'utils/authority.ts',
  'utils/permissions.ts',
  'utils/userAgent.ts',

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

  // --- Lot E1 : coquille, connexion, tableau de bord, logiciels, mise en forme
  'components/CardLoadError.vue',
  'components/LoadErrorBanner.vue',
  'layouts/MainLayout.vue',
  'pages/DashboardPage.vue',
  'pages/ErrorNotFound.vue',
  'pages/ForgotPasswordPage.vue',
  'pages/LoginPage.vue',
  'pages/NoAccessPage.vue',
  'pages/ResetPasswordPage.vue',
  'pages/SoftwarePage.vue',
  'router/routes.ts',
  'utils/format.ts',
  'utils/staleChunks.ts',

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

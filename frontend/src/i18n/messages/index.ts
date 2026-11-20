import account from './account';
import alerts from './alerts';
import assets from './assets';
import audit from './audit';
import auth from './auth';
import checks from './checks';
import commands from './commands';
import common from './common';
import compliance from './compliance';
import dashboard from './dashboard';
import errors from './errors';
import exports from './exports';
import format from './format';
import groups from './groups';
import interventions from './interventions';
import layout from './layout';
import machine from './machine';
import machines from './machines';
import maintenance from './maintenance';
import packagePages from './packagePages';
import packages from './packages';
import permissions from './permissions';
import reports from './reports';
import rooms from './rooms';
import schedules from './schedules';
import settings from './settings';
import settingsEnv from './settingsEnv';
import software from './software';
import tasks from './tasks';
import users from './users';

/**
 * Every catalogue of the console, one domain per file, each with its French
 * and its English side by side (plan `dev/plan-console-bilingue.md`, §4.1).
 * A domain's texts are `t('<domain>.<key>')`. The API's error codes have
 * their own table (`errorCodes.ts`).
 */
export const fr = {
  alerts: alerts.fr,
  assets: assets.fr,
  schedules: schedules.fr,
  reports: reports.fr,
  common: common.fr,
  compliance: compliance.fr,
  errors: errors.fr,
  packages: packages.fr,
  machine: machine.fr,
  machines: machines.fr,
  settings: settings.fr,
  settingsEnv: settingsEnv.fr,
  users: users.fr,
  groups: groups.fr,
  account: account.fr,
  audit: audit.fr,
  permissions: permissions.fr,
  rooms: rooms.fr,
  maintenance: maintenance.fr,
  checks: checks.fr,
  tasks: tasks.fr,
  interventions: interventions.fr,
  layout: layout.fr,
  auth: auth.fr,
  dashboard: dashboard.fr,
  software: software.fr,
  format: format.fr,
  packagePages: packagePages.fr,
  commands: commands.fr,
  exports: exports.fr,
};

export const en = {
  alerts: alerts.en,
  assets: assets.en,
  schedules: schedules.en,
  reports: reports.en,
  common: common.en,
  compliance: compliance.en,
  errors: errors.en,
  packages: packages.en,
  machine: machine.en,
  machines: machines.en,
  settings: settings.en,
  settingsEnv: settingsEnv.en,
  users: users.en,
  groups: groups.en,
  account: account.en,
  audit: audit.en,
  permissions: permissions.en,
  rooms: rooms.en,
  maintenance: maintenance.en,
  checks: checks.en,
  tasks: tasks.en,
  interventions: interventions.en,
  layout: layout.en,
  auth: auth.en,
  dashboard: dashboard.en,
  software: software.en,
  format: format.en,
  packagePages: packagePages.en,
  commands: commands.en,
  exports: exports.en,
};

export type MessageSchema = typeof fr;

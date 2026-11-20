<template>
  <q-page padding>
    <h1 class="text-h5 q-mb-md">{{ t('settings.title') }}</h1>

    <!-- The settings could not be read: said once, with « Réessayer », rather
         than a toast over cards with nothing in them (item 2). -->
    <LoadErrorBanner
      v-if="loadError && !settings"
      :error="loadError"
      :loading="reloading"
      @retry="retryLoad"
    />

    <q-card flat bordered style="max-width: 640px" class="q-mb-md">
      <q-card-section class="text-subtitle1">
        {{ t('settings.maintenance.title') }}
        <div class="text-caption text-muted">
          {{ t('settings.maintenance.caption') }}
        </div>
      </q-card-section>
      <q-separator />
      <q-card-section v-if="settings" class="q-gutter-md">
        <q-input
          v-model.number="form.cycle"
          :error="fieldErrors.cycle !== null"
          :error-message="fieldErrors.cycle ?? ''"
          type="number"
          min="0"
          max="3650"
          :suffix="t('settings.units.days')"
          :label="t('settings.maintenance.cycle')"
          outlined
          dense
          :hint="t('settings.maintenance.cycleHint', { days: settings.env_default_cycle_days })"
          :disable="!canWrite"
        />
        <q-select
          v-model="form.ownerId"
          :options="ownerOptions"
          emit-value
          map-options
          :label="t('settings.maintenance.owner')"
          outlined
          dense
          clearable
          :hint="t('settings.maintenance.ownerHint')"
          :disable="!canWrite"
        />
        <q-input
          v-model.number="form.dueSoon"
          :error="fieldErrors.dueSoon !== null"
          :error-message="fieldErrors.dueSoon ?? ''"
          type="number"
          min="0"
          max="365"
          :suffix="t('settings.units.days')"
          :label="t('settings.maintenance.dueSoon')"
          outlined
          dense
          :hint="t('settings.maintenance.dueSoonHint', { days: settings.env_due_soon_days })"
          :disable="!canWrite"
        />
      </q-card-section>
      <q-card-actions v-if="canWrite && settings" align="right" class="q-px-md q-pb-md">
        <q-btn
          color="primary"
          :label="t('settings.save')"
          :loading="saving"
          :disable="maintenanceInvalid"
          @click="save"
        />
      </q-card-actions>
    </q-card>

    <!-- The usage statistics' window and thresholds: what « peu utilisé » and
         « toujours allumé » mean on this parc. Saved on its own, so a refused
         threshold never holds the maintenance settings back. -->
    <q-card flat bordered style="max-width: 640px" class="q-mb-md">
      <q-card-section class="text-subtitle1">
        {{ t('settings.usage.title') }}
        <div class="text-caption text-muted">
          {{ t('settings.usage.caption') }}
        </div>
      </q-card-section>
      <q-separator />
      <q-card-section v-if="settings" class="q-gutter-md">
        <q-input
          v-model.number="usageForm.windowDays"
          type="number"
          min="1"
          max="90"
          :suffix="t('settings.units.days')"
          :label="t('settings.usage.windowDays')"
          outlined
          dense
          :hint="t('settings.usage.windowHint', { days: settings.env_usage_window_days })"
          :disable="!canWrite"
        />
        <q-input
          v-model.number="usageForm.lowHours"
          type="number"
          min="0"
          :suffix="t('settings.units.hours')"
          :label="t('settings.usage.lowHours')"
          outlined
          dense
          :hint="t('settings.usage.lowHint', { hours: settings.env_usage_low_hours })"
          :disable="!canWrite"
        />
        <q-input
          v-model.number="usageForm.highHours"
          type="number"
          min="1"
          :suffix="t('settings.units.hours')"
          :label="t('settings.usage.highHours')"
          outlined
          dense
          :hint="t('settings.usage.highHint', { hours: settings.env_usage_high_hours })"
          :disable="!canWrite"
        />
        <div v-if="usageError" class="text-negative text-caption">{{ usageError }}</div>
      </q-card-section>
      <q-card-actions v-if="canWrite && settings" align="right" class="q-px-md q-pb-md">
        <q-btn
          color="primary"
          :label="t('settings.save')"
          :loading="savingUsage"
          :disable="usageError !== null"
          @click="saveUsage"
        />
      </q-card-actions>
    </q-card>

    <!-- Alerts: which rules of the closed catalogue run, their thresholds,
         the « logiciels interdits » list and the rules that open a
         verification by themselves. Saved on its own. -->
    <q-card flat bordered style="max-width: 640px" class="q-mb-md">
      <q-card-section class="text-subtitle1">
        {{ t('settings.alerts.title') }}
        <div class="text-caption text-muted">{{ t('settings.alerts.caption') }}</div>
      </q-card-section>
      <q-separator />
      <q-card-section v-if="settings" class="q-gutter-md">
        <div>
          <div class="text-caption text-muted q-mb-xs">{{ t('settings.alerts.rules') }}</div>
          <div v-for="rule in settings.alert_rules ?? []" :key="rule" class="row items-center">
            <q-toggle
              v-model="alertForm.enabled"
              :val="rule"
              :label="alertRuleLabel(rule)"
              :disable="!canWrite"
              class="col"
            />
            <q-checkbox
              v-model="alertForm.autoCheck"
              :val="rule"
              dense
              :label="t('settings.alerts.autoCheck')"
              :disable="!canWrite || !alertForm.enabled.includes(rule)"
            />
          </div>
          <div class="text-caption text-muted q-mt-xs">
            {{ t('settings.alerts.autoCheckHint') }}
          </div>
        </div>
        <q-input
          v-model.number="alertForm.rebootDays"
          type="number"
          min="1"
          max="365"
          :suffix="t('settings.units.days')"
          :label="t('settings.alerts.rebootDays')"
          outlined
          dense
          :error="alertRebootError !== null"
          :error-message="alertRebootError ?? undefined"
          :hint="t('settings.alerts.rebootHint', { days: settings.env_alert_reboot_pending_days })"
          :disable="!canWrite"
        />
        <q-select
          v-model="alertForm.unencryptedScope"
          :options="unencryptedOptions"
          emit-value
          map-options
          :label="t('settings.alerts.unencryptedScope')"
          outlined
          dense
          :disable="!canWrite"
        />
        <q-select
          v-model="alertForm.forbidden"
          :label="t('settings.alerts.forbidden')"
          :hint="t('settings.alerts.forbiddenHint')"
          outlined
          dense
          multiple
          use-chips
          use-input
          hide-dropdown-icon
          new-value-mode="add-unique"
          input-debounce="0"
          :disable="!canWrite"
        />
      </q-card-section>
      <q-card-actions v-if="canWrite && settings" align="right" class="q-px-md q-pb-md">
        <q-btn
          color="primary"
          :label="t('settings.save')"
          :loading="savingAlerts"
          :disable="alertRebootError !== null"
          @click="saveAlerts"
        />
      </q-card-actions>
    </q-card>

    <!-- Parc thresholds: what makes the console call a poste « périmé »,
         « inactif », short of disk, due for renewal or behind on its agent,
         and how long a queued command waits for it. The environment gives the
         initial value; the value saved here wins, without a restart. -->
    <q-card flat bordered style="max-width: 640px" class="q-mb-md">
      <q-card-section class="text-subtitle1">
        {{ t('settings.fleet.title') }}
        <div class="text-caption text-muted">
          {{ t('settings.fleet.caption') }}
        </div>
      </q-card-section>
      <q-separator />
      <q-card-section v-if="settings" class="q-gutter-md">
        <q-input
          v-model.number="fleetForm.signatureMaxAgeDays"
          :error="fieldErrors.signatureMaxAgeDays !== null"
          :error-message="fieldErrors.signatureMaxAgeDays ?? ''"
          type="number"
          min="0"
          max="365"
          :suffix="t('settings.units.days')"
          :label="t('settings.fleet.signatureMaxAge')"
          outlined
          dense
          :hint="
            t('settings.fleet.signatureMaxAgeHint', { days: settings.env_signature_max_age_days })
          "
          :disable="!canWrite"
        />
        <q-input
          v-model.number="fleetForm.inactiveAfterDays"
          :error="fieldErrors.inactiveAfterDays !== null"
          :error-message="fieldErrors.inactiveAfterDays ?? ''"
          type="number"
          min="1"
          max="3650"
          :suffix="t('settings.units.days')"
          :label="t('settings.fleet.inactiveAfter')"
          outlined
          dense
          :hint="t('settings.fleet.inactiveAfterHint', { days: settings.env_inactive_after_days })"
          :disable="!canWrite"
        />
        <q-input
          v-model.number="fleetForm.lowDiskFreePercent"
          :error="fieldErrors.lowDiskFreePercent !== null"
          :error-message="fieldErrors.lowDiskFreePercent ?? ''"
          type="number"
          min="1"
          max="99"
          :suffix="t('settings.units.percentFree')"
          :label="t('settings.fleet.lowDisk')"
          outlined
          dense
          :hint="t('settings.fleet.lowDiskHint', { percent: settings.env_low_disk_free_percent })"
          :disable="!canWrite"
        />
        <q-input
          v-model.number="fleetForm.hardwareAgingYears"
          :error="fieldErrors.hardwareAgingYears !== null"
          :error-message="fieldErrors.hardwareAgingYears ?? ''"
          type="number"
          min="1"
          max="30"
          :suffix="t('settings.units.years')"
          :label="t('settings.fleet.hardwareAging')"
          outlined
          dense
          :hint="
            t('settings.fleet.hardwareAgingHint', { years: settings.env_hardware_aging_years })
          "
          :disable="!canWrite"
        />
        <q-input
          v-model="fleetForm.agentExpectedVersion"
          :label="t('settings.fleet.agentVersion')"
          :placeholder="t('settings.fleet.agentVersionPlaceholder')"
          outlined
          dense
          clearable
          :error="!agentVersionValid"
          :error-message="t('settings.fleet.agentVersionError')"
          :hint="
            t('settings.fleet.agentVersionHint', {
              version: settings.env_agent_expected_version ?? t('settings.fleet.automatic'),
            })
          "
          :disable="!canWrite"
        />
        <q-input
          v-model.number="fleetForm.commandDefaultTtlMinutes"
          :error="fieldErrors.commandDefaultTtlMinutes !== null"
          :error-message="fieldErrors.commandDefaultTtlMinutes ?? ''"
          type="number"
          min="1"
          :max="60 * 24 * 30"
          :suffix="t('settings.units.minutes')"
          :label="t('settings.fleet.commandTtl')"
          outlined
          dense
          :hint="
            t('settings.fleet.commandTtlHint', {
              minutes: settings.env_command_default_ttl_minutes,
            })
          "
          :disable="!canWrite"
        />
      </q-card-section>
      <q-card-actions v-if="canWrite && settings" align="right" class="q-px-md q-pb-md">
        <q-btn
          color="primary"
          :label="t('settings.save')"
          :loading="savingFleet"
          :disable="!agentVersionValid || fleetInvalid"
          @click="saveFleet"
        />
      </q-card-actions>
    </q-card>

    <!-- The worker's mails. The server counts in UTC; the hints say when the
         mail lands on the reader's own clock, weekday shift included. -->
    <q-card flat bordered style="max-width: 640px" class="q-mb-md">
      <q-card-section class="text-subtitle1">
        {{ t('settings.schedule.title') }}
        <div class="text-caption text-muted">
          {{ t('settings.schedule.caption') }}
        </div>
      </q-card-section>
      <q-separator />
      <q-card-section v-if="settings" class="q-gutter-md">
        <q-select
          v-model="scheduleForm.digestHourUtc"
          :options="hourOptions"
          emit-value
          map-options
          :label="t('settings.schedule.digestHour')"
          outlined
          dense
          :hint="
            t('settings.schedule.digestHint', {
              when: digestHint,
              hour: settings.env_digest_hour_utc,
            })
          "
          :disable="!canWrite"
        />
        <q-select
          v-model="scheduleForm.reminderWeekday"
          :options="weekdayOptions"
          emit-value
          map-options
          :label="t('settings.schedule.reminderDay')"
          outlined
          dense
          :hint="
            t('settings.schedule.reminderHint', {
              when: reminderHint,
              day: weekdayName(settings.env_maintenance_reminder_weekday),
            })
          "
          :disable="!canWrite"
        />
      </q-card-section>
      <q-card-actions v-if="canWrite && settings" align="right" class="q-px-md q-pb-md">
        <q-btn
          color="primary"
          :label="t('settings.save')"
          :loading="savingSchedule"
          @click="saveSchedule"
        />
      </q-card-actions>
    </q-card>

    <!-- How mail leaves: provider, sender, account. Saved on its own, and
         testable before it is saved — the test send carries the unsaved
         values. Secrets are write-only: the page only ever learns whether one
         is stored, and whether it must be typed again. -->
    <q-card v-if="settings" flat bordered style="max-width: 640px" class="q-mb-md">
      <q-card-section class="text-subtitle1">
        {{ t('settings.email.title') }}
        <div class="text-caption text-muted">
          {{ t('settings.email.captionBefore') }}<code>deploy/.env</code
          >{{ t('settings.email.captionAfter') }}
        </div>
      </q-card-section>
      <q-separator />
      <q-card-section class="q-gutter-md">
        <div
          :class="status.ok ? 'text-ok' : 'text-negative'"
          class="row items-center no-wrap q-gutter-x-sm"
        >
          <q-icon :name="status.ok ? 'check_circle' : 'error_outline'" size="sm" />
          <span>{{ status.text }}</span>
        </div>
        <div>
          <div class="text-caption text-muted q-mb-xs">{{ t('settings.email.provider') }}</div>
          <q-btn-toggle
            v-model="emailForm.provider"
            :options="providerOptions"
            no-caps
            unelevated
            toggle-color="primary"
            :disable="!canWrite"
          />
          <div class="text-caption text-muted q-mt-xs">
            {{
              t('settings.email.serverValue', { value: providerLabel(settings.email.env.provider) })
            }}
          </div>
        </div>
        <q-input
          v-model="emailForm.fromEmail"
          :label="t('settings.email.fromEmail')"
          outlined
          dense
          :placeholder="settings.email.env.from_email ?? ''"
          :hint="
            t('settings.email.fromEmailHint', {
              value: settings.email.env.from_email ?? t('settings.email.notSetFeminine'),
            })
          "
          :disable="!canWrite"
        />
        <q-input
          v-model="emailForm.fromName"
          :label="t('settings.email.fromName')"
          outlined
          dense
          :placeholder="settings.email.env.from_name"
          :hint="t('settings.email.serverValue', { value: settings.email.env.from_name })"
          :disable="!canWrite"
        />

        <template v-if="emailForm.provider === 'smtp'">
          <q-input
            v-model="emailForm.smtpHost"
            :label="t('settings.email.smtpHost')"
            outlined
            dense
            :placeholder="settings.email.env.smtp_host ?? 'smtp.office365.com'"
            :hint="
              t('settings.email.smtpHostHint', {
                value: settings.email.env.smtp_host ?? t('settings.email.notSetFeminine'),
              })
            "
            :disable="!canWrite"
          />
          <div class="row q-col-gutter-md">
            <q-select
              v-model="emailForm.smtpSecurity"
              :options="SECURITY_OPTIONS"
              emit-value
              map-options
              :label="t('settings.email.security')"
              outlined
              dense
              class="col-12 col-sm-7"
              :hint="
                t('settings.email.serverValue', {
                  value: securityLabel(settings.email.env.smtp_security),
                })
              "
              :disable="!canWrite"
            />
            <q-input
              v-model.number="emailForm.smtpPort"
              type="number"
              min="1"
              max="65535"
              :label="t('settings.email.port')"
              outlined
              dense
              class="col-12 col-sm-5"
              :placeholder="String(settings.email.env.smtp_port)"
              :hint="t('settings.email.serverValue', { value: settings.email.env.smtp_port })"
              :disable="!canWrite"
            />
          </div>
          <q-input
            v-model="emailForm.smtpUser"
            :label="t('settings.email.user')"
            outlined
            dense
            autocomplete="off"
            :hint="
              t('settings.email.userHint', {
                value: settings.email.env.smtp_user_set
                  ? t('settings.email.userSet')
                  : t('settings.email.userNone'),
              })
            "
            :disable="!canWrite"
          />
          <q-input
            v-model="emailForm.smtpPassword"
            type="password"
            :label="t('settings.email.password')"
            outlined
            dense
            autocomplete="new-password"
            :placeholder="smtpPasswordKind === 'stored' ? '••••••••' : ''"
            :hint="secretHint(smtpPasswordKind, emailForm.clearSmtpPassword)"
            :disable="!canWrite"
          >
            <template #append>
              <q-badge
                :color="smtpPasswordState.color"
                :label="smtpPasswordState.label"
                class="q-mr-xs"
              />
              <q-btn
                v-if="
                  canWrite &&
                  (settings.email.smtp_password_set || settings.email.smtp_password_unreadable)
                "
                :aria-label="
                  emailForm.clearSmtpPassword
                    ? t('settings.email.keepPasswordAria')
                    : t('settings.email.clearPasswordAria')
                "
                flat
                dense
                round
                size="sm"
                :icon="emailForm.clearSmtpPassword ? 'undo' : 'delete_outline'"
                @click="emailForm.clearSmtpPassword = !emailForm.clearSmtpPassword"
              >
                <q-tooltip>{{
                  emailForm.clearSmtpPassword
                    ? t('settings.email.keepPassword')
                    : t('settings.email.clearPassword')
                }}</q-tooltip>
              </q-btn>
            </template>
          </q-input>
          <div class="row q-col-gutter-md items-center">
            <div class="col-12 col-sm-7">
              <q-toggle
                v-model="emailForm.smtpVerifyTls"
                :label="t('settings.email.verifyTls')"
                :disable="!canWrite"
              />
              <div class="text-caption text-muted">
                {{
                  t('settings.email.verifyTlsHint', {
                    value: settings.email.env.smtp_verify_tls
                      ? t('settings.email.yes')
                      : t('settings.email.no'),
                  })
                }}
              </div>
            </div>
            <q-input
              v-model.number="emailForm.smtpTimeout"
              type="number"
              min="1"
              max="120"
              suffix="s"
              :label="t('settings.email.timeout')"
              outlined
              dense
              class="col-12 col-sm-5"
              :placeholder="String(settings.email.env.smtp_timeout_seconds)"
              :hint="
                t('settings.email.serverValueSeconds', {
                  value: settings.email.env.smtp_timeout_seconds,
                })
              "
              :disable="!canWrite"
            />
          </div>
        </template>

        <template v-else>
          <q-input
            v-model="emailForm.mailgunDomain"
            :label="t('settings.email.mailgunDomain')"
            outlined
            dense
            :placeholder="
              settings.email.env.mailgun_domain ?? t('settings.email.mailgunDomainPlaceholder')
            "
            :hint="
              t('settings.email.serverValue', {
                value: settings.email.env.mailgun_domain ?? t('settings.email.notSetFeminine'),
              })
            "
            :disable="!canWrite"
          />
          <q-input
            v-model="emailForm.mailgunApiKey"
            type="password"
            :label="t('settings.email.mailgunApiKey')"
            outlined
            dense
            autocomplete="new-password"
            :placeholder="mailgunKeyKind === 'stored' ? '••••••••' : ''"
            :hint="secretHint(mailgunKeyKind, emailForm.clearMailgunApiKey)"
            :disable="!canWrite"
          >
            <template #append>
              <q-badge
                :color="mailgunKeyState.color"
                :label="mailgunKeyState.label"
                class="q-mr-xs"
              />
              <q-btn
                v-if="
                  canWrite &&
                  (settings.email.mailgun_api_key_set || settings.email.mailgun_api_key_unreadable)
                "
                :aria-label="
                  emailForm.clearMailgunApiKey
                    ? t('settings.email.keepKeyAria')
                    : t('settings.email.clearKeyAria')
                "
                flat
                dense
                round
                size="sm"
                :icon="emailForm.clearMailgunApiKey ? 'undo' : 'delete_outline'"
                @click="emailForm.clearMailgunApiKey = !emailForm.clearMailgunApiKey"
              >
                <q-tooltip>{{
                  emailForm.clearMailgunApiKey
                    ? t('settings.email.keepKey')
                    : t('settings.email.clearKey')
                }}</q-tooltip>
              </q-btn>
            </template>
          </q-input>
          <q-input
            v-model="emailForm.mailgunBaseUrl"
            :label="t('settings.email.mailgunBaseUrl')"
            outlined
            dense
            :placeholder="settings.email.env.mailgun_base_url"
            :hint="
              t('settings.email.mailgunBaseUrlHint', { value: settings.email.env.mailgun_base_url })
            "
            :disable="!canWrite"
          />
        </template>

        <div v-if="emailError" class="text-negative text-caption">{{ emailError }}</div>
      </q-card-section>

      <template v-if="canWrite">
        <q-separator />
        <q-card-section class="q-gutter-sm">
          <div class="row items-start q-col-gutter-sm">
            <q-input
              v-model="testTo"
              :label="t('settings.test.recipient')"
              outlined
              dense
              class="col-12 col-sm"
              :placeholder="auth.user?.email ?? ''"
              :error="testToError !== null"
              :error-message="testToError ?? undefined"
              :hint="t('settings.test.recipientHint')"
            />
            <div class="col-12 col-sm-auto">
              <q-btn
                outline
                color="primary"
                icon="send"
                :label="t('settings.test.send')"
                no-caps
                :loading="testing"
                :disable="emailError !== null || testToError !== null"
                @click="sendTest"
              />
            </div>
          </div>
          <q-banner
            v-if="testBanner"
            dense
            rounded
            :class="testBanner.ok ? 'surface-green' : 'surface-red'"
          >
            <template #avatar>
              <q-icon :name="testBanner.ok ? 'check_circle' : 'error_outline'" />
            </template>
            {{ testBanner.text }}
          </q-banner>
        </q-card-section>
        <q-card-actions align="right" class="q-px-md q-pb-md">
          <q-btn
            color="primary"
            :label="t('settings.save')"
            :loading="savingEmail"
            :disable="emailError !== null"
            @click="saveEmail"
          />
        </q-card-actions>
      </template>
    </q-card>

    <!-- The server's environment, read-only. One card, one group per section
         of ``.env``: the page is where an administrator comes to answer
         « pourquoi ce poste est-il signalé ? » without opening a shell. -->
    <q-card v-if="settings" flat bordered style="max-width: 960px">
      <q-card-section class="text-subtitle1">
        {{ t('settings.environment.title') }}
        <div class="text-caption text-muted">
          {{ t('settings.environment.captionBefore') }}<code>deploy/.env</code
          >{{ t('settings.environment.captionAfter') }}
        </div>
      </q-card-section>
      <q-separator />
      <q-card-section class="q-pt-sm">
        <q-input
          v-model="envFilter"
          :aria-label="t('settings.environment.search')"
          dense
          outlined
          clearable
          :placeholder="t('settings.environment.searchPlaceholder')"
          style="max-width: 360px"
        >
          <template #prepend><q-icon name="search" /></template>
        </q-input>
      </q-card-section>
      <template v-for="group in environmentGroups" :key="group.key">
        <q-separator />
        <q-card-section class="q-pb-none text-subtitle2">{{ group.label }}</q-card-section>
        <q-markup-table flat dense wrap-cells class="env-table">
          <tbody>
            <tr v-for="item in group.items" :key="item.key">
              <td class="env-key">
                <code>{{ item.key }}</code>
              </td>
              <td class="env-value">
                <span v-if="item.value !== null">{{ item.value }}</span>
                <span v-else class="text-muted">{{ t('settings.environment.notSet') }}</span>
              </td>
              <td class="text-muted">{{ item.description }}</td>
            </tr>
          </tbody>
        </q-markup-table>
      </template>
      <q-card-section v-if="!environmentGroups.length" class="text-muted">
        {{ t('settings.environment.noMatch') }}
      </q-card-section>
    </q-card>
  </q-page>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue';
import { onBeforeRouteLeave } from 'vue-router';
import { useQuasar } from 'quasar';
import LoadErrorBanner from 'src/components/LoadErrorBanner.vue';
import { t } from 'src/i18n';
import { rememberFleetThresholds } from 'src/composables/useFleetThresholds';
import { formSnapshot } from 'src/utils/formSnapshot';
import { listAssignableOwners } from 'src/services/maintenance';
import { apiErrorMessage } from 'src/services/errors';
import {
  getSettings,
  sendTestEmail,
  updateSettings,
  type ConsoleSettings,
  type EmailTestResult,
} from 'src/services/settings';
import { alertRuleLabel } from 'src/services/alerts';
import { useAuthStore } from 'src/stores/auth';
import {
  SECURITY_OPTIONS,
  emailFormError,
  emailFormFrom,
  emailPayload,
  emailStatus,
  providerLabel,
  secretHint,
  secretKind,
  secretState,
  securityLabel,
  testRecipientError,
  testResultText,
  type EmailForm,
} from 'src/utils/emailSettings';
import { intFieldError } from 'src/utils/numberField';
import { usageSettingsError } from 'src/utils/usageFilter';
import { envDescription, envGroupLabel, envValue } from 'src/utils/serverEnvironment';
import {
  WEEKDAY_KEYS,
  digestSummary,
  isAgentVersion,
  readerTimeZone,
  reminderSummary,
  weekdayName,
} from 'src/utils/settingsSchedule';
import { liveDialog } from 'src/utils/liveDialog';
import { notify } from 'src/utils/notify';

const $q = useQuasar();
const auth = useAuthStore();

const settings = ref<ConsoleSettings | null>(null);
const saving = ref(false);
const form = reactive({ cycle: 90, ownerId: null as string | null, dueSoon: 14 });
const ownerOptions = ref<{ label: string; value: string }[]>([]);
// The owner as loaded: sent back only when the operator picks another — a
// default owner deactivated since was shown empty, and saving the card
// cleared it for good (item 3).
let loadedOwnerId: string | null = null;
const canWrite = computed(() => auth.can('settings', 'write'));

function fillMaintenanceForm(s: ConsoleSettings) {
  form.cycle = s.maintenance_default_cycle_days;
  // The stored owner that no longer resolves (deactivated, rights lost) is
  // named and kept as the value, not shown as an empty field.
  form.ownerId =
    s.maintenance_default_owner?.id ?? s.maintenance_default_owner_unavailable?.id ?? null;
  loadedOwnerId = form.ownerId;
  form.dueSoon = s.maintenance_due_soon_days;
  saved.maintenance = formSnapshot(form);
}

// The usage card's own form. `number | string`: an emptied box hands back ''.
const savingUsage = ref(false);
const usageForm = reactive({
  windowDays: 7,
  lowHours: 10,
  highHours: 30,
});
const usageError = computed(() =>
  usageSettingsError(usageForm.windowDays, usageForm.lowHours, usageForm.highHours),
);

function fillUsageForm(s: ConsoleSettings) {
  usageForm.windowDays = s.usage_window_days;
  usageForm.lowHours = s.usage_low_hours;
  usageForm.highHours = s.usage_high_hours;
  saved.usage = formSnapshot(usageForm);
}

// The alerts card. Lists as the server returns them, in the catalogue's order.
const savingAlerts = ref(false);
const alertForm = reactive({
  enabled: [] as string[],
  autoCheck: [] as string[],
  rebootDays: 7 as number | string,
  unencryptedScope: 'laptops',
  forbidden: [] as string[],
});
const alertRebootError = computed(() => intFieldError(alertForm.rebootDays, 1, 365));
const unencryptedOptions = computed(() => [
  { label: t('settings.alerts.scopeLaptops'), value: 'laptops' },
  { label: t('settings.alerts.scopeAll'), value: 'all' },
]);

function fillAlertForm(s: ConsoleSettings) {
  alertForm.enabled = [...(s.alert_enabled_rules ?? [])];
  alertForm.autoCheck = [...(s.alert_auto_check_rules ?? [])];
  alertForm.rebootDays = s.alert_reboot_pending_days ?? 7;
  alertForm.unencryptedScope = s.alert_unencrypted_scope ?? 'laptops';
  alertForm.forbidden = [...(s.alert_forbidden_software ?? [])];
  saved.alerts = formSnapshot(alertForm);
}

async function saveAlerts() {
  if (alertRebootError.value) return;
  savingAlerts.value = true;
  try {
    settings.value = await updateSettings({
      alert_enabled_rules: alertForm.enabled,
      // A rule turned off opens nothing: it is not kept among those that do.
      alert_auto_check_rules: alertForm.autoCheck.filter((r) => alertForm.enabled.includes(r)),
      alert_reboot_pending_days: Number(alertForm.rebootDays),
      alert_unencrypted_scope: alertForm.unencryptedScope as 'laptops' | 'all',
      alert_forbidden_software: alertForm.forbidden
        .map((p) => p.trim())
        .filter((p) => p.length >= 2),
    });
    fillAlertForm(settings.value);
    notify($q, () => ({ type: 'positive', message: t('settings.saved') }));
  } catch (e) {
    notify($q, () => ({ type: 'negative', message: apiErrorMessage(e, t('settings.saveFailed')) }));
  } finally {
    savingAlerts.value = false;
  }
}

// The parc thresholds card. The agent version is a string: '' = automatic.
const savingFleet = ref(false);
const fleetForm = reactive({
  signatureMaxAgeDays: 3,
  inactiveAfterDays: 30,
  lowDiskFreePercent: 10,
  hardwareAgingYears: 5,
  agentExpectedVersion: '',
  commandDefaultTtlMinutes: 60,
});
// The bounds of the server (SettingsUpdate in settings_routes.py), checked
// before sending: an emptied field is not a 0 (audit U06).
const fieldErrors = computed(() => ({
  cycle: intFieldError(form.cycle, 0, 3650),
  dueSoon: intFieldError(form.dueSoon, 0, 365),
  signatureMaxAgeDays: intFieldError(fleetForm.signatureMaxAgeDays, 0, 365),
  inactiveAfterDays: intFieldError(fleetForm.inactiveAfterDays, 1, 3650),
  lowDiskFreePercent: intFieldError(fleetForm.lowDiskFreePercent, 1, 99),
  hardwareAgingYears: intFieldError(fleetForm.hardwareAgingYears, 1, 30),
  commandDefaultTtlMinutes: intFieldError(fleetForm.commandDefaultTtlMinutes, 1, 60 * 24 * 30),
}));
const maintenanceInvalid = computed(
  () => fieldErrors.value.cycle !== null || fieldErrors.value.dueSoon !== null,
);
const fleetInvalid = computed(() =>
  (
    [
      'signatureMaxAgeDays',
      'inactiveAfterDays',
      'lowDiskFreePercent',
      'hardwareAgingYears',
      'commandDefaultTtlMinutes',
    ] as const
  ).some((k) => fieldErrors.value[k] !== null),
);
const agentVersionValid = computed(() => isAgentVersion(fleetForm.agentExpectedVersion ?? ''));

function fillFleetForm(s: ConsoleSettings) {
  fleetForm.signatureMaxAgeDays = s.signature_max_age_days;
  fleetForm.inactiveAfterDays = s.inactive_after_days;
  fleetForm.lowDiskFreePercent = s.low_disk_free_percent;
  fleetForm.hardwareAgingYears = s.hardware_aging_years;
  fleetForm.agentExpectedVersion = s.agent_expected_version ?? '';
  fleetForm.commandDefaultTtlMinutes = s.command_default_ttl_minutes;
  saved.fleet = formSnapshot(fleetForm);
  // The fiche and the list colour their disks by this threshold.
  rememberFleetThresholds(s);
}

// The mail schedule card, and when each mail lands for the reader.
const savingSchedule = ref(false);
const scheduleForm = reactive({ digestHourUtc: 18, reminderWeekday: 0 });
const timeZone = readerTimeZone();
// Computed: their labels follow the reader's language.
const hourOptions = computed(() =>
  Array.from({ length: 24 }, (_, h) => ({
    label: t('settings.schedule.hourOption', { hour: h }),
    value: h,
  })),
);
const weekdayOptions = computed(() =>
  WEEKDAY_KEYS.map((_, i) => {
    const day = weekdayName(i);
    return { label: day.charAt(0).toUpperCase() + day.slice(1), value: i };
  }),
);
const digestHint = computed(() => digestSummary(scheduleForm.digestHourUtc, timeZone));
const reminderHint = computed(() =>
  reminderSummary(scheduleForm.reminderWeekday, scheduleForm.digestHourUtc, timeZone),
);

function fillScheduleForm(s: ConsoleSettings) {
  scheduleForm.digestHourUtc = s.digest_hour_utc;
  scheduleForm.reminderWeekday = s.maintenance_reminder_weekday;
  saved.schedule = formSnapshot(scheduleForm);
}

// The mail card's own form, filled from what the console stored.
const savingEmail = ref(false);
const emailForm = reactive<EmailForm>({
  provider: 'mailgun',
  fromEmail: '',
  fromName: '',
  smtpHost: '',
  smtpPort: '',
  smtpSecurity: 'starttls',
  smtpUser: '',
  smtpPassword: '',
  clearSmtpPassword: false,
  smtpVerifyTls: true,
  smtpTimeout: '',
  mailgunDomain: '',
  mailgunApiKey: '',
  clearMailgunApiKey: false,
  mailgunBaseUrl: '',
});
const emailError = computed(() => emailFormError(emailForm));
const status = computed(() =>
  settings.value ? emailStatus(settings.value.email) : { ok: false, text: '' },
);
// Each secret's case: stored, unreadable, the server's, or none.
function smtpPasswordArgs(): [boolean, boolean, boolean] {
  const e = settings.value?.email;
  // A `.env` password the server holds back is not « celui du .env ».
  return [
    e?.smtp_password_set ?? false,
    e?.smtp_password_unreadable ?? false,
    (e?.env.smtp_password_set ?? false) && !e?.withheld?.includes('smtp_password'),
  ];
}
function mailgunKeyArgs(): [boolean, boolean, boolean] {
  const e = settings.value?.email;
  return [
    e?.mailgun_api_key_set ?? false,
    e?.mailgun_api_key_unreadable ?? false,
    (e?.env.mailgun_api_key_set ?? false) && !e?.withheld?.includes('mailgun_api_key'),
  ];
}
const smtpPasswordKind = computed(() => secretKind(...smtpPasswordArgs()));
const smtpPasswordState = computed(() => secretState(...smtpPasswordArgs()));
const mailgunKeyKind = computed(() => secretKind(...mailgunKeyArgs()));
const mailgunKeyState = computed(() => secretState(...mailgunKeyArgs()));
const providerOptions = computed(() => [
  { label: t('settings.email.providers.smtp'), value: 'smtp' },
  { label: t('settings.email.providers.mailgun'), value: 'mailgun' },
]);
const testTo = ref('');
const testToError = computed(() => testRecipientError(testTo.value ?? ''));
const testing = ref(false);
const testResult = ref<EmailTestResult | null>(null);
// A test the server refused: the error itself, worded at render so a change
// of language rewords it.
const testFailure = ref<{ error: unknown } | null>(null);
const testBanner = computed(() => {
  if (testResult.value) return { ok: testResult.value.ok, text: testResultText(testResult.value) };
  if (testFailure.value)
    return { ok: false, text: apiErrorMessage(testFailure.value.error, t('settings.test.failed')) };
  return null;
});

function fillEmailForm(s: ConsoleSettings) {
  Object.assign(emailForm, emailFormFrom(s.email));
  saved.email = formSnapshot(emailForm);
}

// --- Unsaved changes (item 12). Each card's form as last filled from the
// server; a card whose form differs holds changes « Enregistrer » has not
// sent. All five cards: a cycle retyped and left unsaved is lost like any
// other field.
const saved = reactive({
  maintenance: '',
  usage: '',
  alerts: '',
  fleet: '',
  schedule: '',
  email: '',
});
// The cards by their key in the catalogue (`settings.unsaved.cards`).
const unsavedCards = computed(() => {
  if (!settings.value || !canWrite.value) return [];
  const cards: string[] = [];
  if (formSnapshot(form) !== saved.maintenance) cards.push('maintenance');
  if (formSnapshot(usageForm) !== saved.usage) cards.push('usage');
  if (formSnapshot(alertForm) !== saved.alerts) cards.push('alerts');
  if (formSnapshot(fleetForm) !== saved.fleet) cards.push('fleet');
  if (formSnapshot(scheduleForm) !== saved.schedule) cards.push('schedule');
  if (formSnapshot(emailForm) !== saved.email) cards.push('email');
  return cards;
});

onBeforeRouteLeave(() => {
  const cards = unsavedCards.value;
  if (!cards.length) return true;
  return new Promise<boolean>((resolve) => {
    liveDialog($q, () => ({
      title: t('settings.unsaved.title'),
      message: t('settings.unsaved.message', {
        cards: cards
          .map((card) => t(`settings.unsaved.cards.${card}`))
          .join(t('settings.unsaved.cardSeparator')),
      }),
      cancel: { flat: true, noCaps: true, label: t('settings.unsaved.stay') },
      ok: {
        unelevated: true,
        noCaps: true,
        label: t('settings.unsaved.leave'),
        color: 'negative',
      },
      persistent: true,
    }))
      .onOk(() => resolve(true))
      .onCancel(() => resolve(false));
  });
});

// A reload or a closed tab: the browser's own question.
function onBeforeUnload(event: BeforeUnloadEvent) {
  if (!unsavedCards.value.length) return;
  event.preventDefault();
  event.returnValue = '';
}
window.addEventListener('beforeunload', onBeforeUnload);
onBeforeUnmount(() => window.removeEventListener('beforeunload', onBeforeUnload));

// The environment card, worded in the reader's language
// (`utils/serverEnvironment.ts`) and narrowed by the search box: on the
// variable's name, its value and its description alike, as shown, since a
// reader may know any of the three (« ROOM_SOURCE », « ad_ou », « salles »).
interface ShownEnvItem {
  key: string;
  value: string | null;
  description: string;
}
const envFilter = ref('');
const environmentGroups = computed<{ key: string; label: string; items: ShownEnvItem[] }[]>(() => {
  const groups = (settings.value?.environment ?? []).map((g) => ({
    key: g.code ?? g.label,
    label: envGroupLabel(g),
    items: g.items.map((i) => ({
      key: i.key,
      value: envValue(i),
      description: envDescription(i),
    })),
  }));
  const needle = (envFilter.value ?? '').trim().toLocaleLowerCase();
  if (!needle) return groups;
  const matches = (item: ShownEnvItem) =>
    [item.key, item.value ?? '', item.description].some((text) =>
      text.toLocaleLowerCase().includes(needle),
    );
  return groups
    .map((g) => ({ ...g, items: g.items.filter(matches) }))
    .filter((g) => g.items.length);
});

// The first read failed: the banner above, with « Réessayer » (item 2).
const loadError = ref<unknown>(null);
const reloading = ref(false);
async function retryLoad() {
  reloading.value = true;
  try {
    await load();
  } finally {
    reloading.value = false;
  }
}

async function load() {
  try {
    settings.value = await getSettings();
    loadError.value = null;
    const unavailable = settings.value.maintenance_default_owner_unavailable ?? null;
    fillMaintenanceForm(settings.value);
    fillUsageForm(settings.value);
    fillAlertForm(settings.value);
    fillFleetForm(settings.value);
    fillScheduleForm(settings.value);
    fillEmailForm(settings.value);
    // Only the accounts the server accepts as default owner: maintenance
    // rights over the whole parc.
    // Asked only of an account that may change the owner: a read-only one got
    // a 403 and a toast for a list it cannot use (item 4).
    const options = (canWrite.value ? await listAssignableOwners() : []).map((u) => ({
      label: u.name,
      value: u.id,
    }));
    if (unavailable && !options.some((o) => o.value === unavailable.id)) {
      options.unshift({
        label: t('settings.maintenance.ownerDeactivated', { name: unavailable.name }),
        value: unavailable.id,
      });
    }
    ownerOptions.value = options;
  } catch (e) {
    // Before the settings: nothing to show, the banner says why. After them
    // (the owner list): the cards are shown, the toast names what is missing.
    if (!settings.value) loadError.value = e;
    else
      notify($q, () => ({
        type: 'negative',
        message: apiErrorMessage(e, t('settings.loadFailed')),
      }));
  }
}

async function save() {
  if (maintenanceInvalid.value) return;
  saving.value = true;
  try {
    settings.value = await updateSettings({
      maintenance_default_cycle_days: Number(form.cycle),
      ...(form.ownerId !== loadedOwnerId ? { maintenance_default_owner_id: form.ownerId } : {}),
      maintenance_due_soon_days: Number(form.dueSoon),
    });
    fillMaintenanceForm(settings.value);
    notify($q, () => ({ type: 'positive', message: t('settings.saved') }));
  } catch (e) {
    notify($q, () => ({ type: 'negative', message: apiErrorMessage(e, t('settings.saveFailed')) }));
  } finally {
    saving.value = false;
  }
}

async function saveUsage() {
  if (usageError.value) return;
  savingUsage.value = true;
  try {
    settings.value = await updateSettings({
      usage_window_days: Number(usageForm.windowDays),
      usage_low_hours: Number(usageForm.lowHours),
      usage_high_hours: Number(usageForm.highHours),
    });
    fillUsageForm(settings.value);
    notify($q, () => ({ type: 'positive', message: t('settings.saved') }));
  } catch (e) {
    notify($q, () => ({ type: 'negative', message: apiErrorMessage(e, t('settings.saveFailed')) }));
  } finally {
    savingUsage.value = false;
  }
}

async function saveFleet() {
  if (!agentVersionValid.value || fleetInvalid.value) return;
  savingFleet.value = true;
  try {
    settings.value = await updateSettings({
      signature_max_age_days: Number(fleetForm.signatureMaxAgeDays),
      inactive_after_days: Number(fleetForm.inactiveAfterDays),
      low_disk_free_percent: Number(fleetForm.lowDiskFreePercent),
      hardware_aging_years: Number(fleetForm.hardwareAgingYears),
      // '' and not null: « automatique » is a choice the console makes, and
      // must win over a version pinned in the environment.
      agent_expected_version: (fleetForm.agentExpectedVersion ?? '').trim(),
      command_default_ttl_minutes: Number(fleetForm.commandDefaultTtlMinutes),
    });
    fillFleetForm(settings.value);
    notify($q, () => ({ type: 'positive', message: t('settings.saved') }));
  } catch (e) {
    notify($q, () => ({ type: 'negative', message: apiErrorMessage(e, t('settings.saveFailed')) }));
  } finally {
    savingFleet.value = false;
  }
}

async function saveSchedule() {
  savingSchedule.value = true;
  try {
    settings.value = await updateSettings({
      digest_hour_utc: scheduleForm.digestHourUtc,
      maintenance_reminder_weekday: scheduleForm.reminderWeekday,
    });
    fillScheduleForm(settings.value);
    notify($q, () => ({ type: 'positive', message: t('settings.saved') }));
  } catch (e) {
    notify($q, () => ({ type: 'negative', message: apiErrorMessage(e, t('settings.saveFailed')) }));
  } finally {
    savingSchedule.value = false;
  }
}

async function saveEmail() {
  if (!settings.value || emailError.value) return;
  savingEmail.value = true;
  try {
    settings.value = await updateSettings({ email: emailPayload(emailForm, settings.value.email) });
    fillEmailForm(settings.value);
    notify($q, () => ({ type: 'positive', message: t('settings.email.saved') }));
  } catch (e) {
    notify($q, () => ({ type: 'negative', message: apiErrorMessage(e, t('settings.saveFailed')) }));
  } finally {
    savingEmail.value = false;
  }
}

async function sendTest() {
  if (!settings.value || emailError.value || testToError.value) return;
  testing.value = true;
  testResult.value = null;
  testFailure.value = null;
  try {
    const to = (testTo.value ?? '').trim();
    testResult.value = await sendTestEmail({
      ...(to ? { to } : {}),
      email: emailPayload(emailForm, settings.value.email),
    });
  } catch (e) {
    testFailure.value = { error: e };
  } finally {
    testing.value = false;
  }
}

onMounted(load);
</script>

<style scoped>
.env-table td {
  vertical-align: top;
}
.env-key {
  width: 30%;
  white-space: nowrap;
}
/* Phone: the long keys no longer squeeze the description into a sliver —
   each line stacks, key and value above, description below (audit U27). */
@media (max-width: 599px) {
  /* Stacked on a phone (audit U27). « height: auto »: Quasar's dense table
     fixes a cell at 28 px, and the stacked blocks then overlapped. */
  .env-table tbody tr,
  .env-table tbody td {
    display: block;
    width: 100%;
    height: auto;
  }
  .env-key {
    white-space: normal;
    word-break: break-all;
    padding-bottom: 0;
  }
  .env-value {
    padding-top: 0;
  }
}
.env-value {
  width: 20%;
  font-weight: 500;
}
</style>

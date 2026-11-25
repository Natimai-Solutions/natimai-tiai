<template>
  <!-- One form for a new schedule — from the page, a room or a selection of
       postes — and for one rewritten. Saved, it runs in the writer's name. -->
  <q-dialog :model-value="modelValue" @update:model-value="(v) => emit('update:modelValue', v)">
    <q-card style="width: 720px; max-width: 95vw">
      <q-card-section class="text-h6">
        {{ schedule ? t('schedules.form.titleEdit') : t('schedules.form.titleNew') }}
      </q-card-section>
      <q-form @submit="submit">
        <q-card-section class="q-gutter-md">
          <q-input
            v-model="form.name"
            :label="t('schedules.form.name')"
            outlined
            dense
            maxlength="200"
            autofocus
            reactive-rules
            :rules="[(v: string) => !!v?.trim() || t('schedules.form.nameRequired')]"
          />
          <div class="row q-col-gutter-sm">
            <q-select
              v-model="form.command_type"
              class="col-12 col-sm-6"
              :options="actionOptions"
              emit-value
              map-options
              outlined
              dense
              :label="t('schedules.form.action')"
            />
            <q-select
              v-if="isPackage"
              v-model="form.package_id"
              class="col-12 col-sm-6"
              :options="packageOptions"
              emit-value
              map-options
              outlined
              dense
              :label="t('schedules.form.package')"
              reactive-rules
              :rules="[(v: string | null) => !!v || t('schedules.form.required')]"
            />
          </div>

          <ScheduleTargetField
            v-model="form.target"
            :label="t('schedules.form.target')"
            :initial-machine-ids="initialMachineIds"
            :rooms="rooms"
            :buildings="buildings"
          />

          <div>
            <div class="text-caption text-muted">{{ t('schedules.form.recurrence') }}</div>
            <q-option-group
              v-model="form.recurrence"
              inline
              :options="[
                { label: t('schedules.form.once'), value: 'once' },
                { label: t('schedules.form.weekly'), value: 'weekly' },
              ]"
            />
          </div>
          <div class="row q-col-gutter-sm items-start">
            <q-input
              v-if="form.recurrence === 'once'"
              v-model="form.date"
              class="col-12 col-sm-5"
              type="date"
              outlined
              dense
              stack-label
              :label="t('schedules.form.date')"
              reactive-rules
              :rules="[(v: string) => !!v || t('schedules.form.required')]"
            />
            <div v-else class="col-12 col-sm-7">
              <div class="text-caption text-muted">{{ t('schedules.form.days') }}</div>
              <q-option-group
                v-model="form.weekdays"
                type="checkbox"
                inline
                dense
                :options="dayOptions"
              />
              <div v-if="daysError" class="text-caption text-negative">
                {{ t('schedules.form.daysRequired') }}
              </div>
            </div>
            <q-input
              v-model="form.time"
              class="col-6 col-sm-3"
              type="time"
              outlined
              dense
              stack-label
              :label="t('schedules.form.time')"
              :hint="t('schedules.form.zoneHint', { zone: timezone })"
              reactive-rules
              :rules="[(v: string) => !!v || t('schedules.form.required')]"
            />
          </div>
          <div v-if="forbiddenWindows.length" class="text-caption text-muted">
            {{ t('schedules.form.forbiddenHint', { windows: windowsText(forbiddenWindows) }) }}
          </div>

          <q-input
            v-model.number="form.ttl_hours"
            type="number"
            min="1"
            max="24"
            outlined
            dense
            style="max-width: 260px"
            :label="t('schedules.form.ttl')"
            :suffix="t('schedules.form.hours')"
            :hint="t('schedules.form.ttlHint')"
          />

          <div v-if="form.command_type !== 'wake_on_lan'">
            <q-toggle v-model="form.wake_first" :label="t('schedules.form.wakeFirst')" />
            <div v-if="!isPower">
              <q-toggle
                v-model="form.shutdown_after"
                :disable="!form.wake_first"
                :label="t('schedules.form.shutdownAfter')"
              />
              <div class="text-caption text-muted q-pl-md">
                {{ t('schedules.form.shutdownAfterHint') }}
              </div>
            </div>
          </div>

          <div v-if="canRing">
            <q-toggle v-model="form.rings_on" :label="t('schedules.form.rings')" />
            <div class="text-caption text-muted q-pl-md">{{ t('schedules.form.ringsHint') }}</div>
            <div v-if="form.rings_on" class="q-pl-md q-mt-sm q-gutter-sm">
              <div
                v-for="(stage, i) in form.rings"
                :key="i"
                class="row items-center q-col-gutter-sm"
              >
                <ScheduleTargetField
                  :model-value="stage"
                  class="col"
                  :label="t('schedules.form.stage', { n: i + 1 })"
                  :rooms="rooms"
                  :buildings="buildings"
                  :kinds="['room', 'building', 'location', 'all']"
                  @update:model-value="(v: ScheduleTargetIn) => (form.rings[i] = v)"
                />
                <q-btn
                  v-if="form.rings.length > 2"
                  flat
                  round
                  dense
                  icon="remove_circle_outline"
                  :aria-label="t('schedules.form.removeStage')"
                  @click="form.rings.splice(i, 1)"
                />
              </div>
              <q-btn
                v-if="form.rings.length < 5"
                flat
                dense
                no-caps
                icon="add"
                color="primary"
                :label="t('schedules.form.addStage')"
                @click="form.rings.push({ kind: 'room', value: null })"
              />
              <div class="row q-col-gutter-sm">
                <q-input
                  v-model.number="form.ring_observe_hours"
                  class="col-6 col-sm-4"
                  type="number"
                  min="1"
                  max="336"
                  outlined
                  dense
                  :label="t('schedules.form.observe')"
                  :suffix="t('schedules.form.hours')"
                />
                <q-input
                  v-model.number="form.ring_failure_percent"
                  class="col-6 col-sm-4"
                  type="number"
                  min="0"
                  max="100"
                  outlined
                  dense
                  :label="t('schedules.form.threshold')"
                  :suffix="t('schedules.form.percent')"
                />
              </div>
            </div>
          </div>
        </q-card-section>
        <q-card-actions align="right" class="q-px-md q-pb-md">
          <q-btn v-close-popup flat no-caps :label="t('schedules.form.cancel')" />
          <q-btn
            type="submit"
            color="primary"
            no-caps
            :label="t('schedules.form.save')"
            :loading="saving"
          />
        </q-card-actions>
      </q-form>
    </q-card>
  </q-dialog>
</template>

<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue';
import { useQuasar } from 'quasar';
import ScheduleTargetField from 'src/components/schedule/ScheduleTargetField.vue';
import { t } from 'src/i18n';
import { notifyApprovalsChanged } from 'src/composables/useApprovalsBadge';
import { canRunCommand, commandActions, commandTypeLabel } from 'src/services/commands';
import { apiErrorMessage } from 'src/services/errors';
import { listPackages, type Package } from 'src/services/packages';
import { listBuildings, listRooms, type Building, type Room } from 'src/services/rooms';
import {
  POWER_TYPES,
  RING_TYPES,
  createSchedule,
  updateSchedule,
  windowsText,
  type ForbiddenWindow,
  type Schedule,
  type SchedulePayload,
  type ScheduleTargetIn,
} from 'src/services/schedules';
import { useAuthStore } from 'src/stores/auth';
import { formatDateTime } from 'src/utils/format';
import { notify } from 'src/utils/notify';
import { WEEKDAY_KEYS, weekdayName } from 'src/utils/settingsSchedule';

const props = defineProps<{
  modelValue: boolean;
  /** The schedule to rewrite; null for a new one. */
  schedule: Schedule | null;
  /** Where a new one starts from: a room, a selection of postes. */
  initialTarget?: ScheduleTargetIn | null | undefined;
  timezone: string;
  forbiddenWindows: ForbiddenWindow[];
}>();
const emit = defineEmits<{
  (e: 'update:modelValue', value: boolean): void;
  (e: 'saved', schedule: Schedule): void;
}>();

const $q = useQuasar();
const auth = useAuthStore();
const saving = ref(false);
const rooms = ref<Room[]>([]);
const buildings = ref<Building[]>([]);
const packages = ref<Package[]>([]);
const daysError = ref(false);

const empty = () => ({
  name: '',
  command_type: 'quick_scan',
  package_id: null as string | null,
  target: { kind: 'all' } as ScheduleTargetIn,
  recurrence: 'once' as 'once' | 'weekly',
  date: '',
  time: '18:00',
  weekdays: [] as number[],
  ttl_hours: 3,
  wake_first: false,
  shutdown_after: false,
  rings_on: false,
  rings: [] as ScheduleTargetIn[],
  ring_observe_hours: 24,
  ring_failure_percent: 10,
});
const form = reactive(empty());

const permissions = computed(() => new Set(auth.user?.permissions ?? []));
const actionOptions = computed(() => {
  const options = commandActions
    .filter((a) => a.bulk && canRunCommand(permissions.value, a))
    .map((a) => ({ label: a.label, value: a.type }));
  if (permissions.value.has('package:read') && permissions.value.has('risky_command:execute')) {
    for (const type of ['package_install', 'package_uninstall']) {
      options.push({ label: commandTypeLabel(type), value: type as never });
    }
  }
  return options;
});
const packageOptions = computed(() =>
  packages.value.map((p) => ({
    label: p.version ? `${p.name} ${p.version}` : p.name,
    value: p.id,
  })),
);
const dayOptions = computed(() =>
  WEEKDAY_KEYS.map((_, i) => ({ label: weekdayName(i), value: i })),
);
const isPackage = computed(() => form.command_type.startsWith('package_'));
const isPower = computed(() => (POWER_TYPES as readonly string[]).includes(form.command_type));
const canRing = computed(() => (RING_TYPES as readonly string[]).includes(form.command_type));
const initialMachineIds = computed(() =>
  props.initialTarget?.kind === 'machines' ? (props.initialTarget.machine_ids ?? []) : [],
);

watch(
  () => [form.wake_first, form.command_type],
  () => {
    if (!form.wake_first || isPower.value || form.command_type === 'wake_on_lan') {
      form.shutdown_after = false;
    }
    if (form.command_type === 'wake_on_lan') form.wake_first = false;
    if (!canRing.value) form.rings_on = false;
  },
);
watch(
  () => form.rings_on,
  (on) => {
    if (on && form.rings.length < 2) {
      form.rings = [{ ...form.target }, { kind: 'all' }];
    }
  },
);

function fromSchedule(s: Schedule) {
  const [date, time] = (s.run_at_local ?? '').split('T');
  Object.assign(form, {
    name: s.name,
    command_type: s.command_type,
    package_id: s.package_id,
    target: { kind: s.target.kind, machine_ids: s.target.machine_ids, value: s.target.value },
    recurrence: s.recurrence,
    date: date ?? '',
    time: s.recurrence === 'once' ? (time ?? '') : (s.time_of_day ?? ''),
    weekdays: [...s.weekdays],
    ttl_hours: Math.max(1, Math.round(s.ttl_minutes / 60)),
    wake_first: s.wake_first,
    shutdown_after: s.shutdown_after,
    rings_on: !!s.rings,
    rings: (s.rings ?? []).map((r) => ({
      kind: r.kind,
      machine_ids: r.machine_ids,
      value: r.value,
    })),
    ring_observe_hours: s.ring_observe_hours ?? 24,
    ring_failure_percent: s.ring_failure_percent ?? 10,
  });
}

watch(
  () => props.modelValue,
  async (open) => {
    if (!open) return;
    Object.assign(form, empty());
    daysError.value = false;
    if (props.schedule) fromSchedule(props.schedule);
    else if (props.initialTarget) form.target = { ...props.initialTarget };
    const can = (p: string) => permissions.value.has(p);
    const [r, b, p] = await Promise.all([
      can('room:read') ? listRooms().catch(() => []) : Promise.resolve([]),
      can('room:read') ? listBuildings().catch(() => []) : Promise.resolve([]),
      can('package:read') ? listPackages().catch(() => []) : Promise.resolve([]),
    ]);
    rooms.value = r;
    buildings.value = b;
    packages.value = p;
  },
  { immediate: true },
);

function payload(): SchedulePayload {
  const out: SchedulePayload = {
    name: form.name.trim(),
    command_type: form.command_type,
    package_id: isPackage.value ? form.package_id : null,
    target: form.target,
    recurrence: form.recurrence,
    ttl_minutes: Math.round(Number(form.ttl_hours) * 60) || null,
    wake_first: form.wake_first,
    shutdown_after: form.shutdown_after,
  };
  if (form.recurrence === 'once') out.run_at_local = `${form.date}T${form.time}`;
  else {
    out.weekdays = [...form.weekdays].sort((a, b) => a - b);
    out.time_of_day = form.time;
  }
  if (form.rings_on && canRing.value) {
    out.rings = form.rings.map((target) => ({ target }));
    out.ring_observe_hours = Number(form.ring_observe_hours);
    out.ring_failure_percent = Number(form.ring_failure_percent);
  }
  return out;
}

async function submit(): Promise<void> {
  daysError.value = form.recurrence === 'weekly' && form.weekdays.length === 0;
  if (daysError.value) return;
  saving.value = true;
  try {
    const body = payload();
    const saved = props.schedule
      ? await updateSchedule(props.schedule.id, body)
      : await createSchedule(body);
    // C10: beyond the threshold, a schedule at risk waits for a second
    // account before it runs — said, rather than « saved » alone.
    const waiting = saved.state === 'to_approve';
    if (waiting) notifyApprovalsChanged();
    notify($q, () =>
      waiting
        ? {
            type: 'info',
            message: t('schedules.actions.savedToApprove', {
              at: formatDateTime(saved.approval?.expires_at ?? null),
            }),
          }
        : { type: 'positive', message: t('schedules.actions.saved') },
    );
    emit('saved', saved);
    emit('update:modelValue', false);
  } catch (e) {
    notify($q, () => ({
      type: 'negative',
      message: apiErrorMessage(e, t('schedules.actions.failed')),
    }));
  } finally {
    saving.value = false;
  }
}
</script>

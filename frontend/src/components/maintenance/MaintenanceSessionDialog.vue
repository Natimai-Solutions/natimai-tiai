<template>
  <!-- Recording a visit: the date, a global note, and the postes done —
       each with its own note. A poste absent or off that day is unticked
       rather than lied about. -->
  <!-- Persistent: a note per poste is minutes of typing, and Échap or a
       click beside the card must not throw it away (audit U14). -->
  <q-dialog
    :model-value="modelValue"
    persistent
    :maximized="small"
    @update:model-value="(v) => emit('update:modelValue', v)"
    @keydown.esc="cancel"
  >
    <!-- Échap is ours to handle: a persistent dialog only shakes. On a phone
         the whole screen, the list scrolling between a fixed title and fixed
         buttons (audit U23); on a wider screen too, within the window's
         height: where a sending stopped stays in view beside its buttons. -->
    <q-card
      class="column no-wrap"
      :style="small ? undefined : 'width: 720px; max-width: 95vw; max-height: calc(100vh - 48px)'"
      data-test="session-card"
    >
      <q-card-section class="text-h6">{{
        roomName
          ? t('maintenance.session.titleIn', { room: roomName })
          : t('maintenance.session.title')
      }}</q-card-section>
      <q-form class="col column no-wrap" style="min-height: 0" @submit="submit">
        <q-card-section class="col scroll q-gutter-md" data-test="session-list">
          <!-- In a block of its own: the row's column gutter is a negative
               margin, which the section's gutter would otherwise replace —
               the two fields then sat against the card's left edge. -->
          <div>
            <div class="row q-col-gutter-md">
              <q-input
                v-model="performedAt"
                :label="t('maintenance.session.date')"
                outlined
                dense
                type="datetime-local"
                stack-label
                class="col-12 col-sm-5"
                :hint="t('maintenance.session.backdating')"
                :disable="!!pending"
              />
              <q-input
                v-model="note"
                :label="t('maintenance.session.generalNote')"
                outlined
                dense
                autogrow
                type="textarea"
                maxlength="5000"
                class="col-12 col-sm-7"
                :disable="!!pending"
              />
            </div>
          </div>
          <!-- A phone gets a list: the name, then its note below at full
               width, rather than a table whose note column sits off screen. -->
          <q-list v-if="small" bordered separator data-test="session-rows">
            <q-item>
              <q-item-section side>
                <q-checkbox
                  :model-value="allDone"
                  :aria-label="t('maintenance.session.toggleAll')"
                  :disable="!!pending"
                  @update:model-value="(v) => toggleAll(v === true)"
                />
              </q-item-section>
              <q-item-section class="text-weight-medium">{{
                t('maintenance.session.tickAll')
              }}</q-item-section>
            </q-item>
            <q-item v-for="row in rows" :key="row.id" class="column q-py-sm">
              <div class="row items-center no-wrap">
                <q-checkbox
                  v-model="row.done"
                  :aria-label="t('maintenance.session.done', { name: row.hostname })"
                  :disable="!!pending"
                />
                <div class="col q-ml-sm" style="min-width: 0; overflow-wrap: anywhere">
                  {{ row.hostname }}
                  <div v-if="hintOf(row)" class="text-caption text-muted">{{ hintOf(row) }}</div>
                </div>
              </div>
              <q-input
                v-model="row.note"
                :aria-label="t('maintenance.session.noteFor', { name: row.hostname })"
                dense
                outlined
                :placeholder="
                  row.done
                    ? t('maintenance.session.notePlaceholder')
                    : t('maintenance.session.whyNotDone')
                "
                maxlength="5000"
                :disable="!!pending"
                class="q-mt-xs"
              />
            </q-item>
          </q-list>
          <q-markup-table v-else flat bordered dense>
            <thead>
              <tr>
                <th style="width: 40px">
                  <q-checkbox
                    :model-value="allDone"
                    dense
                    :aria-label="t('maintenance.session.toggleAll')"
                    :disable="!!pending"
                    @update:model-value="(v) => toggleAll(v === true)"
                  />
                </th>
                <th class="text-left">{{ t('maintenance.session.machine') }}</th>
                <th class="text-left">{{ t('maintenance.session.machineNote') }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in rows" :key="row.id">
                <td>
                  <q-checkbox
                    v-model="row.done"
                    dense
                    :aria-label="t('maintenance.session.done', { name: row.hostname })"
                    :disable="!!pending"
                  />
                </td>
                <td>
                  {{ row.hostname }}
                  <div v-if="hintOf(row)" class="text-caption text-muted">{{ hintOf(row) }}</div>
                </td>
                <td>
                  <!-- Open on an unticked poste too: why it was not done is
                       worth keeping, in its own journal (audit U20). -->
                  <q-input
                    v-model="row.note"
                    :aria-label="t('maintenance.session.noteFor', { name: row.hostname })"
                    dense
                    borderless
                    :placeholder="row.done ? '—' : t('maintenance.session.whyNotDoneOptional')"
                    maxlength="5000"
                    :disable="!!pending"
                  />
                </td>
              </tr>
            </tbody>
          </q-markup-table>
          <div class="text-caption text-muted">
            {{ t('maintenance.session.explain', { count: doneCount }) }}
          </div>
          <div v-if="!doneCount" class="text-caption text-warn" data-test="session-nothing-done">
            {{ t('maintenance.session.nothingDone') }}
          </div>
        </q-card-section>
        <q-separator />
        <!-- Where a sending stopped, said beside the buttons that act on it
             — not above a list of a thousand postes, scrolled out of sight. -->
        <q-card-section v-if="pending || refused" class="q-gutter-sm q-pb-none">
          <q-banner v-if="pending" rounded class="surface-blue" data-test="session-pending">
            <template v-if="pending.progress.sessionId">
              {{
                t('maintenance.session.partlySent', {
                  sent: pending.progress.sent,
                  total: pending.progress.total,
                })
              }}
            </template>
            <!-- The part that creates the visit got no answer: recorded or
                 not, nobody knows — sent again, it cannot create a second. -->
            <template v-else>
              {{ t('maintenance.session.noAnswer') }}
            </template>
          </q-banner>
          <!-- Postes the server refuses a part for: named, and left out at a
               click — the rest of the visit must not wait on them. The part
               that creates the visit too: nothing is recorded, and the form,
               editable again, is sent anew without them. -->
          <q-banner v-if="refused" rounded class="surface-orange" data-test="session-refused">
            {{
              refused.reason === 'moved'
                ? t('maintenance.session.refusedMoved', { names: refusedNames })
                : t('maintenance.session.refusedGone', { names: refusedNames })
            }}
            <template #action>
              <q-btn
                flat
                no-caps
                color="primary"
                :label="t('maintenance.session.dropRefused')"
                :disable="saving"
                data-test="session-drop"
                @click="dropRefused"
              />
            </template>
          </q-banner>
        </q-card-section>
        <q-card-actions align="right" class="q-px-md q-pb-md" :class="small ? 'q-pt-md' : ''">
          <!-- Not while a part is on its way: closing would not stop the
               sending, only hide where it stops. Once it has stopped, the
               pending state says what is recorded and offers to abandon. -->
          <q-btn flat :label="t('maintenance.actions.cancel')" :disable="saving" @click="cancel" />
          <q-btn
            type="submit"
            color="primary"
            :label="pending ? t('maintenance.session.resume') : t('maintenance.actions.save')"
            :disable="!canSave"
            :loading="saving"
          />
        </q-card-actions>
      </q-form>
    </q-card>
  </q-dialog>
</template>

<script setup lang="ts">
import { notifyTasksChanged } from 'src/composables/useTasksBadge';
import { computed, ref, watch } from 'vue';
import { useQuasar } from 'quasar';
import {
  dropUnsentLines,
  isRefusal,
  recordSessionInParts,
  refusedMachines,
  sessionProgress,
  type RefusedMachines,
  type SessionPayload,
  type SessionProgress,
} from 'src/services/maintenance';
import { apiErrorMessage, someNames } from 'src/services/errors';
import { t } from 'src/i18n';

export interface SessionMachine {
  id: string;
  hostname: string;
  /** A line under the name: its standing, its last visit. */
  hint?: string | undefined;
  /** Ticked when the dialog opens; true when unsaid. */
  preselect?: boolean;
}

const props = defineProps<{
  modelValue: boolean;
  roomId: string | null;
  roomName: string | null;
  machines: SessionMachine[];
}>();
const emit = defineEmits<{
  (e: 'update:modelValue', value: boolean): void;
  (e: 'recorded'): void;
}>();

const $q = useQuasar();
const small = computed(() => $q.screen.lt.sm);
const saving = ref(false);
const note = ref('');
const performedAt = ref('');
// `removed`: left out of the visit after the server refused it — said
// under its name instead of its hint.
const rows = ref<{ id: string; hostname: string; removed: boolean; done: boolean; note: string }[]>(
  [],
);
// The hints as the page words them now: a language changed while the dialog
// is open shows in them too.
const hints = computed(() => new Map(props.machines.map((m) => [m.id, m.hint])));
function hintOf(row: { id: string; removed: boolean }): string | undefined {
  return row.removed ? t('maintenance.session.removedFromSession') : hints.value.get(row.id);
}
// A visit whose sending stopped half-way — or whose first part got no answer,
// and may be recorded: what was sent, frozen, and how far it got. « Reprendre
// l'envoi » sends the rest into the same visit rather than a second one.
const pending = ref<{ payload: SessionPayload; progress: SessionProgress } | null>(null);
// The postes the server named in refusing the part the sending stopped on.
const refused = ref<RefusedMachines | null>(null);
// The first few, then how many more: fifty names would push the buttons off
// a phone's screen.
const refusedNames = computed(() =>
  someNames(
    (refused.value?.ids ?? []).map((id) => rows.value.find((r) => r.id === id)?.hostname ?? id),
  ),
);

const doneCount = computed(() => rows.value.filter((r) => r.done).length);
const allDone = computed<boolean | null>(() =>
  doneCount.value === 0 ? false : doneCount.value === rows.value.length ? true : null,
);
// The server's rule (audit T30): nothing done is a visit too, when it says
// why — a poste left out with its note, or the room's global note.
const canSave = computed(
  () =>
    !!pending.value ||
    doneCount.value > 0 ||
    rows.value.some((r) => !r.done && !r.removed && r.note.trim()) ||
    (!!props.roomId && !!note.value.trim()),
);

function toLocalInput(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

// The form as it was filled: what « modifié » is measured from.
let pristine = '';
// What the form was filled for, kept until a save or a confirmed cancel: a
// dialog reopened on the same room finds its input again.
let filledFor: string | null = null;

function snapshot(): string {
  return JSON.stringify([note.value, performedAt.value, rows.value]);
}

function reset() {
  note.value = '';
  performedAt.value = toLocalInput(new Date());
  rows.value = props.machines.map((m) => ({
    id: m.id,
    hostname: m.hostname,
    removed: false,
    done: m.preselect ?? true,
    note: '',
  }));
  pending.value = null;
  refused.value = null;
  pristine = snapshot();
  filledFor = `${props.roomId ?? ''}|${props.machines.map((m) => m.id).join(',')}`;
}

watch(
  () => props.modelValue,
  (open) => {
    if (!open) return;
    const key = `${props.roomId ?? ''}|${props.machines.map((m) => m.id).join(',')}`;
    if (key !== filledFor) reset();
  },
);

function close() {
  filledFor = null;
  emit('update:modelValue', false);
}

/** Annuler, or Échap: straight away when nothing was typed, else confirmed. */
function cancel() {
  // Échap while a part is on its way: the sending would go on behind a
  // closed dialog, and « Abandonner » would have abandoned nothing.
  if (saving.value) return;
  if (pending.value) {
    // Part of the visit is recorded already — or may be: closing keeps that
    // part, and the page must show it.
    const { sessionId, sent, total } = pending.value.progress;
    $q.dialog({
      title: t('maintenance.session.abandonSendingTitle'),
      message: sessionId
        ? t('maintenance.session.abandonSendingPartly', { sent, total })
        : t('maintenance.session.abandonSendingUnknown'),
      cancel: { flat: true, noCaps: true, label: t('maintenance.session.resume') },
      ok: { flat: true, noCaps: true, label: t('maintenance.session.abandon'), color: 'negative' },
      persistent: true,
    }).onOk(() => {
      close();
      notifyTasksChanged();
      emit('recorded');
    });
    return;
  }
  if (snapshot() === pristine) {
    close();
    return;
  }
  $q.dialog({
    title: t('maintenance.session.abandonInputTitle'),
    message: t('maintenance.session.abandonInputBody'),
    cancel: { flat: true, noCaps: true, label: t('maintenance.session.continueInput') },
    ok: { flat: true, noCaps: true, label: t('maintenance.session.abandon'), color: 'negative' },
    persistent: true,
  }).onOk(close);
}

function toggleAll(on: boolean) {
  for (const r of rows.value) r.done = on;
}

function payloadOf(): SessionPayload {
  return {
    room_id: props.roomId,
    performed_at: performedAt.value ? new Date(performedAt.value).toISOString() : null,
    note: note.value.trim() || null,
    items: rows.value
      .filter((r) => r.done)
      .map((r) => ({ machine_id: r.id, note: r.note.trim() || null })),
    // A poste left out after a refusal is not sent at all, its note kept.
    skipped: rows.value
      .filter((r) => !r.done && !r.removed && r.note.trim())
      .map((r) => ({ machine_id: r.id, note: r.note.trim() })),
  };
}

function newJob(): { payload: SessionPayload; progress: SessionProgress } {
  const payload = payloadOf();
  return { payload, progress: sessionProgress(payload) };
}

/**
 * Leave the postes the server refused out of what remains, and send it — or,
 * the part that creates the visit refused, out of the form, sent anew.
 */
async function dropRefused() {
  if (!refused.value) return;
  const ids = refused.value.ids;
  if (pending.value) dropUnsentLines(pending.value.payload, pending.value.progress, ids);
  for (const row of rows.value) {
    if (ids.includes(row.id)) {
      row.done = false;
      row.removed = true;
    }
  }
  await submit();
}

async function submit() {
  if (saving.value) return;
  const job = pending.value ?? newJob();
  saving.value = true;
  refused.value = null;
  try {
    // A room of any size is one visit: sent in parts under the server's cap.
    await recordSessionInParts(job.payload, job.progress);
    const done = job.payload.items.length;
    $q.notify({
      type: 'positive',
      message: done
        ? t('maintenance.session.recorded', { count: done }, done)
        : t('maintenance.session.recordedNothingDone'),
    });
    close();
    notifyTasksChanged();
    emit('recorded');
  } catch (e) {
    // Some parts went through: keep them, and offer to send the rest. So
    // does a first part left without an answer — it may be recorded, and
    // sent again it returns the visit it created. Only a first part the
    // server refused is known to have written nothing: the form is the
    // user's again, to correct — and the postes it names offered for removal.
    pending.value = job.progress.sessionId || !isRefusal(e) ? job : null;
    refused.value = refusedMachines(e);
    $q.notify({
      type: 'negative',
      message: apiErrorMessage(e, t('maintenance.session.saveFailed')),
    });
  } finally {
    saving.value = false;
  }
}
</script>

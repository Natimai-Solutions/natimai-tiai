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
         buttons (audit U23). -->
    <q-card
      :class="small ? 'column no-wrap' : ''"
      :style="small ? undefined : 'width: 720px; max-width: 95vw'"
      data-test="session-card"
    >
      <q-card-section class="text-h6"
        >Maintenance{{ roomName ? ` — ${roomName}` : '' }}</q-card-section
      >
      <q-form :class="small ? 'col column no-wrap' : ''" @submit="submit">
        <q-card-section class="q-gutter-md" :class="small ? 'col scroll' : ''">
          <q-banner v-if="pending" rounded class="surface-blue" data-test="session-pending">
            Séance enregistrée en partie : {{ pending.progress.sent }} poste(s) sur
            {{ pending.progress.total }}. « Reprendre l'envoi » envoie le reste dans la même séance.
          </q-banner>
          <div class="row q-col-gutter-md">
            <q-input
              v-model="performedAt"
              label="Date"
              outlined
              dense
              type="datetime-local"
              stack-label
              class="col-12 col-sm-5"
              hint="Antidater est permis"
              :disable="!!pending"
            />
            <q-input
              v-model="note"
              label="Observation générale"
              outlined
              dense
              autogrow
              type="textarea"
              maxlength="5000"
              class="col-12 col-sm-7"
              :disable="!!pending"
            />
          </div>
          <!-- A phone gets a list: the name, then its note below at full
               width, rather than a table whose note column sits off screen. -->
          <q-list v-if="small" bordered separator data-test="session-rows">
            <q-item>
              <q-item-section side>
                <q-checkbox
                  :model-value="allDone"
                  aria-label="Tout cocher ou tout décocher"
                  :disable="!!pending"
                  @update:model-value="(v) => toggleAll(v === true)"
                />
              </q-item-section>
              <q-item-section class="text-weight-medium">Tout cocher</q-item-section>
            </q-item>
            <q-item v-for="row in rows" :key="row.id" class="column q-py-sm">
              <div class="row items-center no-wrap">
                <q-checkbox
                  v-model="row.done"
                  :aria-label="`${row.hostname} : fait`"
                  :disable="!!pending"
                />
                <div class="col q-ml-sm" style="min-width: 0; overflow-wrap: anywhere">
                  {{ row.hostname }}
                  <div v-if="row.hint" class="text-caption text-muted">{{ row.hint }}</div>
                </div>
              </div>
              <q-input
                v-model="row.note"
                :aria-label="`Note pour ${row.hostname}`"
                dense
                outlined
                :placeholder="row.done ? 'Observation (facultatif)' : 'Pourquoi non fait'"
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
                    aria-label="Tout cocher ou tout décocher"
                    :disable="!!pending"
                    @update:model-value="(v) => toggleAll(v === true)"
                  />
                </th>
                <th class="text-left">Poste</th>
                <th class="text-left">Observation sur ce poste</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in rows" :key="row.id">
                <td>
                  <q-checkbox
                    v-model="row.done"
                    dense
                    :aria-label="`${row.hostname} : fait`"
                    :disable="!!pending"
                  />
                </td>
                <td>
                  {{ row.hostname }}
                  <div v-if="row.hint" class="text-caption text-muted">{{ row.hint }}</div>
                </td>
                <td>
                  <!-- Open on an unticked poste too: why it was not done is
                       worth keeping, in its own journal (audit U20). -->
                  <q-input
                    v-model="row.note"
                    :aria-label="`Note pour ${row.hostname}`"
                    dense
                    borderless
                    :placeholder="row.done ? '—' : 'Pourquoi non fait (facultatif)'"
                    maxlength="5000"
                    :disable="!!pending"
                  />
                </td>
              </tr>
            </tbody>
          </q-markup-table>
          <div class="text-caption text-muted">
            {{ doneCount }} poste(s) coché(s) : chacun reçoit une ligne « Maintenance » dans son
            historique et repart pour un cycle. Un poste décoché avec une observation reçoit une
            ligne « Maintenance non faite », sans changer son échéance.
          </div>
          <div v-if="!doneCount" class="text-caption text-warn" data-test="session-nothing-done">
            Aucun poste coché : la séance est enregistrée sans maintenance, à condition de dire
            pourquoi — une observation générale ou la note d'un poste non fait.
          </div>
        </q-card-section>
        <q-separator v-if="small" />
        <q-card-actions align="right" class="q-px-md q-pb-md" :class="small ? 'q-pt-md' : ''">
          <q-btn flat label="Annuler" @click="cancel" />
          <q-btn
            type="submit"
            color="primary"
            :label="pending ? 'Reprendre l\'envoi' : 'Enregistrer'"
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
  recordSessionInParts,
  sessionProgress,
  type SessionPayload,
  type SessionProgress,
} from 'src/services/maintenance';
import { apiErrorMessage } from 'src/services/errors';

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
const rows = ref<
  { id: string; hostname: string; hint: string | undefined; done: boolean; note: string }[]
>([]);
// A visit larger than one request whose sending stopped half-way: what was
// sent, frozen, and how far it got — « Reprendre l'envoi » sends the rest
// into the same visit rather than a second one.
const pending = ref<{ payload: SessionPayload; progress: SessionProgress } | null>(null);

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
    rows.value.some((r) => !r.done && r.note.trim()) ||
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
    hint: m.hint,
    done: m.preselect ?? true,
    note: '',
  }));
  pending.value = null;
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
  if (pending.value) {
    // Part of the visit is recorded already: closing keeps that part, and
    // the page must show it.
    $q.dialog({
      title: "Abandonner l'envoi ?",
      message:
        `${pending.value.progress.sent} poste(s) sur ${pending.value.progress.total} sont ` +
        'enregistrés dans la séance ; les autres ne le seront pas.',
      cancel: { flat: true, noCaps: true, label: "Reprendre l'envoi" },
      ok: { flat: true, noCaps: true, label: 'Abandonner', color: 'negative' },
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
    title: 'Abandonner la saisie ?',
    message: 'Les notes et les postes cochés ou décochés seront perdus.',
    cancel: { flat: true, noCaps: true, label: 'Continuer la saisie' },
    ok: { flat: true, noCaps: true, label: 'Abandonner', color: 'negative' },
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
    skipped: rows.value
      .filter((r) => !r.done && r.note.trim())
      .map((r) => ({ machine_id: r.id, note: r.note.trim() })),
  };
}

async function submit() {
  const job = pending.value ?? { payload: payloadOf(), progress: sessionProgress(payloadOf()) };
  const done = job.payload.items.length;
  saving.value = true;
  try {
    // A room of any size is one visit: sent in parts under the server's cap.
    await recordSessionInParts(job.payload, job.progress);
    $q.notify({
      type: 'positive',
      message: done
        ? `Maintenance enregistrée sur ${done} poste(s)`
        : 'Séance enregistrée : aucun poste fait',
    });
    close();
    notifyTasksChanged();
    emit('recorded');
  } catch (e) {
    // Some parts went through: keep them, and offer to send the rest.
    if (job.progress.sessionId) pending.value = job;
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'Enregistrement impossible') });
  } finally {
    saving.value = false;
  }
}
</script>

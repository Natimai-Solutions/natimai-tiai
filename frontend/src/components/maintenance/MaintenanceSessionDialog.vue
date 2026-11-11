<template>
  <!-- Recording a visit: the date, a global note, and the postes done —
       each with its own note. A poste absent or off that day is unticked
       rather than lied about. -->
  <!-- Persistent: a note per poste is minutes of typing, and Échap or a
       click beside the card must not throw it away (audit U14). -->
  <q-dialog
    :model-value="modelValue"
    persistent
    @update:model-value="(v) => emit('update:modelValue', v)"
    @keydown.esc="cancel"
  >
    <!-- Échap is ours to handle: a persistent dialog only shakes. -->
    <q-card style="width: 720px; max-width: 95vw">
      <q-card-section class="text-h6"
        >Maintenance{{ roomName ? ` — ${roomName}` : '' }}</q-card-section
      >
      <q-form @submit="submit">
        <q-card-section class="q-gutter-md">
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
            />
          </div>
          <q-markup-table flat bordered dense>
            <thead>
              <tr>
                <th style="width: 40px">
                  <q-checkbox
                    :model-value="allDone"
                    dense
                    @update:model-value="(v) => toggleAll(v === true)"
                  />
                </th>
                <th class="text-left">Poste</th>
                <th class="text-left">Observation sur ce poste</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in rows" :key="row.id">
                <td><q-checkbox v-model="row.done" dense /></td>
                <td>
                  {{ row.hostname }}
                  <div v-if="row.hint" class="text-caption text-muted">{{ row.hint }}</div>
                </td>
                <td>
                  <q-input
                    v-model="row.note"
                    :aria-label="`Note pour ${row.hostname}`"
                    dense
                    borderless
                    placeholder="—"
                    maxlength="5000"
                    :disable="!row.done"
                  />
                </td>
              </tr>
            </tbody>
          </q-markup-table>
          <div class="text-caption text-muted">
            {{ doneCount }} poste(s) coché(s) : chacun reçoit une ligne « Maintenance » dans son
            historique et repart pour un cycle.
          </div>
        </q-card-section>
        <q-card-actions align="right" class="q-px-md q-pb-md">
          <q-btn flat label="Annuler" @click="cancel" />
          <q-btn
            type="submit"
            color="primary"
            label="Enregistrer"
            :disable="!doneCount"
            :loading="saving"
          />
        </q-card-actions>
      </q-form>
    </q-card>
  </q-dialog>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { useQuasar } from 'quasar';
import { recordSession } from 'src/services/maintenance';
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
const saving = ref(false);
const note = ref('');
const performedAt = ref('');
const rows = ref<
  { id: string; hostname: string; hint: string | undefined; done: boolean; note: string }[]
>([]);

const doneCount = computed(() => rows.value.filter((r) => r.done).length);
const allDone = computed<boolean | null>(() =>
  doneCount.value === 0 ? false : doneCount.value === rows.value.length ? true : null,
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

async function submit() {
  saving.value = true;
  try {
    await recordSession({
      room_id: props.roomId,
      performed_at: performedAt.value ? new Date(performedAt.value).toISOString() : null,
      note: note.value.trim() || null,
      items: rows.value
        .filter((r) => r.done)
        .map((r) => ({ machine_id: r.id, note: r.note.trim() || null })),
    });
    $q.notify({
      type: 'positive',
      message: `Maintenance enregistrée sur ${doneCount.value} poste(s)`,
    });
    close();
    emit('recorded');
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'Enregistrement impossible') });
  } finally {
    saving.value = false;
  }
}
</script>

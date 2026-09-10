<template>
  <!-- Recording a visit: the date, a global note, and the postes done —
       each with its own note. A poste absent or off that day is unticked
       rather than lied about. -->
  <q-dialog :model-value="modelValue" @update:model-value="(v) => emit('update:modelValue', v)">
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
                  <div v-if="row.hint" class="text-caption text-grey">{{ row.hint }}</div>
                </td>
                <td>
                  <q-input
                    v-model="row.note"
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
          <div class="text-caption text-grey">
            {{ doneCount }} poste(s) coché(s) : chacun reçoit une ligne « Maintenance » dans son
            historique et repart pour un cycle.
          </div>
        </q-card-section>
        <q-card-actions align="right" class="q-px-md q-pb-md">
          <q-btn v-close-popup flat label="Annuler" />
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

watch(
  () => props.modelValue,
  (open) => {
    if (!open) return;
    note.value = '';
    performedAt.value = toLocalInput(new Date());
    rows.value = props.machines.map((m) => ({
      id: m.id,
      hostname: m.hostname,
      hint: m.hint,
      done: true,
      note: '',
    }));
  },
);

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
    emit('update:modelValue', false);
    emit('recorded');
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'Enregistrement impossible') });
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <q-card flat bordered class="q-mt-md">
    <q-card-section class="row items-center text-subtitle1">
      Historique des interventions
      <q-space />
      <q-btn
        v-if="canWrite"
        dense
        color="primary"
        icon="add"
        label="Ajouter une intervention"
        @click="openCreate"
      />
    </q-card-section>
    <q-separator />

    <q-card-section v-if="!items.length && !loading" class="text-grey">
      Aucune intervention enregistrée sur ce poste.
    </q-card-section>

    <!-- A timeline rather than a table: a journal is read top to bottom,
         and a note is a paragraph, not a cell. -->
    <q-list v-else separator>
      <q-item v-for="item in items" :key="item.id" class="q-py-md">
        <q-item-section avatar top>
          <q-avatar :color="interventionKindColor(item.kind)" text-color="white" size="36px">
            <q-icon :name="interventionKindIcon(item.kind)" size="20px" />
          </q-avatar>
        </q-item-section>
        <q-item-section>
          <q-item-label>
            <span class="text-weight-medium">{{ interventionKindLabel(item.kind) }}</span>
            <span v-if="item.title"> — {{ item.title }}</span>
          </q-item-label>
          <q-item-label caption>
            {{ formatDateTime(item.performed_at) }} · {{ item.performed_by }}
            <span v-if="wasEdited(item)"> · modifié</span>
          </q-item-label>
          <q-item-label v-if="item.note" class="q-mt-xs" style="white-space: pre-line">
            {{ item.note }}
          </q-item-label>
        </q-item-section>
        <q-item-section v-if="canWrite" side top>
          <q-btn flat dense round icon="more_vert" :aria-label="`Actions sur l'intervention`">
            <q-menu>
              <q-list style="min-width: 160px">
                <q-item v-close-popup clickable @click="openEdit(item)">
                  <q-item-section avatar><q-icon name="edit" /></q-item-section>
                  <q-item-section>Modifier</q-item-section>
                </q-item>
                <q-item v-close-popup clickable class="text-negative" @click="confirmDelete(item)">
                  <q-item-section avatar><q-icon name="delete" /></q-item-section>
                  <q-item-section>Supprimer</q-item-section>
                </q-item>
              </q-list>
            </q-menu>
          </q-btn>
        </q-item-section>
      </q-item>
    </q-list>

    <q-card-section v-if="total > items.length" class="row justify-center q-pt-none">
      <q-btn flat dense label="Afficher plus" :loading="loading" @click="emit('more')" />
    </q-card-section>

    <q-dialog v-model="formOpen">
      <q-card style="width: 520px; max-width: 95vw">
        <q-card-section class="text-h6">
          {{ editing ? "Modifier l'intervention" : 'Nouvelle intervention' }}
        </q-card-section>
        <q-form @submit="submit">
          <q-card-section class="q-gutter-md">
            <q-select
              v-model="form.kind"
              :options="kindOptions"
              emit-value
              map-options
              label="Type"
              outlined
              dense
            />
            <q-input v-model="form.title" label="Titre" outlined dense maxlength="200" autofocus />
            <q-input
              v-model="form.note"
              label="Observations"
              outlined
              dense
              autogrow
              maxlength="5000"
              type="textarea"
            />
            <!-- When it happened, not when it is typed: a journal can start
                 before the console did. -->
            <q-input
              v-model="form.performed_at"
              label="Date"
              outlined
              dense
              type="datetime-local"
              stack-label
              hint="Laisser tel quel pour maintenant ; antidater est permis"
            />
          </q-card-section>
          <q-card-actions align="right" class="q-px-md q-pb-md">
            <q-btn v-close-popup flat label="Annuler" />
            <q-btn type="submit" color="primary" label="Enregistrer" :loading="saving" />
          </q-card-actions>
        </q-form>
      </q-card>
    </q-dialog>
  </q-card>
</template>

<script setup lang="ts">
import { reactive, ref } from 'vue';
import { useQuasar } from 'quasar';
import {
  createIntervention,
  deleteIntervention,
  INTERVENTION_KINDS,
  interventionKindColor,
  interventionKindIcon,
  interventionKindLabel,
  updateIntervention,
  type Intervention,
  type InterventionKind,
} from 'src/services/interventions';
import { apiErrorMessage } from 'src/services/errors';
import { formatDateTime } from 'src/utils/format';

const props = defineProps<{
  machineId: string;
  items: Intervention[];
  total: number;
  loading: boolean;
  canWrite: boolean;
}>();
const emit = defineEmits<{ (e: 'changed'): void; (e: 'more'): void }>();

const $q = useQuasar();
const formOpen = ref(false);
const saving = ref(false);
const editing = ref<Intervention | null>(null);
const form = reactive({
  kind: 'incident' as InterventionKind,
  title: '',
  note: '',
  performed_at: '',
});

const kindOptions = INTERVENTION_KINDS.map((k) => ({ label: k.label, value: k.value }));

/** Edited after the fact — not the same instant written twice at creation. */
function wasEdited(item: Intervention): boolean {
  return new Date(item.updated_at).getTime() - new Date(item.created_at).getTime() > 1000;
}

/** An ISO instant as the datetime-local input wants it, in local time. */
function toLocalInput(iso: string): string {
  const d = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function openCreate() {
  editing.value = null;
  Object.assign(form, {
    kind: 'incident',
    title: '',
    note: '',
    performed_at: toLocalInput(new Date().toISOString()),
  });
  formOpen.value = true;
}

function openEdit(item: Intervention) {
  editing.value = item;
  Object.assign(form, {
    kind: item.kind as InterventionKind,
    title: item.title ?? '',
    note: item.note ?? '',
    performed_at: toLocalInput(item.performed_at),
  });
  formOpen.value = true;
}

async function submit() {
  saving.value = true;
  try {
    const performedAt = form.performed_at ? new Date(form.performed_at).toISOString() : null;
    const payload = {
      kind: form.kind,
      title: form.title.trim() || null,
      note: form.note.trim() || null,
      performed_at: performedAt,
    };
    if (editing.value) {
      await updateIntervention(editing.value.id, payload);
      $q.notify({ type: 'positive', message: 'Intervention mise à jour' });
    } else {
      await createIntervention(props.machineId, payload);
      $q.notify({ type: 'positive', message: 'Intervention enregistrée' });
    }
    formOpen.value = false;
    emit('changed');
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'Enregistrement impossible') });
  } finally {
    saving.value = false;
  }
}

function confirmDelete(item: Intervention) {
  $q.dialog({
    title: "Supprimer l'intervention",
    message: `Supprimer « ${interventionKindLabel(item.kind)}${item.title ? ` — ${item.title}` : ''} » du ${formatDateTime(item.performed_at)} ? La suppression est tracée dans le journal d'audit.`,
    cancel: true,
    ok: { label: 'Supprimer', color: 'negative' },
  }).onOk(() => {
    void (async () => {
      try {
        await deleteIntervention(item.id);
        $q.notify({ type: 'positive', message: 'Intervention supprimée' });
        emit('changed');
      } catch (e) {
        $q.notify({ type: 'negative', message: apiErrorMessage(e, 'Suppression impossible') });
      }
    })();
  });
}
</script>

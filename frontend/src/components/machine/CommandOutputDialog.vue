<template>
  <q-dialog v-model="open">
    <q-card style="min-width: 480px; max-width: 90vw">
      <q-card-section class="text-h6">
        {{ kind === 'error' ? "Détail de l'erreur" : 'Résultat de la commande' }}
      </q-card-section>
      <q-card-section v-if="command" class="q-pt-none text-caption text-muted">
        {{ commandTypeLabel(command.type) }} — terminée le
        {{ formatDateTime(command.finished_at) }}
      </q-card-section>
      <q-separator />
      <q-card-section>
        <pre class="command-output">{{ text }}</pre>
      </q-card-section>
      <q-card-actions align="right">
        <q-btn flat icon="content_copy" label="Copier" @click="copy" />
        <q-btn v-close-popup flat label="Fermer" />
      </q-card-actions>
    </q-card>
  </q-dialog>
</template>

<script setup lang="ts">
import { computed } from 'vue';
import { useQuasar } from 'quasar';
import { commandTypeLabel, type Command } from 'src/services/commands';
import { formatDateTime } from 'src/utils/format';

const props = defineProps<{ command: Command | null; kind: 'output' | 'error' }>();

const open = defineModel<boolean>({ required: true });

const $q = useQuasar();

const text = computed(() =>
  props.kind === 'error' ? (props.command?.error ?? '') : (props.command?.result_output ?? ''),
);

// An ipconfig /all or a gpresult dump is meant to be pasted into a ticket, and
// selecting it out of a scrolling <pre> is a chore.
async function copy() {
  try {
    await navigator.clipboard.writeText(text.value);
    $q.notify({ type: 'positive', message: 'Copié dans le presse-papiers' });
  } catch {
    $q.notify({ type: 'negative', message: 'Copie impossible' });
  }
}
</script>

<style scoped>
.command-output {
  margin: 0;
  max-height: 50vh;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-word;
  font-size: 12px;
}
</style>

<template>
  <q-dialog v-model="open">
    <!-- 480 px at least on a desktop, as wide as the output asks up to the
         95vw cap — and never wider than a 375 px phone (audit U11), as the
         merge dialog. -->
    <q-card class="command-output-card">
      <q-card-section class="text-h6">
        {{ kind === 'error' ? t('commands.output.errorTitle') : t('commands.output.outputTitle') }}
      </q-card-section>
      <q-card-section v-if="command" class="q-pt-none text-caption text-muted">
        {{ t('commands.output.finished', { label: commandTypeLabel(command.type) }) }}
        {{ formatDateTime(command.finished_at) }}
      </q-card-section>
      <q-separator />
      <q-card-section>
        <pre class="command-output">{{ text }}</pre>
      </q-card-section>
      <q-card-actions align="right">
        <q-btn flat icon="content_copy" :label="t('commands.output.copy')" @click="copy" />
        <q-btn v-close-popup flat :label="t('commands.output.close')" />
      </q-card-actions>
    </q-card>
  </q-dialog>
</template>

<script setup lang="ts">
import { computed } from 'vue';
import { useQuasar } from 'quasar';
import { t } from 'src/i18n';
import { commandResultText, commandTypeLabel, type Command } from 'src/services/commands';
import { formatDateTime } from 'src/utils/format';
import { notify } from 'src/utils/notify';

const props = defineProps<{ command: Command | null; kind: 'output' | 'error' }>();

const open = defineModel<boolean>({ required: true });

const $q = useQuasar();

// Worded from the verdict's code in the language shown, else the stored
// text: a tool's output, a row stored before codes, a newer code.
const text = computed(() => (props.command ? commandResultText(props.command, props.kind) : ''));

// An ipconfig /all or a gpresult dump is meant to be pasted into a ticket, and
// selecting it out of a scrolling <pre> is a chore.
async function copy() {
  try {
    await navigator.clipboard.writeText(text.value);
    notify($q, () => ({ type: 'positive', message: t('commands.output.copied') }));
  } catch {
    notify($q, () => ({ type: 'negative', message: t('commands.output.copyFailed') }));
  }
}
</script>

<style scoped>
.command-output-card {
  min-width: min(480px, 95vw);
  max-width: 95vw;
}
.command-output {
  margin: 0;
  max-height: 50vh;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-word;
  font-size: 12px;
}
</style>

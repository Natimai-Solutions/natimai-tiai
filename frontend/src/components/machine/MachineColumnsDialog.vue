<template>
  <q-dialog v-model="open" @before-show="onOpen">
    <q-card style="width: 460px; max-width: 95vw">
      <q-card-section class="row items-center q-pb-none">
        <div>
          <div class="text-h6">Colonnes de la liste</div>
          <div class="text-caption text-grey">
            Cochez les colonnes à afficher et ordonnez-les. Le choix est enregistré sur votre
            compte.
          </div>
        </div>
      </q-card-section>

      <q-card-section>
        <q-list dense bordered separator class="rounded-borders">
          <q-item v-for="(entry, index) in entries" :key="entry.key">
            <q-item-section side>
              <q-checkbox
                v-model="entry.visible"
                dense
                :disable="entry.key === MANDATORY_MACHINE_COLUMN"
              />
            </q-item-section>
            <q-item-section :class="{ 'text-grey': !entry.visible }">
              {{ entry.label }}
            </q-item-section>
            <q-item-section side>
              <div class="row no-wrap">
                <q-btn
                  flat
                  dense
                  round
                  size="sm"
                  icon="arrow_upward"
                  :disable="index <= 1"
                  @click="move(index, -1)"
                />
                <q-btn
                  flat
                  dense
                  round
                  size="sm"
                  icon="arrow_downward"
                  :disable="index === 0 || index === entries.length - 1"
                  @click="move(index, 1)"
                />
              </div>
            </q-item-section>
          </q-item>
        </q-list>
      </q-card-section>

      <q-card-actions align="right" class="q-px-md q-pb-md">
        <q-btn flat no-caps label="Par défaut" @click="resetToDefaults" />
        <q-space />
        <q-btn v-close-popup flat no-caps label="Annuler" />
        <q-btn
          color="primary"
          no-caps
          label="Appliquer"
          :loading="saving"
          :disable="!visibleKeys.length"
          @click="apply"
        />
      </q-card-actions>
    </q-card>
  </q-dialog>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue';
import {
  DEFAULT_MACHINE_COLUMNS,
  MACHINE_COLUMN_KEYS,
  MANDATORY_MACHINE_COLUMN,
  type MachineColumnKey,
} from 'src/utils/machineColumns';

/**
 * The machine list's column picker: one ordered list, a checkbox per column,
 * arrows to reorder. The name column is pinned first — it carries the link to
 * the fiche — and the rest is the reader's. Hidden columns keep their place
 * in the order, so unhiding one puts it back where it was.
 */
const props = defineProps<{
  /** The columns currently shown, in order. */
  columns: MachineColumnKey[];
  /** Column labels, as the table shows them. */
  labels: Record<string, string>;
  /** Persists the layout; the dialog closes once it resolves. */
  save: (columns: MachineColumnKey[]) => Promise<void>;
}>();

const open = defineModel<boolean>('open', { required: true });

interface Entry {
  key: MachineColumnKey;
  label: string;
  visible: boolean;
}

const entries = ref<Entry[]>([]);
const saving = ref(false);

const visibleKeys = computed(() => entries.value.filter((e) => e.visible).map((e) => e.key));

/** The list to edit: the shown columns first, in their order, then the hidden
 * ones in catalogue order — so a hidden column is found where one expects it. */
function build(shown: readonly MachineColumnKey[]) {
  const hidden = MACHINE_COLUMN_KEYS.filter((key) => !shown.includes(key));
  entries.value = [...shown, ...hidden].map((key) => ({
    key,
    label: props.labels[key] ?? key,
    visible: shown.includes(key),
  }));
}

function onOpen() {
  build(props.columns);
}

function resetToDefaults() {
  build(DEFAULT_MACHINE_COLUMNS);
}

function move(index: number, delta: number) {
  const target = index + delta;
  // The name column stays at the top: nothing moves onto or over it.
  if (index === 0 || target < 1 || target >= entries.value.length) return;
  const next = [...entries.value];
  const [item] = next.splice(index, 1);
  next.splice(target, 0, item!);
  entries.value = next;
}

async function apply() {
  saving.value = true;
  try {
    await props.save(visibleKeys.value);
    open.value = false;
  } finally {
    saving.value = false;
  }
}
</script>

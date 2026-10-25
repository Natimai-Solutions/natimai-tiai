<template>
  <q-dialog v-model="open" @before-show="onOpen">
    <q-card style="width: 900px; max-width: 95vw">
      <q-card-section class="row items-center q-pb-none">
        <div>
          <div class="text-h6">Exporter le parc</div>
          <div class="text-caption text-muted">
            {{ countLabel }} — les filtres de la liste s'appliquent, pas la pagination.
          </div>
        </div>
        <q-space />
        <q-btn-toggle
          v-model="format"
          dense
          no-caps
          unelevated
          toggle-color="primary"
          :options="formatOptions"
        />
      </q-card-section>

      <q-card-section v-if="loadError" class="text-negative">
        {{ loadError }}
      </q-card-section>

      <q-card-section v-else class="row q-col-gutter-md">
        <!-- Left: what can be exported, by section. A click adds; the chosen
             ones stay listed but greyed, so the section still reads as a whole. -->
        <div class="col-12 col-sm-6">
          <div class="text-subtitle2 q-mb-xs">Colonnes disponibles</div>
          <q-input
            v-model="filter"
            dense
            outlined
            clearable
            placeholder="Rechercher une colonne…"
            class="q-mb-sm"
          >
            <template #prepend><q-icon name="search" /></template>
          </q-input>
          <q-scroll-area style="height: 360px" class="rounded-borders bordered-list">
            <q-list dense>
              <template v-for="section in availableSections" :key="section.label">
                <q-item-label header class="q-py-xs">{{ section.label }}</q-item-label>
                <q-item
                  v-for="column in section.columns"
                  :key="column.key"
                  clickable
                  :disable="isSelected(column.key)"
                  @click="add(column.key)"
                >
                  <q-item-section>{{ column.label }}</q-item-section>
                  <q-item-section side>
                    <q-icon :name="isSelected(column.key) ? 'check' : 'add'" size="18px" />
                  </q-item-section>
                </q-item>
              </template>
              <q-item v-if="!availableSections.length">
                <q-item-section class="text-muted">Aucune colonne ne correspond.</q-item-section>
              </q-item>
            </q-list>
          </q-scroll-area>
        </div>

        <!-- Right: what will be exported, in the order it will appear. -->
        <div class="col-12 col-sm-6">
          <div class="row items-center q-mb-xs">
            <div class="text-subtitle2">Colonnes exportées ({{ selected.length }})</div>
            <q-space />
            <q-btn flat dense no-caps size="sm" label="Par défaut" @click="resetToDefaults" />
            <q-btn
              flat
              dense
              no-caps
              size="sm"
              label="Tout retirer"
              :disable="!selected.length"
              @click="selected = []"
            />
          </div>
          <q-scroll-area style="height: 404px" class="rounded-borders bordered-list">
            <q-list dense>
              <q-item v-for="(key, index) in selected" :key="key">
                <q-item-section>{{ labelOf(key) }}</q-item-section>
                <q-item-section side>
                  <div class="row no-wrap">
                    <q-btn
                      flat
                      dense
                      round
                      size="sm"
                      icon="arrow_upward"
                      :disable="index === 0"
                      @click="move(index, -1)"
                    />
                    <q-btn
                      flat
                      dense
                      round
                      size="sm"
                      icon="arrow_downward"
                      :disable="index === selected.length - 1"
                      @click="move(index, 1)"
                    />
                    <q-btn flat dense round size="sm" icon="close" @click="remove(index)" />
                  </div>
                </q-item-section>
              </q-item>
              <q-item v-if="!selected.length">
                <q-item-section class="text-muted">
                  Aucune colonne : choisissez-en à gauche, ou revenez aux colonnes par défaut.
                </q-item-section>
              </q-item>
            </q-list>
          </q-scroll-area>
        </div>
      </q-card-section>

      <q-card-actions align="right">
        <q-btn v-close-popup flat no-caps label="Annuler" />
        <q-btn
          color="primary"
          no-caps
          icon="download"
          :label="exportLabel"
          :loading="exporting"
          :disable="!selected.length || !!loadError"
          @click="doExport"
        />
      </q-card-actions>
    </q-card>
  </q-dialog>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue';
import { useQuasar } from 'quasar';
import {
  exportMachines,
  listExportColumns,
  type ExportColumn,
  type ExportFormat,
  type ListMachinesParams,
} from 'src/services/machines';
import { apiErrorMessage } from 'src/services/errors';
import { downloadBlob } from 'src/utils/format';

/**
 * The fleet export's column picker — the way Odoo's export dialog works: a
 * default set on the right, the whole catalogue on the left, and the reader
 * moves columns across and reorders them. The choice is remembered in the
 * browser, since the columns a meeting wants are the same from one week to
 * the next.
 */
const props = defineProps<{
  /** The list's current filters — what bounds the export. */
  params: ListMachinesParams;
  /** How many rows the filters match, for the caption. */
  count: number;
}>();

const open = defineModel<boolean>({ required: true });

const $q = useQuasar();

// Remembered choice. One key, one small JSON: the columns and the format.
const STORAGE_KEY = 'tiai.machineExport';

const formatOptions: { label: string; value: ExportFormat }[] = [
  { label: 'Excel (.xlsx)', value: 'xlsx' },
  { label: 'CSV', value: 'csv' },
];

const catalogue = ref<ExportColumn[]>([]);
const loadError = ref('');
const selected = ref<string[]>([]);
const format = ref<ExportFormat>('xlsx');
const filter = ref('');
const exporting = ref(false);

const byKey = computed(() => new Map(catalogue.value.map((c) => [c.key, c])));

const countLabel = computed(() =>
  props.count === 1 ? '1 poste' : `${props.count.toLocaleString('fr-FR')} postes`,
);

const exportLabel = computed(() =>
  format.value === 'xlsx' ? 'Exporter en Excel' : 'Exporter en CSV',
);

/** The catalogue in sections, narrowed by the search box. */
const availableSections = computed<{ label: string; columns: ExportColumn[] }[]>(() => {
  const needle = filter.value.trim().toLocaleLowerCase('fr-FR');
  const sections = new Map<string, ExportColumn[]>();
  for (const column of catalogue.value) {
    if (needle && !column.label.toLocaleLowerCase('fr-FR').includes(needle)) continue;
    const list = sections.get(column.group_label) ?? [];
    list.push(column);
    sections.set(column.group_label, list);
  }
  return [...sections.entries()].map(([label, columns]) => ({ label, columns }));
});

function isSelected(key: string): boolean {
  return selected.value.includes(key);
}

function labelOf(key: string): string {
  return byKey.value.get(key)?.label ?? key;
}

function add(key: string) {
  if (!isSelected(key)) selected.value = [...selected.value, key];
}

function remove(index: number) {
  selected.value = selected.value.filter((_, i) => i !== index);
}

function move(index: number, delta: number) {
  const target = index + delta;
  if (target < 0 || target >= selected.value.length) return;
  const next = [...selected.value];
  const [item] = next.splice(index, 1);
  next.splice(target, 0, item!);
  selected.value = next;
}

function resetToDefaults() {
  selected.value = catalogue.value.filter((c) => c.default).map((c) => c.key);
}

/** The remembered choice, if any and still valid against the catalogue. */
function restore() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return;
    const saved = JSON.parse(raw) as { columns?: unknown; format?: unknown };
    if (Array.isArray(saved.columns)) {
      const known = saved.columns.filter(
        (k): k is string => typeof k === 'string' && byKey.value.has(k),
      );
      if (known.length) selected.value = known;
    }
    if (saved.format === 'csv' || saved.format === 'xlsx') format.value = saved.format;
  } catch {
    // Storage unavailable or corrupt: the defaults are a fine answer.
  }
}

function remember() {
  try {
    localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({ columns: selected.value, format: format.value }),
    );
  } catch {
    // Same: forgetting is not an error worth a notification.
  }
}

async function onOpen() {
  filter.value = '';
  if (catalogue.value.length) return;
  try {
    catalogue.value = await listExportColumns();
    resetToDefaults();
    restore();
  } catch (e) {
    loadError.value = apiErrorMessage(e, 'Impossible de charger la liste des colonnes');
  }
}

async function doExport() {
  exporting.value = true;
  try {
    // The reader's own zone, so « Vu le » reads as the console showed it.
    const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
    const blob = await exportMachines(props.params, {
      format: format.value,
      columns: selected.value,
      ...(tz ? { tz } : {}),
    });
    downloadBlob(blob, `parc.${format.value}`);
    remember();
    open.value = false;
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, "Échec de l'export") });
  } finally {
    exporting.value = false;
  }
}
</script>

<style scoped>
.bordered-list {
  border: 1px solid var(--ti-border);
}
</style>

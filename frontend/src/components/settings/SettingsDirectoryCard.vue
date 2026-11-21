<template>
  <!-- Reading the directory (plan-lecture-annuaire.md): the mode, the domains
       read and by whom, the readers, the moves waiting for a confirmation. -->
  <q-card flat bordered style="max-width: 640px" class="q-mb-md" data-test="directory-card">
    <q-card-section class="text-subtitle1">
      {{ t('directory.title') }}
      <div class="text-caption text-muted">{{ t('directory.caption') }}</div>
    </q-card-section>
    <q-separator />
    <q-card-section v-if="loadError" class="text-negative">
      {{ t('directory.loadFailed') }}
    </q-card-section>
    <q-card-section v-else-if="state" class="q-gutter-sm">
      <div data-test="directory-mode">
        {{
          state.mode === 'relay'
            ? t('directory.mode.relay', {
                minutes: state.sync_minutes,
                hours: state.stale_hours,
              })
            : t('directory.mode.off')
        }}
      </div>
      <template v-if="state.mode === 'relay'">
        <div class="text-caption">
          {{
            t('directory.counts', {
              verified: state.status_counts.verified ?? 0,
              mismatch: state.status_counts.mismatch ?? 0,
              unknown: state.status_counts.unknown ?? 0,
              stale: state.status_counts.stale ?? 0,
            })
          }}
          <router-link
            v-if="state.status_counts.mismatch"
            :to="{ name: 'machines', query: { directory_status: 'mismatch' } }"
            class="q-ml-sm"
          >
            {{ t('directory.status.mismatch') }}
          </router-link>
        </div>
        <div v-if="!state.domains.length" class="text-muted">{{ t('directory.noDomain') }}</div>
        <q-list bordered separator class="rounded-borders">
          <q-item v-for="d in state.domains" :key="d.sid" :data-test="`domain-${d.netbios_name}`">
            <q-item-section>
              <q-item-label class="text-weight-medium">
                {{ d.name }} <span class="text-muted">({{ d.netbios_name }})</span>
              </q-item-label>
              <q-item-label caption>
                {{
                  d.last_read_at
                    ? t('directory.domain.lastRead', {
                        date: formatDateTime(d.last_read_at),
                        reader: d.last_reader ?? '—',
                        count: d.objects_read,
                      })
                    : t('directory.domain.neverRead')
                }}
              </q-item-label>
              <q-item-label caption>
                {{
                  d.readers.length
                    ? t('directory.domain.readers', { names: names(d.readers) })
                    : t('directory.domain.noReader')
                }}
              </q-item-label>
              <q-banner v-if="d.disagreement_at" dense rounded class="surface-red q-mt-sm">
                {{
                  t('directory.domain.disagreement', {
                    names: d.disagreement.map((o) => o.sam).join(', '),
                  })
                }}
              </q-banner>
              <div v-if="d.pending_count" class="q-mt-sm" data-test="pending">
                <q-banner dense rounded class="surface-orange">
                  {{
                    t('directory.domain.pending', {
                      count: d.pending_count,
                      limit: state.confirm_moves,
                    })
                  }}
                </q-banner>
                <ul class="q-my-xs text-caption">
                  <li v-for="m in d.pending_moves.slice(0, 10)" :key="m.machine_id">
                    {{
                      t('directory.domain.move', {
                        host: m.hostname ?? '—',
                        from: m.from_room ?? t('directory.domain.noRoom'),
                        to: m.to_room ?? t('directory.domain.noRoom'),
                      })
                    }}
                  </li>
                </ul>
                <div v-if="canWrite" class="row q-gutter-sm">
                  <q-btn
                    color="primary"
                    no-caps
                    dense
                    :label="t('directory.domain.confirm')"
                    :loading="busy"
                    @click="act(() => confirmMoves(d.sid))"
                  />
                  <q-btn
                    flat
                    no-caps
                    dense
                    :label="t('directory.domain.discard')"
                    :loading="busy"
                    @click="act(() => discardMoves(d.sid))"
                  />
                </div>
              </div>
            </q-item-section>
          </q-item>
        </q-list>
        <div v-if="state.readers_waiting.length" class="text-caption">
          {{ t('directory.waiting', { names: names(state.readers_waiting) }) }}
        </div>
        <div v-if="state.domains_without_reader.length" class="text-caption text-warn">
          {{ t('directory.withoutReader', { names: state.domains_without_reader.join(', ') }) }}
        </div>
      </template>
    </q-card-section>
  </q-card>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import { useQuasar } from 'quasar';
import { t } from 'src/i18n';
import {
  confirmMoves,
  discardMoves,
  getDirectoryState,
  type DirectoryReader,
  type DirectoryState,
} from 'src/services/directory';
import { apiErrorMessage } from 'src/services/errors';
import { useAuthStore } from 'src/stores/auth';
import { formatDateTime } from 'src/utils/format';
import { notify } from 'src/utils/notify';

const $q = useQuasar();
const auth = useAuthStore();
const canWrite = computed(() => auth.can('settings', 'write'));
const state = ref<DirectoryState | null>(null);
const loadError = ref<unknown>(null);
const busy = ref(false);

function names(readers: DirectoryReader[]): string {
  return readers.map((r) => r.hostname ?? r.id).join(', ');
}

async function load(): Promise<void> {
  try {
    state.value = await getDirectoryState();
    loadError.value = null;
  } catch (e) {
    loadError.value = e;
  }
}

async function act(run: () => Promise<unknown>): Promise<void> {
  busy.value = true;
  try {
    await run();
    notify($q, () => ({ type: 'positive', message: t('directory.domain.done') }));
    await load();
  } catch (e) {
    notify($q, () => ({
      type: 'negative',
      message: apiErrorMessage(e, t('directory.domain.failed')),
    }));
  } finally {
    busy.value = false;
  }
}

onMounted(load);
</script>

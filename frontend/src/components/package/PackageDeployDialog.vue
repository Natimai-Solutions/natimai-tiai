<template>
  <!-- Install or remove a package: on given postes (a fiche, a selection), or
       — opened from a package's page — on the parc or one site. -->
  <q-dialog :model-value="modelValue" @update:model-value="emit('update:modelValue', $event)">
    <q-card style="width: 520px; max-width: 95vw">
      <q-card-section class="text-h6">
        {{ action === 'install' ? 'Installer un logiciel' : 'Désinstaller un logiciel' }}
      </q-card-section>

      <q-card-section class="q-gutter-md">
        <q-btn-toggle
          v-model="action"
          no-caps
          unelevated
          toggle-color="primary"
          :options="[
            { label: 'Installer', value: 'install' },
            { label: 'Désinstaller', value: 'uninstall', disable: !canUninstall },
          ]"
        />

        <q-select
          v-if="!fixedPackage"
          v-model="chosenId"
          :options="packageOptions"
          :loading="loadingPackages"
          label="Paquet"
          outlined
          dense
          emit-value
          map-options
          :hint="packageOptions.length ? '' : 'Aucun paquet prêt — voir la page Paquets'"
        />

        <template v-if="!machineIds?.length">
          <q-option-group
            v-model="scope"
            :options="[
              { label: 'Tout le parc', value: 'all' },
              { label: 'Un emplacement', value: 'location' },
            ]"
            inline
          />
          <q-select
            v-if="scope === 'location'"
            v-model="location"
            :options="locations"
            label="Emplacement"
            outlined
            dense
          />
        </template>
        <div v-else class="text-body2">
          Sur {{ machineIds.length > 1 ? `${machineIds.length} postes` : 'ce poste' }}.
        </div>

        <q-banner v-if="chosen" dense class="surface-blue">
          {{ trustSentence(chosen) }}
        </q-banner>
      </q-card-section>

      <q-card-actions align="right" class="q-px-md q-pb-md">
        <q-btn v-close-popup flat no-caps label="Annuler" />
        <q-btn
          unelevated
          no-caps
          :color="action === 'uninstall' ? 'negative' : 'primary'"
          :label="okLabel"
          :disable="!ready"
          :loading="sending"
          @click="send"
        />
      </q-card-actions>
    </q-card>
  </q-dialog>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { useQuasar } from 'quasar';
import { bulkSendNotification } from 'src/services/commands';
import { apiErrorMessage } from 'src/services/errors';
import { listLocations, listMachines } from 'src/services/machines';
import {
  deployable,
  deployPackage,
  listPackages,
  trustMethod,
  type DeployTarget,
  type Package,
} from 'src/services/packages';

const props = defineProps<{
  modelValue: boolean;
  /** The postes to act on; absent, the dialog offers the parc or a site. */
  machineIds?: string[];
  /** Opened from a package's page: that package, no choice. */
  package?: Package | null;
  initialAction?: 'install' | 'uninstall';
}>();
const emit = defineEmits<{ 'update:modelValue': [boolean]; sent: [] }>();

const $q = useQuasar();
const action = ref<'install' | 'uninstall'>('install');
const packages = ref<Package[]>([]);
const loadingPackages = ref(false);
const chosenId = ref<string | null>(null);
const scope = ref<'all' | 'location'>('location');
const location = ref<string | null>(null);
const locations = ref<string[]>([]);
const sending = ref(false);

const fixedPackage = computed(() => props.package ?? null);
const chosen = computed<Package | null>(
  () => fixedPackage.value ?? packages.value.find((p) => p.id === chosenId.value) ?? null,
);
const packageOptions = computed(() =>
  packages.value
    .filter(deployable)
    .map((p) => ({ label: p.version ? `${p.name} ${p.version}` : p.name, value: p.id })),
);
const canUninstall = computed(
  () => !chosen.value || chosen.value.kind === 'winget' || !!chosen.value.uninstall_run,
);
const ready = computed(() => {
  if (!chosen.value || (action.value === 'install' && !deployable(chosen.value))) return false;
  // The dialog says no poste will run it: it does not send it either (audit B30).
  if (action.value === 'install' && trustMethod(chosen.value) === 'none') return false;
  if (action.value === 'uninstall' && !canUninstall.value) return false;
  if (!props.machineIds?.length && scope.value === 'location' && !location.value) return false;
  return true;
});
const okLabel = computed(() => {
  const verb = action.value === 'install' ? 'Installer' : 'Désinstaller';
  if (props.machineIds?.length)
    return props.machineIds.length > 1 ? `${verb} sur ${props.machineIds.length} postes` : verb;
  return scope.value === 'all'
    ? `${verb} sur tout le parc`
    : `${verb} sur ${location.value ?? '…'}`;
});

function trustSentence(p: Package): string {
  switch (trustMethod(p)) {
    case 'winget':
      return 'Paquet winget : seuls les postes où la GPO active winget (DeployWinget) l’installeront.';
    case 'signed':
      return 'Paquet signé : seuls les postes dont la GPO approuve ce certificat (DeploySigners) l’exécuteront.';
    case 'publisher':
      return `Non signé par l’administrateur : seuls les postes dont la GPO approuve l’éditeur « ${p.publisher_name} » (DeployPublishers) l’exécuteront.`;
    default:
      return 'Ni signé, ni lancé par un exécutable d’éditeur : aucun poste ne l’exécutera. Signez le paquet avant de le déployer.';
  }
}

watch(
  () => props.modelValue,
  async (open) => {
    if (!open) return;
    action.value = props.initialAction ?? 'install';
    chosenId.value = null;
    // Never the whole parc by default: the last choice must not carry over to
    // the next opening, an uninstall least of all (audit U04).
    scope.value = 'location';
    location.value = null;
    if (!props.machineIds?.length) {
      locations.value = (await listLocations().catch(() => [])).map((v) => v.name);
    }
    if (!fixedPackage.value) {
      loadingPackages.value = true;
      try {
        packages.value = await listPackages();
      } catch (e) {
        $q.notify({ type: 'negative', message: apiErrorMessage(e, 'Chargement impossible') });
      } finally {
        loadingPackages.value = false;
      }
    }
  },
);

/** How many postes the target names, for the confirmation. */
async function targetCount(): Promise<number | null> {
  if (props.machineIds?.length) return props.machineIds.length;
  try {
    const list = await listMachines(
      scope.value === 'all' ? { page_size: 1 } : { location: location.value ?? '', page_size: 1 },
    );
    return list.total;
  } catch {
    return null;
  }
}

/**
 * The whole parc, or any uninstall, is confirmed with the number of postes it
 * reaches — as the bulk actions of the machine list are (audit U04).
 */
async function confirmed(): Promise<boolean> {
  const wide = !props.machineIds?.length && scope.value === 'all';
  if (!wide && action.value !== 'uninstall') return true;
  const count = await targetCount();
  const where =
    count === null
      ? wide
        ? 'tout le parc'
        : 'les postes visés'
      : `${count} poste${count > 1 ? 's' : ''}${wide ? ' (tout le parc)' : ''}`;
  const verb = action.value === 'install' ? 'Installer' : 'Désinstaller';
  return new Promise((resolve) => {
    $q.dialog({
      title: `${verb} ${chosen.value?.name ?? ''}`,
      message: `${verb} sur ${where} ?`,
      cancel: { flat: true, noCaps: true, label: 'Annuler' },
      ok: {
        unelevated: true,
        noCaps: true,
        label: verb,
        color: action.value === 'uninstall' ? 'negative' : 'primary',
      },
      persistent: true,
    })
      .onOk(() => resolve(true))
      .onCancel(() => resolve(false));
  });
}

async function send() {
  if (!chosen.value) return;
  const target: DeployTarget = props.machineIds?.length
    ? { machine_ids: props.machineIds }
    : scope.value === 'all'
      ? { target_all: true }
      : { target_location: location.value ?? '' };
  if (!(await confirmed())) return;
  sending.value = true;
  try {
    const res = await deployPackage(chosen.value.id, action.value, target);
    $q.notify(bulkSendNotification(res));
    emit('update:modelValue', false);
    emit('sent');
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'Envoi impossible') });
  } finally {
    sending.value = false;
  }
}
</script>

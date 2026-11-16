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

        <!-- What the server would refuse the command for, said before it is
             sent: an uninstall is held back by fewer problems than an install. -->
        <q-banner v-if="chosen && blocking.length" dense class="surface-orange">
          <div class="text-weight-medium">
            {{ action === 'install' ? 'Pas encore déployable' : 'Désinstallation impossible' }}
          </div>
          <ul class="q-my-xs q-pl-md">
            <li v-for="p in blocking" :key="p.code">{{ p.message }}</li>
          </ul>
        </q-banner>
        <q-banner v-else-if="installBlockers.length" dense class="surface-orange">
          <div class="text-weight-medium">Aucun poste ne l’installera</div>
          <ul class="q-my-xs q-pl-md" style="overflow-wrap: anywhere">
            <li v-for="m in installBlockers" :key="m">{{ m }}</li>
          </ul>
        </q-banner>
        <q-banner v-else-if="chosen" dense class="surface-blue">
          {{ trustSentence(chosen, action) }}
        </q-banner>
      </q-card-section>

      <q-card-actions align="right" class="q-px-md q-pb-md">
        <q-btn v-close-popup flat no-caps label="Annuler" />
        <q-btn
          unelevated
          no-caps
          :color="action === 'uninstall' ? 'negative' : 'primary'"
          :label="okLabel"
          :disable="!ready || busy"
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
  blockingProblems,
  deployable,
  deployPackage,
  listPackages,
  methodAMaxLabel,
  packageChoiceLabel,
  publisherOf,
  stepTrust,
  tooLargeForMethodA,
  uninstallable,
  type DeployAction,
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
// From the first click to the answer, the confirmation included: a second
// click while the number of postes is being counted would otherwise open a
// second confirmation over the first (audit U04).
const busy = ref(false);
// Which showing of the dialog a send belongs to. Closed, or closed and opened
// again, while the postes are being counted: that send is over — it must
// neither pop its confirmation over whatever is on screen by then, nor keep
// the button of the next showing disabled.
let showing = 0;

const fixedPackage = computed(() => props.package ?? null);
const chosen = computed<Package | null>(
  () => fixedPackage.value ?? packages.value.find((p) => p.id === chosenId.value) ?? null,
);
// What the server would accept for the action: the same rule as its command
// route, read from the package (deployable / uninstallable).
// Two packages may bear one name and version: each then says what tells it
// from the other (packageChoiceLabel).
const packageOptions = computed(() => {
  const offered = packages.value.filter(action.value === 'install' ? deployable : uninstallable);
  return offered.map((p) => ({ label: packageChoiceLabel(p, offered), value: p.id }));
});
const canUninstall = computed(
  () => !chosen.value || chosen.value.kind === 'winget' || !!chosen.value.uninstall_run,
);
const blocking = computed(() => (chosen.value ? blockingProblems(chosen.value, action.value) : []));
// Why no poste would install it, named by the server — the file in the way
// included — where the dialog used to say « ni signé, ni lancé par un
// exécutable d'éditeur » whatever the cause.
const installBlockers = computed(() =>
  chosen.value && action.value === 'install' && !blocking.value.length
    ? (chosen.value.install_blockers ?? [])
    : [],
);
const ready = computed(() => {
  if (!chosen.value) return false;
  // What the server answers 409 to is not sent: an install of an incomplete
  // or retired package, an uninstall the agent would refuse the manifest for.
  if (action.value === 'install' ? !deployable(chosen.value) : !uninstallable(chosen.value))
    return false;
  // The dialog says no poste will run it: it does not send it either (audit
  // B30) — an uninstall no more than an install (U04).
  if (stepTrust(chosen.value, action.value) === 'none') return false;
  if (installBlockers.value.length) return false;
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

function trustSentence(p: Package, step: DeployAction): string {
  switch (stepTrust(p, step)) {
    case 'winget':
      return step === 'install'
        ? 'Paquet winget : seuls les postes où la GPO active winget (DeployWinget) l’installeront.'
        : 'Paquet winget : seuls les postes où la GPO active winget (DeployWinget) le désinstalleront.';
    case 'signed':
      return 'Paquet signé : seuls les postes dont la GPO approuve ce certificat (DeploySigners) l’exécuteront.';
    case 'publisher':
      return `Non signé par l’administrateur : seuls les postes dont la GPO approuve l’éditeur « ${publisherOf(p, step) ?? ''} » (DeployPublishers) l’exécuteront.`;
    case 'product_code':
      return 'Désinstallation par code produit (msiexec /x) : seuls les postes dont la GPO approuve au moins un éditeur (DeployPublishers) l’exécuteront.';
    default:
      if (tooLargeForMethodA(p, step))
        return `Plus de ${methodAMaxLabel(p)} de fichiers : sans signature de l’administrateur, aucun poste ne les téléchargera (plafond de la méthode A). Signez le paquet avant de le déployer.`;
      return step === 'install'
        ? 'Ni signé, ni lancé par un exécutable d’éditeur : aucun poste ne l’exécutera. Signez le paquet avant de le déployer.'
        : 'Désinstallation ni signée, ni lancée par un exécutable d’éditeur, ni par « msiexec /x {code produit} » : aucun poste ne l’exécutera. Signez le paquet avant de le déployer.';
  }
}

watch(
  () => props.modelValue,
  async (open) => {
    // Either way, whatever send was under way belongs to the past.
    showing++;
    busy.value = false;
    sending.value = false;
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
async function confirmed(mine: number): Promise<boolean> {
  const wide = !props.machineIds?.length && scope.value === 'all';
  if (!wide && action.value !== 'uninstall') return true;
  const count = await targetCount();
  // Closed while the postes were being counted: nothing is asked, nothing
  // is sent.
  if (mine !== showing) return false;
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
  if (!chosen.value || busy.value) return;
  const mine = showing;
  busy.value = true;
  try {
    const target: DeployTarget = props.machineIds?.length
      ? { machine_ids: props.machineIds }
      : scope.value === 'all'
        ? { target_all: true }
        : { target_location: location.value ?? '' };
    if (!(await confirmed(mine))) return;
    sending.value = true;
    const res = await deployPackage(chosen.value.id, action.value, target);
    $q.notify(bulkSendNotification(res));
    emit('update:modelValue', false);
    emit('sent');
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'Envoi impossible') });
  } finally {
    // Only for the showing this send was started in: a later one has its
    // own state, reset when it opened.
    if (mine === showing) {
      sending.value = false;
      busy.value = false;
    }
  }
}
</script>

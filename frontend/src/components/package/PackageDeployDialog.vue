<template>
  <!-- Install or remove a package: on given postes (a fiche, a selection), or
       — opened from a package's page — on the parc or one site. -->
  <q-dialog :model-value="modelValue" @update:model-value="emit('update:modelValue', $event)">
    <q-card style="width: 520px; max-width: 95vw">
      <q-card-section class="text-h6">
        {{
          action === 'install'
            ? t('packagePages.deploy.titleInstall')
            : t('packagePages.deploy.titleUninstall')
        }}
      </q-card-section>

      <q-card-section class="q-gutter-md">
        <q-btn-toggle
          v-model="action"
          no-caps
          unelevated
          toggle-color="primary"
          :options="[
            { label: t('packagePages.deploy.install'), value: 'install' },
            {
              label: t('packagePages.deploy.uninstall'),
              value: 'uninstall',
              disable: !canUninstall,
            },
          ]"
        />

        <q-select
          v-if="!fixedPackage"
          v-model="chosenId"
          :options="packageOptions"
          :loading="loadingPackages"
          :label="t('packagePages.deploy.package')"
          outlined
          dense
          emit-value
          map-options
          :hint="packageOptions.length ? '' : t('packagePages.deploy.noPackage')"
        />

        <template v-if="!machineIds?.length">
          <q-option-group
            v-model="scope"
            :options="[
              { label: t('packagePages.deploy.scopeAll'), value: 'all' },
              { label: t('packagePages.deploy.scopeLocation'), value: 'location' },
            ]"
            inline
          />
          <q-select
            v-if="scope === 'location'"
            v-model="location"
            :options="locations"
            :label="t('packagePages.deploy.location')"
            outlined
            dense
          />
        </template>
        <div v-else class="text-body2">
          {{ t('packagePages.deploy.onMachines', { count: machineIds.length }, machineIds.length) }}
        </div>

        <!-- What the server would refuse the command for, said before it is
             sent: an uninstall is held back by fewer problems than an install. -->
        <q-banner v-if="chosen && blocking.length" dense class="surface-orange">
          <div class="text-weight-medium">
            {{
              action === 'install'
                ? t('packagePages.deploy.notDeployable')
                : t('packagePages.deploy.cannotUninstall')
            }}
          </div>
          <ul class="q-my-xs q-pl-md">
            <li v-for="p in blocking" :key="p.code">{{ problemText(p) }}</li>
          </ul>
        </q-banner>
        <q-banner v-else-if="installBlockers.length" dense class="surface-orange">
          <div class="text-weight-medium">{{ t('packagePages.deploy.noComputer') }}</div>
          <ul class="q-my-xs q-pl-md" style="overflow-wrap: anywhere">
            <li v-for="m in installBlockers" :key="m">{{ m }}</li>
          </ul>
        </q-banner>
        <q-banner v-else-if="chosen" dense class="surface-blue">
          {{ trustSentence(chosen, action) }}
        </q-banner>
      </q-card-section>

      <q-card-actions align="right" class="q-px-md q-pb-md">
        <q-btn v-close-popup flat no-caps :label="t('packagePages.deploy.cancel')" />
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
import { installBlockerTexts, problemText } from 'src/utils/packageText';
import { computed, ref, watch } from 'vue';
import { useQuasar } from 'quasar';
import { t } from 'src/i18n';
import { bulkSendNotification } from 'src/services/commands';
import { apiErrorCode, apiErrorMessage } from 'src/services/errors';
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
import { liveDialog } from 'src/utils/liveDialog';
import { windowText, type ForbiddenWindow } from 'src/services/schedules';
import { notify } from 'src/utils/notify';

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
    ? installBlockerTexts(chosen.value)
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
/** The action's verb, alone on a button or first in a sentence. */
function verbLabel(): string {
  return action.value === 'install'
    ? t('packagePages.deploy.install')
    : t('packagePages.deploy.uninstall');
}

const okLabel = computed(() => {
  const verb = verbLabel();
  if (props.machineIds?.length)
    return props.machineIds.length > 1
      ? t('packagePages.deploy.okMachines', { verb, count: props.machineIds.length })
      : verb;
  return scope.value === 'all'
    ? t('packagePages.deploy.okAll', { verb })
    : t('packagePages.deploy.okLocation', { verb, location: location.value ?? '…' });
});

function trustSentence(p: Package, step: DeployAction): string {
  switch (stepTrust(p, step)) {
    case 'winget':
      return step === 'install'
        ? t('packagePages.deploy.trust.wingetInstall')
        : t('packagePages.deploy.trust.wingetUninstall');
    case 'signed':
      return t('packagePages.deploy.trust.signed');
    case 'publisher':
      return t('packagePages.deploy.trust.publisher', { publisher: publisherOf(p, step) ?? '' });
    case 'product_code':
      return t('packagePages.deploy.trust.productCode');
    default:
      if (tooLargeForMethodA(p, step))
        return t('packagePages.deploy.trust.tooLarge', { max: methodAMaxLabel(p) });
      return step === 'install'
        ? t('packagePages.deploy.trust.noneInstall')
        : t('packagePages.deploy.trust.noneUninstall');
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
        notify($q, () => ({
          type: 'negative',
          message: apiErrorMessage(e, t('packagePages.deploy.loadFailed')),
        }));
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
  const where = () =>
    count === null
      ? wide
        ? t('packagePages.deploy.confirm.whereAll')
        : t('packagePages.deploy.confirm.whereTargets')
      : t(
          wide
            ? 'packagePages.deploy.confirm.whereCountAll'
            : 'packagePages.deploy.confirm.whereCount',
          { count },
          count,
        );
  return new Promise((resolve) => {
    liveDialog($q, () => ({
      title: t('packagePages.deploy.confirm.title', {
        verb: verbLabel(),
        name: chosen.value?.name ?? '',
      }),
      message: t('packagePages.deploy.confirm.message', { verb: verbLabel(), where: where() }),
      cancel: { flat: true, noCaps: true, label: t('packagePages.deploy.cancel') },
      ok: {
        unelevated: true,
        noCaps: true,
        label: verbLabel(),
        color: action.value === 'uninstall' ? 'negative' : 'primary',
      },
      persistent: true,
    }))
      .onOk(() => resolve(true))
      .onCancel(() => resolve(false));
  });
}

/** The forbidden window named, and the question asked once. */
function confirmedForbidden(error: unknown): Promise<boolean> {
  const details = (
    error as { response?: { data?: { error?: { details?: { window?: ForbiddenWindow } } } } }
  )?.response?.data?.error?.details;
  const window = details?.window ? windowText(details.window) : '';
  return new Promise((resolve) => {
    liveDialog($q, () => ({
      title: t('schedules.forbiddenConfirm.title'),
      message: t('schedules.forbiddenConfirm.deploy', { window }),
      cancel: { flat: true, noCaps: true, label: t('schedules.forbiddenConfirm.cancel') },
      ok: { color: 'negative', noCaps: true, label: t('schedules.forbiddenConfirm.ok') },
      persistent: true,
    }))
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
    let res;
    try {
      res = await deployPackage(chosen.value.id, action.value, target);
    } catch (e) {
      // Inside a forbidden window (Paramètres): a deployment to several
      // postes goes once the person says so, as from the machine list.
      if (apiErrorCode(e) !== 'command.forbidden_window') throw e;
      if (!(await confirmedForbidden(e)) || mine !== showing) return;
      res = await deployPackage(chosen.value.id, action.value, target, true);
    }
    notify($q, () => bulkSendNotification(res));
    emit('update:modelValue', false);
    emit('sent');
  } catch (e) {
    notify($q, () => ({
      type: 'negative',
      message: apiErrorMessage(e, t('packagePages.deploy.sendFailed')),
    }));
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

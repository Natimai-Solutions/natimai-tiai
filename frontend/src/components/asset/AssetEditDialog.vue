<template>
  <!-- One form for a poste's asset and for equipment without an agent: the
       equipment adds what a poste takes from its machine record — a name, a
       type, a room, its hardware. -->
  <q-dialog :model-value="modelValue" @update:model-value="(v) => emit('update:modelValue', v)">
    <q-card style="width: 640px; max-width: 95vw">
      <q-card-section class="text-h6">
        {{ isNew ? t('assets.form.titleNew') : t('assets.form.titleEdit') }}
        <div v-if="subtitle" class="text-caption text-muted">{{ subtitle }}</div>
      </q-card-section>
      <q-form @submit="submit">
        <q-card-section class="row q-col-gutter-md">
          <template v-if="equipment">
            <q-input
              v-model="form.name"
              class="col-12 col-sm-8"
              :label="t('assets.form.name')"
              outlined
              dense
              maxlength="200"
              autofocus
              reactive-rules
              :rules="[(v: string) => !!v?.trim() || t('assets.form.nameRequired')]"
            />
            <q-select
              v-model="form.kind"
              class="col-12 col-sm-4"
              :options="kindOptions"
              emit-value
              map-options
              :label="t('assets.form.kind')"
              outlined
              dense
            />
            <q-select
              v-model="form.room_id"
              class="col-12"
              :options="roomOptions"
              emit-value
              map-options
              clearable
              :label="t('assets.form.room')"
              outlined
              dense
            />
            <q-input
              v-model="form.manufacturer"
              class="col-12 col-sm-4"
              :label="t('assets.form.manufacturer')"
              outlined
              dense
              maxlength="200"
            />
            <q-input
              v-model="form.model"
              class="col-12 col-sm-4"
              :label="t('assets.form.model')"
              outlined
              dense
              maxlength="200"
            />
            <q-input
              v-model="form.serial_number"
              class="col-12 col-sm-4"
              :label="t('assets.form.serial')"
              outlined
              dense
              maxlength="200"
            />
          </template>
          <q-input
            v-model="form.inventory_number"
            class="col-12 col-sm-6"
            :label="t('assets.form.inventory')"
            outlined
            dense
            maxlength="100"
          />
          <q-select
            v-model="form.status"
            class="col-12 col-sm-6"
            :options="statusOptions"
            emit-value
            map-options
            :label="t('assets.form.status')"
            outlined
            dense
          />
          <q-input
            v-model="form.purchase_date"
            class="col-12 col-sm-4"
            type="date"
            stack-label
            :label="t('assets.form.purchaseDate')"
            outlined
            dense
          />
          <q-input
            v-model="form.warranty_end"
            class="col-12 col-sm-4"
            type="date"
            stack-label
            :label="t('assets.form.warrantyEnd')"
            outlined
            dense
          />
          <q-input
            v-model="form.purchase_price"
            class="col-12 col-sm-4"
            inputmode="decimal"
            :label="t('assets.form.price')"
            outlined
            dense
            :error="priceError !== null"
            :error-message="priceError ?? undefined"
          />
          <q-input
            v-model="form.supplier"
            class="col-12 col-sm-6"
            :label="t('assets.form.supplier')"
            outlined
            dense
            maxlength="200"
          />
          <q-input
            v-model="form.order_reference"
            class="col-12 col-sm-6"
            :label="t('assets.form.orderReference')"
            outlined
            dense
            maxlength="200"
          />
          <template v-if="form.status === 'on_loan'">
            <q-input
              v-model="form.borrower"
              class="col-12 col-sm-8"
              :label="t('assets.form.borrower')"
              outlined
              dense
              maxlength="200"
            />
            <q-input
              v-model="form.loan_due"
              class="col-12 col-sm-4"
              type="date"
              stack-label
              :label="t('assets.form.loanDue')"
              outlined
              dense
            />
          </template>
          <q-input
            v-model="form.notes"
            class="col-12"
            type="textarea"
            autogrow
            :label="t('assets.form.notes')"
            outlined
            dense
            maxlength="5000"
          />
        </q-card-section>
        <q-card-actions class="q-px-md q-pb-md">
          <q-btn
            v-if="!isNew && asset"
            flat
            no-caps
            color="primary"
            icon="qr_code"
            :label="t('assets.form.renewToken')"
            :loading="renewing"
            @click="renew"
          >
            <q-tooltip max-width="280px">{{ t('assets.form.renewTokenHint') }}</q-tooltip>
          </q-btn>
          <q-btn
            v-if="!isNew && asset && equipment"
            flat
            no-caps
            color="negative"
            :label="t('assets.form.delete')"
            @click="remove"
          />
          <q-space />
          <q-btn v-close-popup flat :label="t('assets.form.cancel')" />
          <q-btn
            type="submit"
            color="primary"
            :label="t('assets.form.save')"
            :loading="saving"
            :disable="priceError !== null"
          />
        </q-card-actions>
      </q-form>
    </q-card>
  </q-dialog>
</template>

<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue';
import { useQuasar } from 'quasar';
import { t } from 'src/i18n';
import {
  ASSET_STATUSES,
  EQUIPMENT_KINDS,
  assetKindLabel,
  assetStatusLabel,
  createEquipment,
  deleteAsset,
  putMachineAsset,
  renewAssetToken,
  updateAsset,
  type Asset,
  type AssetKind,
  type AssetPayload,
  type AssetStatus,
} from 'src/services/assets';
import { apiErrorMessage } from 'src/services/errors';
import { listRooms } from 'src/services/rooms';
import { liveDialog } from 'src/utils/liveDialog';
import { notify } from 'src/utils/notify';

const props = defineProps<{
  modelValue: boolean;
  /** The asset to edit; null for a new one. */
  asset: Asset | null;
  /** The poste whose asset this is; absent for equipment without an agent. */
  machineId?: string | null | undefined;
  subtitle?: string | undefined;
}>();
const emit = defineEmits<{
  (e: 'update:modelValue', value: boolean): void;
  (e: 'saved', asset: Asset | null): void;
}>();

const $q = useQuasar();
const saving = ref(false);
const renewing = ref(false);
const isNew = computed(() => props.asset === null);
const equipment = computed(() => !props.machineId && !props.asset?.machine_id);

const empty = () => ({
  name: '',
  kind: 'other' as AssetKind,
  room_id: null as string | null,
  manufacturer: '',
  model: '',
  serial_number: '',
  inventory_number: '',
  status: 'in_service' as AssetStatus,
  purchase_date: '',
  warranty_end: '',
  purchase_price: '',
  supplier: '',
  order_reference: '',
  borrower: '',
  loan_due: '',
  notes: '',
});
const form = reactive(empty());

const roomOptions = ref<{ label: string; value: string }[]>([]);
const kindOptions = computed(() =>
  EQUIPMENT_KINDS.map((k) => ({ label: assetKindLabel(k), value: k })),
);
const statusOptions = computed(() =>
  ASSET_STATUSES.map((s) => ({ label: assetStatusLabel(s), value: s })),
);

/** A price as typed (« 749,90 », « 1 200 »), or the reason it is refused. */
function normalisedPrice(raw: string): string {
  const text = raw.replace(/[\s  €]/g, '').replace(',', '.');
  return text;
}
const priceError = computed(() => {
  const text = normalisedPrice(form.purchase_price ?? '');
  if (!text) return null;
  return /^\d{1,10}(\.\d{1,2})?$/.test(text) ? null : t('assets.form.priceInvalid');
});

watch(
  () => props.modelValue,
  async (open) => {
    if (!open) return;
    Object.assign(form, empty());
    const a = props.asset;
    if (a) {
      form.name = a.name ?? '';
      form.kind = (a.kind === 'computer' ? 'other' : a.kind) as AssetKind;
      form.room_id = a.machine_id ? null : a.room_id;
      form.manufacturer = a.machine_id ? '' : (a.manufacturer ?? '');
      form.model = a.machine_id ? '' : (a.model ?? '');
      form.serial_number = a.machine_id ? '' : (a.serial_number ?? '');
      form.inventory_number = a.inventory_number ?? '';
      form.status = a.status as AssetStatus;
      form.purchase_date = a.purchase_date ?? '';
      form.warranty_end = a.warranty_end ?? '';
      form.purchase_price = a.purchase_price ?? '';
      form.supplier = a.supplier ?? '';
      form.order_reference = a.order_reference ?? '';
      form.borrower = a.borrower ?? '';
      form.loan_due = a.loan_due ?? '';
      form.notes = a.notes ?? '';
    }
    if (equipment.value && !roomOptions.value.length) {
      try {
        const rooms = await listRooms();
        roomOptions.value = rooms
          .map((r) => ({
            label: r.building ? `${r.building.name} — ${r.name}` : r.name,
            value: r.id,
          }))
          .sort((x, y) => x.label.localeCompare(y.label));
      } catch {
        roomOptions.value = [];
      }
    }
  },
  { immediate: true },
);

/** Empty text is « not entered »: sent as null, so the server clears it. */
function orNull(value: string): string | null {
  const trimmed = value.trim();
  return trimmed ? trimmed : null;
}

function payload(): AssetPayload {
  const common: AssetPayload = {
    inventory_number: orNull(form.inventory_number),
    status: form.status,
    purchase_date: orNull(form.purchase_date),
    warranty_end: orNull(form.warranty_end),
    purchase_price: orNull(normalisedPrice(form.purchase_price ?? '')),
    supplier: orNull(form.supplier),
    order_reference: orNull(form.order_reference),
    // A loan's fields mean something only while it is on loan.
    borrower: form.status === 'on_loan' ? orNull(form.borrower) : null,
    loan_due: form.status === 'on_loan' ? orNull(form.loan_due) : null,
    notes: orNull(form.notes),
  };
  if (!equipment.value) return common;
  return {
    ...common,
    name: form.name.trim(),
    kind: form.kind,
    room_id: form.room_id,
    manufacturer: orNull(form.manufacturer),
    model: orNull(form.model),
    serial_number: orNull(form.serial_number),
  };
}

async function submit(): Promise<void> {
  if (priceError.value) return;
  saving.value = true;
  try {
    let saved: Asset;
    const body = payload();
    if (props.machineId) saved = await putMachineAsset(props.machineId, body);
    else if (props.asset) saved = await updateAsset(props.asset.id, body);
    else saved = await createEquipment({ ...body, name: form.name.trim() });
    notify($q, () => ({ type: 'positive', message: t('assets.form.saved') }));
    emit('saved', saved);
    emit('update:modelValue', false);
  } catch (e) {
    notify($q, () => ({
      type: 'negative',
      message: apiErrorMessage(e, t('assets.form.saveFailed')),
    }));
  } finally {
    saving.value = false;
  }
}

async function renew(): Promise<void> {
  if (!props.asset) return;
  renewing.value = true;
  try {
    const saved = await renewAssetToken(props.asset.id);
    notify($q, () => ({ type: 'positive', message: t('assets.form.tokenRenewed') }));
    emit('saved', saved);
  } catch (e) {
    notify($q, () => ({
      type: 'negative',
      message: apiErrorMessage(e, t('assets.form.saveFailed')),
    }));
  } finally {
    renewing.value = false;
  }
}

function remove(): void {
  const asset = props.asset;
  if (!asset) return;
  liveDialog($q, () => ({
    message: t('assets.form.deleteConfirm', { name: asset.display_name ?? '' }),
    cancel: { flat: true, noCaps: true, label: t('assets.form.cancel') },
    ok: { color: 'negative', noCaps: true, label: t('assets.form.delete') },
  })).onOk(() => {
    void (async () => {
      try {
        await deleteAsset(asset.id);
        notify($q, () => ({ type: 'positive', message: t('assets.form.deleted') }));
        emit('saved', null);
        emit('update:modelValue', false);
      } catch (e) {
        notify($q, () => ({
          type: 'negative',
          message: apiErrorMessage(e, t('assets.form.saveFailed')),
        }));
      }
    })();
  });
}
</script>

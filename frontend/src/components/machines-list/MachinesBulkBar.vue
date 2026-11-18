<template>
  <!-- Shown only when there is a selection and something the account may do
       with it: a bar of buttons that all refuse would only be noise. -->
  <div
    v-if="count && (actionGroups.length || canPlace || canCheck || canDeploy || canReenroll)"
    class="row items-center q-mb-sm"
  >
    <div class="text-caption text-muted q-mr-md">
      {{ t('machines.bulk.selected', { count }, count) }}
    </div>
    <q-btn
      v-if="canPlace"
      flat
      dense
      color="primary"
      icon="meeting_room"
      :label="t('machines.bulk.place')"
      class="q-mr-sm"
      @click="emit('place')"
    />
    <q-btn
      v-if="canCheck"
      flat
      dense
      color="primary"
      icon="fact_check"
      :label="t('machines.bulk.check')"
      class="q-mr-sm"
      @click="emit('ask')"
    />
    <q-btn
      v-if="canDeploy"
      flat
      dense
      color="primary"
      icon="install_desktop"
      :label="t('machines.bulk.deploy')"
      class="q-mr-sm"
      @click="emit('deploy')"
    />
    <!-- C2: a reinstall wave, or postes revoked by mistake — approved together. -->
    <q-btn
      v-if="canReenroll"
      flat
      dense
      color="primary"
      icon="key"
      :label="t('machines.bulk.reenroll')"
      class="q-mr-sm"
      @click="emit('reenroll')"
    />
    <q-btn-dropdown
      v-if="actionGroups.length"
      color="primary"
      dense
      :label="t('machines.bulk.actions')"
      icon="bolt"
    >
      <q-list>
        <template v-for="section in actionGroups" :key="section.group">
          <q-item-label header class="q-py-xs">{{ section.label }}</q-item-label>
          <q-item
            v-for="action in section.actions"
            :key="action.type"
            v-close-popup
            clickable
            @click="emit('run', action)"
          >
            <q-item-section avatar><q-icon :name="action.icon" /></q-item-section>
            <q-item-section>{{ action.label }}</q-item-section>
          </q-item>
        </template>
      </q-list>
    </q-btn-dropdown>
  </div>
</template>

<script setup lang="ts">
import { t } from 'src/i18n';
import type { CommandAction, CommandActionGroup } from 'src/services/commands';

/** What can be done to the selected postes, in one bar above the table. */
defineProps<{
  /** How many postes are selected. */
  count: number;
  /** Moving postes by hand: the permission, and a server not in a directory mode. */
  canPlace: boolean;
  /** Asking for a verification. */
  canCheck: boolean;
  /** The bulk commands the account may run, in their sections. */
  actionGroups: CommandActionGroup[];
  /** Installing or removing a package: package:read and the risky commands. */
  canDeploy?: boolean;
  /** Allowing re-enrolment: machine:write. */
  canReenroll?: boolean;
}>();

const emit = defineEmits<{
  place: [];
  ask: [];
  deploy: [];
  reenroll: [];
  run: [action: CommandAction];
}>();
</script>

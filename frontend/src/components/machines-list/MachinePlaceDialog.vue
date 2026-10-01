<template>
  <!-- Placing the selection: one room, or none. The server reports which
       postes now disagree on the site rather than refusing them. -->
  <q-dialog v-model="open">
    <q-card style="width: 420px; max-width: 90vw">
      <q-card-section class="text-h6">Affecter à une salle</q-card-section>
      <q-card-section class="q-pt-none text-body2 text-grey-8">
        {{ count }} poste(s) sélectionné(s)
      </q-card-section>
      <q-card-section>
        <q-select
          v-model="roomId"
          :options="roomOptions"
          emit-value
          map-options
          label="Salle"
          outlined
          dense
          autofocus
        />
      </q-card-section>
      <q-card-actions align="right" class="q-px-md q-pb-md">
        <q-btn v-close-popup flat label="Annuler" />
        <q-btn
          color="primary"
          label="Affecter"
          :loading="placing"
          :disable="!roomId"
          @click="submit"
        />
      </q-card-actions>
    </q-card>
  </q-dialog>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue';
import { roomLabel, type Room } from 'src/services/rooms';
import { ROOM_NONE } from 'src/utils/machineListFilters';

const props = defineProps<{
  /** How many postes are selected. */
  count: number;
  rooms: Room[];
  /**
   * What to do with the room picked: the caller knows the selection, reports
   * a failure itself and closes the dialog on success.
   */
  save: (roomId: string | null) => Promise<void>;
}>();

const open = defineModel<boolean>({ required: true });

const placing = ref(false);
// Kept from one opening to the next: placing a selection, then the next one
// in the same room, is how a room gets filled.
const roomId = ref<string | null>(null);

// « Sans salle » first: it is the one entry that is not a room.
const roomOptions = computed(() => [
  { label: 'Sans salle (retirer de la salle)', value: ROOM_NONE },
  ...props.rooms.map((r) => ({ label: roomLabel(r), value: r.id })),
]);

async function submit() {
  // Nothing picked yet: nothing to do, and no spinner for it either.
  if (!roomId.value) return;
  placing.value = true;
  try {
    await props.save(roomId.value);
  } finally {
    placing.value = false;
  }
}
</script>

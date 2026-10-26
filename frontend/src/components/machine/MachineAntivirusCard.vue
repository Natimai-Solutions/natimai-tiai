<template>
  <MachineInfoCard
    v-if="show"
    title="Antivirus enregistré"
    caption="Vu par le Security Center de Windows — un produit tiers, ou aucun."
    :rows="rows"
  >
    <template v-if="unread" #default>
      <q-card-section class="text-caption text-muted">
        Jamais relevé sur ce poste : son agent est antérieur à la lecture du Security Center, ou
        l'hôte n'en a pas — un SKU Windows Server n'en embarque aucun. C'est ce que dit « Non relevé
        » dans la liste des postes : non pas que le poste soit sans antivirus, mais que ce relevé-là
        manque. L'état Defender ci-dessus, lui, est bien à jour.
      </q-card-section>
    </template>
  </MachineInfoCard>
</template>

<script setup lang="ts">
import { computed } from 'vue';
import MachineInfoCard from './MachineInfoCard.vue';
import type { InfoRow } from './types';
import type { MachineDetail } from 'src/services/machines';
import { antivirusLabel, boolLabel } from 'src/utils/format';

const props = defineProps<{ machine: MachineDetail }>();

/**
 * Whether the Security Center deserves a card of its own.
 *
 * Not when the product it names is Defender: every row it would carry is already
 * in the Defender card, and two panels stating the same protection twice read as
 * a display bug rather than as corroboration. It stays for a third-party product
 * — the case Defender's own WMI class cannot describe — for "no antivirus
 * registered at all", and for the case where nothing was ever read, which is the
 * one an administrator most needs spelled out.
 */
const show = computed(() => props.machine.av_product_is_defender !== true);

/**
 * No Security Center reading at all, as opposed to one that found nothing. The
 * card then explains itself instead of printing four rows of "Inconnu" beside a
 * Defender card that is plainly alive — the contradiction that reading invites.
 */
const unread = computed(() => props.machine.av_product_name == null);

const rows = computed<InfoRow[]>(() => {
  const m = props.machine;
  // Never read: the card shows its explanation instead, not a table of dashes.
  if (m.av_product_name == null) return [];
  const rows: InfoRow[] = [{ label: 'Produit', value: antivirusLabel(m.av_product_name) }];
  // Both bits below describe a *product*. With none registered they would only
  // add two "Inconnu" under a "Aucun" that has already said everything.
  if (m.av_product_name !== '') {
    rows.push(
      { label: 'Protection active', value: boolLabel(m.av_product_enabled) },
      // The Security Center exposes a freshness bit and nothing else — no
      // version, no date, which is why this card carries no scan or update
      // action for a third-party product.
      { label: 'Signatures à jour', value: boolLabel(m.av_product_signatures_up_to_date) },
    );
  }
  // No "Est Defender" row: the card being here at all is that answer, and the
  // Defender card says so in words on the machines where it is Defender.
  return rows;
});
</script>

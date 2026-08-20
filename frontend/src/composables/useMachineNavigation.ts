import { computed, ref, watch, type Ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { listMachines, type Machine } from 'src/services/machines';
import { DEFAULT_PAGE_SIZE, machineListParamsFromQuery, queryValue } from 'src/utils/machineQuery';

/**
 * Walk the search results from inside a poste's fiche.
 *
 * The list page hands over its whole query plus the row's absolute rank (`i`)
 * when opening a poste. From that, this resolves the neighbours by asking the
 * server for the two single-row pages around `i` — not by carrying the list in
 * a store. The reason is the same one that put pagination server-side: the
 * fleet does not fit in the client, and a fiche reached from a pasted URL or a
 * reloaded tab has no store to read anyway. Two rows per fiche is a cheaper
 * price than a list that is wrong after a refresh.
 *
 * With no `i` in the URL — a fiche opened from the dashboard, a bookmark, a
 * merge redirect — there is no search to walk and everything here is null: the
 * arrows simply do not render.
 */
export interface MachineNavigation {
  /** True when the fiche was opened from a list query, i.e. arrows apply. */
  fromSearch: Ref<boolean>;
  /** 0-based rank of this poste in the search, or null. */
  index: Ref<number | null>;
  /** Total results of the search, or null until known. */
  total: Ref<number | null>;
  previousMachine: Ref<Machine | null>;
  nextMachine: Ref<Machine | null>;
  /** "Poste 12 sur 340" — empty while the count is unknown. */
  positionLabel: Ref<string>;
  /** Query params to return to the list, positioned on this poste's page. */
  backQuery: Ref<Record<string, string>>;
  goPrevious: () => void;
  goNext: () => void;
}

export function useMachineNavigation(): MachineNavigation {
  const route = useRoute();
  const router = useRouter();

  const index = ref<number | null>(null);
  const total = ref<number | null>(null);
  const previousMachine = ref<Machine | null>(null);
  const nextMachine = ref<Machine | null>(null);

  const fromSearch = computed(() => index.value !== null);

  const positionLabel = computed(() =>
    index.value === null || total.value === null
      ? ''
      : `Poste ${index.value + 1} sur ${total.value}`,
  );

  /**
   * The list URL to go back to: the same query, on the page that actually holds
   * this poste. Landing on page 1 of a search whose result was on page 7 is the
   * same annoyance as losing the filters altogether — and after walking ten
   * results with the arrows, the page recorded when the fiche was opened is no
   * longer the one the current poste sits on.
   */
  const backQuery = computed(() => {
    const query: Record<string, string> = {};
    for (const [key, value] of Object.entries(route.query)) {
      if (key === 'i') continue;
      const scalar = queryValue(value);
      if (scalar) query[key] = scalar;
    }
    if (index.value !== null) {
      const page = Math.floor(index.value / pageSize()) + 1;
      // Page 1 is the list's own default and stays out of the URL, exactly as
      // the list page writes it.
      if (page > 1) query.page = String(page);
      else delete query.page;
    }
    return query;
  });

  /** The page size the list is using, as the URL records it. */
  function pageSize(): number {
    const raw = Number(queryValue(route.query.page_size) ?? String(DEFAULT_PAGE_SIZE));
    return Number.isInteger(raw) && raw > 0 ? raw : DEFAULT_PAGE_SIZE;
  }

  /** Fetch the row at absolute rank `rank`, or null past either end. */
  async function rowAt(rank: number): Promise<{ machine: Machine | null; total: number }> {
    if (rank < 0) return { machine: null, total: total.value ?? 0 };
    const data = await listMachines({
      ...machineListParamsFromQuery(route.query),
      page: rank + 1,
      page_size: 1,
    });
    return { machine: data.items[0] ?? null, total: data.total };
  }

  // Which resolution is the current one. Two round trips separate a click on ▶
  // from knowing the new neighbours; without this, a second click in that
  // window would walk to the *previous* poste's neighbour — landing on the same
  // machine again while the rank moved on, desynchronising the two for good.
  let resolutionId = 0;

  async function resolve() {
    const id = ++resolutionId;
    const raw = queryValue(route.query.i);
    const rank = raw === null ? Number.NaN : Number(raw);
    if (!Number.isInteger(rank) || rank < 0) {
      index.value = null;
      total.value = null;
      previousMachine.value = null;
      nextMachine.value = null;
      return;
    }
    index.value = rank;
    // Cleared up front: they belong to the poste being left, and an arrow
    // pressed before the answer arrives must do nothing rather than the wrong
    // thing. The buttons simply sit disabled for the round trip.
    previousMachine.value = null;
    nextMachine.value = null;
    try {
      const [before, after] = await Promise.all([rowAt(rank - 1), rowAt(rank + 1)]);
      if (id !== resolutionId) return;
      previousMachine.value = before.machine;
      nextMachine.value = after.machine;
      // Read off `after`, which is always a real request and therefore always
      // carries the search's true total — even asked for a page past the last
      // result. `before` makes no request at rank 0.
      total.value = after.total;
    } catch {
      // Neighbours are a convenience: a failed lookup hides the arrows rather
      // than putting an error over a fiche that loaded perfectly well.
      if (id !== resolutionId) return;
      previousMachine.value = null;
      nextMachine.value = null;
      total.value = null;
    }
  }

  function go(machine: Machine | null, rank: number) {
    if (!machine) return;
    void router.push({
      name: 'machine-detail',
      params: { id: machine.id },
      query: { ...backQuery.value, i: String(rank) },
    });
  }

  function goPrevious() {
    if (index.value === null) return;
    go(previousMachine.value, index.value - 1);
  }

  function goNext() {
    if (index.value === null) return;
    go(nextMachine.value, index.value + 1);
  }

  // Re-resolved on every navigation: moving to the next poste is a route change
  // on the same component, so nothing else would refresh the arrows.
  watch(() => route.fullPath, resolve, { immediate: true });

  return {
    fromSearch,
    index,
    total,
    previousMachine,
    nextMachine,
    positionLabel,
    backQuery,
    goPrevious,
    goNext,
  };
}

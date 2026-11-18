import { computed, onScopeDispose, ref, watch, type Ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { t } from 'src/i18n';
import { getMachineNeighbours, type MachineNeighbour } from 'src/services/machines';
import { DEFAULT_PAGE_SIZE, machineListParamsFromQuery, queryValue } from 'src/utils/machineQuery';

/**
 * Walk the search results from inside a poste's fiche.
 *
 * The list page hands over its whole query plus the row's absolute rank (`i`)
 * when opening a poste. The neighbours and the rank are then the server's
 * (`GET /machines/{id}/neighbours`, audit T31): the same filters, scope and
 * order as the list, worked out on the list's own ORDER BY. Not a store of
 * the list, nor blocks of it read from here: the fleet does not fit in the
 * client, a fiche reached from a pasted URL or a reloaded tab has no store to
 * read, and a block reader loses the postes that move into a block it has
 * already read.
 *
 * With no `i` in the URL — a fiche opened from the dashboard, a bookmark, a
 * merge redirect — there is no search to walk and everything here is null: the
 * arrows simply do not render.
 *
 * The list's default sort is the last contact, which every heartbeat changes
 * (audit B18): the poste reached with ▶ would, a minute later, sit at the top
 * of the list with the wrong neighbours. Each answer therefore carries where
 * the postes it names stood (a cursor), and the walk goes on from that place
 * — in the list as it is now. Opened from the list, a poste is placed where
 * it stands at that moment.
 */
export interface MachineNavigation {
  /** True when the fiche was opened from a list query, i.e. arrows apply. */
  fromSearch: Ref<boolean>;
  /** 0-based rank of this poste in the search, or null. */
  index: Ref<number | null>;
  /** Total results of the search, or null until known. */
  total: Ref<number | null>;
  previousMachine: Ref<MachineNeighbour | null>;
  nextMachine: Ref<MachineNeighbour | null>;
  /** "Poste 12 sur 340" — empty while the count is unknown. */
  positionLabel: Ref<string>;
  /** Query params to return to the list, positioned on this poste's page. */
  backQuery: Ref<Record<string, string>>;
  goPrevious: () => void;
  goNext: () => void;
}

/**
 * Where each poste stood when the walk reached it, per search: sent back with
 * the next request for that poste, so that Back and Forward in the browser
 * land on the same place too. For the life of the tab, emptied each time the
 * list is shown again (the next fiche walks the list as it is then).
 */
const cursors = new Map<string, string>();
const MAX_CURSORS = 500;

/** Forget every walk's places (back on the list; tests). */
export function resetMachineNavigation(): void {
  cursors.clear();
}

function remember(key: string, cursor: string | null | undefined): void {
  if (!cursor) return;
  // Re-inserted so that the oldest entry is the least recently used.
  cursors.delete(key);
  cursors.set(key, cursor);
  if (cursors.size > MAX_CURSORS) {
    const oldest = cursors.keys().next().value;
    if (oldest !== undefined) cursors.delete(oldest);
  }
}

export function useMachineNavigation(): MachineNavigation {
  const route = useRoute();
  const router = useRouter();

  const index = ref<number | null>(null);
  const total = ref<number | null>(null);
  const previousMachine = ref<MachineNeighbour | null>(null);
  const nextMachine = ref<MachineNeighbour | null>(null);

  const fromSearch = computed(() => index.value !== null);

  const positionLabel = computed(() =>
    index.value === null || total.value === null
      ? ''
      : t('machine.navigation.position', { index: index.value + 1, total: total.value }),
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
      // Neither the rank nor the fiche's own tab belongs to the list's query.
      if (key === 'i' || key === 'tab') continue;
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

  /** The search this fiche was opened from, as a stable key. */
  function searchKey(): string {
    const params = machineListParamsFromQuery(route.query);
    return JSON.stringify(Object.entries(params).sort(([a], [b]) => a.localeCompare(b)));
  }

  function cursorKey(search: string, id: string): string {
    return `${search}\n${id}`;
  }

  // Which resolution is the current one. A round trip separates a click on ▶
  // from knowing the new neighbours; without this, a second click in that
  // window would walk to the *previous* poste's neighbour — landing on the same
  // machine again while the rank moved on, desynchronising the two for good.
  let resolutionId = 0;

  function clear() {
    index.value = null;
    total.value = null;
    previousMachine.value = null;
    nextMachine.value = null;
  }

  async function resolve() {
    const id = ++resolutionId;
    const raw = queryValue(route.query.i);
    const rank = raw === null ? Number.NaN : Number(raw);
    const current = String(route.params.id ?? '');
    if (!Number.isInteger(rank) || rank < 0 || !current) {
      clear();
      return;
    }
    index.value = rank;
    // Cleared up front: they belong to the poste being left, and an arrow
    // pressed before the answer arrives must do nothing rather than the wrong
    // thing. The buttons simply sit disabled for the round trip.
    previousMachine.value = null;
    nextMachine.value = null;
    const search = searchKey();
    const params = machineListParamsFromQuery(route.query);
    const cursor = cursors.get(cursorKey(search, current));
    try {
      const data = await getMachineNeighbours(current, cursor ? { ...params, cursor } : params);
      if (id !== resolutionId) return;
      if (data.rank === null) {
        // No longer in the list (a filter it has left since): neighbours and a
        // position would belong to other postes (audit B18). The arrows stay
        // disabled and the position unsaid.
        total.value = null;
        return;
      }
      remember(cursorKey(search, current), data.cursor);
      for (const m of [data.previous, data.next]) {
        if (m) remember(cursorKey(search, m.id), m.cursor);
      }
      index.value = data.rank;
      total.value = data.total;
      previousMachine.value = data.previous;
      nextMachine.value = data.next;
    } catch {
      // Neighbours are a convenience: a failed lookup hides the arrows rather
      // than putting an error over a fiche that loaded perfectly well.
      if (id !== resolutionId) return;
      previousMachine.value = null;
      nextMachine.value = null;
      total.value = null;
    }
  }

  function go(machine: MachineNeighbour | null, rank: number) {
    if (!machine) return;
    // The tab travels with the walk: comparing the hardware of ten postes in a
    // row is exactly what the arrows are for, and landing on « Identité » each
    // time would cost a click per poste.
    const tab = queryValue(route.query.tab);
    void router.push({
      name: 'machine-detail',
      params: { id: machine.id },
      query: { ...backQuery.value, ...(tab ? { tab } : {}), i: String(rank) },
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

  // Re-resolved when the poste, its rank or the search changes: moving to the
  // next poste is a route change on the same component, so nothing else would
  // refresh the arrows. A tab of the fiche changes the URL too, and nothing
  // here: asking again would only disable the arrows for a round trip.
  watch(
    () => JSON.stringify([route.params.id ?? null, queryValue(route.query.i), searchKey()]),
    () => void resolve(),
    { immediate: true },
  );

  // The fiche closes: an answer still on its way is for nobody.
  onScopeDispose(() => {
    resolutionId += 1;
  });

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

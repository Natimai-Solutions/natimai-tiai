import { computed, onScopeDispose, ref, watch, type Ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { listMachines, type Machine } from 'src/services/machines';
import { DEFAULT_PAGE_SIZE, machineListParamsFromQuery, queryValue } from 'src/utils/machineQuery';

/**
 * Walk the search results from inside a poste's fiche.
 *
 * The list page hands over its whole query plus the row's absolute rank (`i`)
 * when opening a poste. From that, this resolves the neighbours by asking the
 * server for the block of the search around `i` — not by carrying the list in
 * a store. The reason is the same one that put pagination server-side: the
 * fleet does not fit in the client, and a fiche reached from a pasted URL or a
 * reloaded tab has no store to read anyway. A block of rows now and then is a
 * cheaper price than a list that is wrong after a refresh.
 *
 * With no `i` in the URL — a fiche opened from the dashboard, a bookmark, a
 * merge redirect — there is no search to walk and everything here is null: the
 * arrows simply do not render.
 *
 * The order is frozen at first read (audit B18): the list's default sort is
 * the last contact, which every heartbeat changes, so the poste at rank i+1
 * a minute later is not the one that followed. The ranks are read in blocks
 * of BLOCK rows, kept for the session, and the walk goes through that
 * snapshot — the order the reader saw, not the order of the moment.
 *
 * Each block is read when the walk first reaches it, not all at once, so the
 * server's order may have moved between two blocks: a poste already in the
 * snapshot can come back in the next block, one rank lower. The snapshot
 * holds every poste once — a block is appended (or prepended) minus the
 * postes it already holds, so the walk never shows the same poste twice.
 * A poste that moved into a block already read is not seen again: losing one
 * from the walk is the lesser evil next to showing one twice.
 *
 * Ranks are the server's for the first block read, and counted from it for
 * the blocks read after — until the run reaches the start of the search,
 * where the first poste held is rank 0 whatever the count made of it.
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

const BLOCK = 50;

/**
 * How far to look for the opened poste when it is not at the rank the list
 * gave (the list may have been read 90 s earlier): 2,000 rows in all beyond
 * the first block read — before and after it together, not on each side —
 * and once per poste and per search, however many times the fiche asks.
 * Past that, no position and no neighbours rather than wrong ones.
 */
const MAX_SCAN_ROWS = 2000;
const MAX_SCAN_BLOCKS = MAX_SCAN_ROWS / BLOCK;

/**
 * One resolution's leave to read: withdrawn when the fiche shows another
 * poste or closes, so a scan nobody waits for stops at the next block.
 */
interface Scan {
  stopped: boolean;
}

/**
 * The frozen order of one search. Ranks `first`..`last` are held, each poste
 * once; `firstBlock`..`lastBlock` are the server pages they were read from.
 * The ranks of the first block read are the server's; the blocks read after
 * it extend the run on either side, so a rank stays what the URL says it is.
 */
interface Snapshot {
  rows: Map<number, Machine>;
  ranks: Map<string, number>;
  total: number;
  first: number;
  last: number;
  /** -1 until the first block is read. */
  firstBlock: number;
  lastBlock: number;
  /** Reads are chained: two blocks extending the run at once would interleave. */
  queue: Promise<unknown>;
  /**
   * The postes looked for and not found, by id: how many blocks were read
   * for each. Kept with the snapshot, so that coming back to the fiche does
   * not send the same forty requests again, and a search cut short resumes
   * with what is left of its budget.
   */
  searches: Map<string, number>;
}

// One snapshot per search, for the life of the tab: walking back and forth
// must see the same order. Bounded, a console session opens a few searches.
const snapshots = new Map<string, Snapshot>();
const MAX_SNAPSHOTS = 20;

/** Forget every frozen order (tests; a new search is a new key anyway). */
export function resetMachineNavigation(): void {
  snapshots.clear();
}

function blockCount(snap: Snapshot): number {
  return Math.ceil(snap.total / BLOCK);
}

function canGrowForward(snap: Snapshot): boolean {
  return snap.lastBlock + 1 < blockCount(snap);
}

function canGrowBackward(snap: Snapshot): boolean {
  return snap.firstBlock > 0 && snap.first > 0;
}

/**
 * The size of the search as the reader is shown it: the server's last count,
 * and never less than the frozen order holds — a rank cannot exceed it.
 */
function shownTotal(snap: Snapshot): number {
  return Math.max(snap.total, snap.last + 1);
}

/**
 * The run has reached the start of the search: its first poste is rank 0.
 * Counting down from a later block can leave it higher — a poste removed
 * before the cursor since, and the first poste would read « Poste 2 ».
 */
function settleStart(snap: Snapshot): void {
  const shift = snap.first;
  if (snap.firstBlock !== 0 || shift <= 0) return;
  const rows = new Map<number, Machine>();
  for (const [rank, m] of snap.rows) rows.set(rank - shift, m);
  snap.rows = rows;
  for (const [id, rank] of snap.ranks) snap.ranks.set(id, rank - shift);
  snap.first = 0;
  snap.last -= shift;
}

/** Run `task` after every read already queued on this snapshot. */
function serialize<T>(snap: Snapshot, task: () => Promise<T>): Promise<T> {
  const run = snap.queue.then(task);
  // The chain survives a failed read: the next caller tries again.
  snap.queue = run.catch(() => undefined);
  return run;
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

  /** The search this fiche was opened from, as a snapshot key. */
  function snapshotKey(): string {
    const params = machineListParamsFromQuery(route.query);
    return JSON.stringify(Object.entries(params).sort(([a], [b]) => a.localeCompare(b)));
  }

  function snapshot(): Snapshot {
    const key = snapshotKey();
    let snap = snapshots.get(key);
    if (!snap) {
      if (snapshots.size >= MAX_SNAPSHOTS) {
        const oldest = snapshots.keys().next().value;
        if (oldest !== undefined) snapshots.delete(oldest);
      }
      snap = {
        rows: new Map(),
        ranks: new Map(),
        total: 0,
        first: 0,
        last: -1,
        firstBlock: -1,
        lastBlock: -1,
        queue: Promise.resolve(),
        searches: new Map(),
      };
      snapshots.set(key, snap);
    }
    return snap;
  }

  // The search is read from the query the resolution started with: a block
  // that answers after the reader has left must not be asked with another.
  async function fetchBlock(
    snap: Snapshot,
    params: ReturnType<typeof machineListParamsFromQuery>,
    b: number,
  ): Promise<Machine[]> {
    const data = await listMachines({ ...params, page: b + 1, page_size: BLOCK });
    snap.total = data.total;
    return data.items;
  }

  function hold(snap: Snapshot, rank: number, m: Machine) {
    snap.rows.set(rank, m);
    snap.ranks.set(m.id, rank);
  }

  /**
   * One reader of a snapshot, bound to the search's params. Every function
   * here runs inside `serialize`: one block at a time per snapshot.
   */
  function reader(snap: Snapshot, params: ReturnType<typeof machineListParamsFromQuery>) {
    /**
     * The first block read: its postes at the server's ranks. A rank past the
     * end of the search — a URL kept from a longer one — has no block: the
     * run then starts from the last block that exists, numbered from what was
     * actually read, instead of counting down from a rank nobody holds.
     */
    async function readFirst(b: number) {
      let items = await fetchBlock(snap, params, b);
      const lastExisting = blockCount(snap) - 1;
      if (!items.length && lastExisting < b) {
        // (An empty search has no block at all: nothing more to ask for.)
        b = Math.max(0, lastExisting);
        if (lastExisting >= 0) items = await fetchBlock(snap, params, b);
      }
      snap.first = b * BLOCK;
      snap.last = snap.first - 1;
      for (const m of items) {
        if (snap.ranks.has(m.id)) continue;
        hold(snap, ++snap.last, m);
      }
      snap.firstBlock = b;
      snap.lastBlock = b;
    }

    /** The next block, after the run, minus the postes already held. */
    async function growForward() {
      const items = await fetchBlock(snap, params, snap.lastBlock + 1);
      for (const m of items) {
        if (snap.ranks.has(m.id)) continue;
        hold(snap, ++snap.last, m);
      }
      snap.lastBlock += 1;
    }

    /**
     * The previous block, before the run, minus the postes already held. Never
     * below rank 0: the run starts at most a block's worth of new postes past
     * the start of its first block.
     */
    async function growBackward() {
      const items = await fetchBlock(snap, params, snap.firstBlock - 1);
      for (let k = items.length - 1; k >= 0 && snap.first > 0; k--) {
        const m = items[k]!;
        if (snap.ranks.has(m.id)) continue;
        hold(snap, --snap.first, m);
      }
      snap.firstBlock -= 1;
      settleStart(snap);
    }

    /**
     * The rank of poste `id` in the frozen order, or null when it is not
     * within reach. `rank` is where the URL says it is: the first block read
     * is that one. Then the blocks on either side — alternately, since a
     * heartbeat moves a poste up the default order and a deleted poste moves
     * the others down — up to MAX_SCAN_ROWS in all.
     * (A poste that moved into a block already read is not seen again: known,
     * and accepted — see the top of this file.)
     */
    async function find(id: string, rank: number, scan: Scan): Promise<number | null> {
      if (scan.stopped) return snap.ranks.get(id) ?? null;
      if (snap.firstBlock < 0) await readFirst(Math.floor(rank / BLOCK));
      let forward = true;
      while (!scan.stopped && !snap.ranks.has(id)) {
        const reads = snap.searches.get(id) ?? 0;
        const ahead = canGrowForward(snap);
        const behind = canGrowBackward(snap);
        if (reads >= MAX_SCAN_BLOCKS || (!ahead && !behind)) break;
        snap.searches.set(id, reads + 1);
        if ((forward && ahead) || !behind) await growForward();
        else await growBackward();
        forward = !forward;
      }
      const found = snap.ranks.get(id);
      if (found === undefined) return null;
      snap.searches.delete(id);
      return found;
    }

    /**
     * Poste `id`, held, with the poste before and the poste after it — read
     * if the run stops short of either. Its rank is read again after every
     * block: the run reaching the start of the search can renumber it.
     */
    async function around(id: string, scan: Scan) {
      const at = () => snap.ranks.get(id)!;
      let reads = 0;
      while (
        !scan.stopped &&
        at() - 1 < snap.first &&
        canGrowBackward(snap) &&
        reads++ < MAX_SCAN_BLOCKS
      ) {
        await growBackward();
      }
      while (
        !scan.stopped &&
        at() + 1 > snap.last &&
        canGrowForward(snap) &&
        reads++ < MAX_SCAN_BLOCKS
      ) {
        await growForward();
      }
      return {
        at: at(),
        before: snap.rows.get(at() - 1) ?? null,
        after: snap.rows.get(at() + 1) ?? null,
      };
    }

    return { find, around };
  }

  // Which resolution is the current one. Two round trips separate a click on ▶
  // from knowing the new neighbours; without this, a second click in that
  // window would walk to the *previous* poste's neighbour — landing on the same
  // machine again while the rank moved on, desynchronising the two for good.
  let resolutionId = 0;
  let scan: Scan = { stopped: false };

  function clear() {
    index.value = null;
    total.value = null;
    previousMachine.value = null;
    nextMachine.value = null;
  }

  async function resolve() {
    const id = ++resolutionId;
    // Whatever the previous resolution was still reading, nobody waits for.
    scan.stopped = true;
    const mine: Scan = (scan = { stopped: false });
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
    const snap = snapshot();
    const read = reader(snap, machineListParamsFromQuery(route.query));
    try {
      // Opened from a list read before the order moved, the poste is not at
      // the rank given: it is found in the snapshot, and the walk goes from
      // where it really is.
      const place = await serialize(snap, async () =>
        (await read.find(current, rank, mine)) === null ? null : read.around(current, mine),
      );
      if (id !== resolutionId) return;
      if (place === null) {
        // Not within reach: neighbours and a position read around the given
        // rank would belong to other postes (audit B18). The arrows stay
        // disabled and the position unsaid.
        total.value = null;
        return;
      }
      index.value = place.at;
      previousMachine.value = place.before;
      nextMachine.value = place.after;
      total.value = shownTotal(snap);
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
  // here: resolving again would only repeat a scan that found nothing.
  watch(
    () => JSON.stringify([route.params.id ?? null, queryValue(route.query.i), snapshotKey()]),
    () => void resolve(),
    { immediate: true },
  );

  // The fiche closes: what is still being read is for nobody.
  onScopeDispose(() => {
    resolutionId += 1;
    scan.stopped = true;
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

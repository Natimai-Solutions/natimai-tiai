import { computed, ref, watch, type Ref } from 'vue';
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
 * gave (the list may have been read 90 s earlier), and how far one step of the
 * walk may read ahead. Past that, no position and no neighbours rather than
 * wrong ones.
 */
const MAX_SCAN_ROWS = 2000;
const MAX_SCAN_BLOCKS = MAX_SCAN_ROWS / BLOCK;

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

  function snapshot(): Snapshot {
    const params = machineListParamsFromQuery(route.query);
    const key = JSON.stringify(Object.entries(params).sort(([a], [b]) => a.localeCompare(b)));
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
      };
      snapshots.set(key, snap);
    }
    return snap;
  }

  async function fetchBlock(snap: Snapshot, b: number): Promise<Machine[]> {
    const data = await listMachines({
      ...machineListParamsFromQuery(route.query),
      page: b + 1,
      page_size: BLOCK,
    });
    snap.total = data.total;
    return data.items;
  }

  function hold(snap: Snapshot, rank: number, m: Machine) {
    snap.rows.set(rank, m);
    snap.ranks.set(m.id, rank);
  }

  /** The first block read: its postes at the server's ranks. */
  async function readFirst(snap: Snapshot, b: number) {
    const items = await fetchBlock(snap, b);
    if (snap.firstBlock >= 0) return; // Read meanwhile by a call queued first.
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
  async function growForward(snap: Snapshot) {
    const items = await fetchBlock(snap, snap.lastBlock + 1);
    for (const m of items) {
      if (snap.ranks.has(m.id)) continue;
      hold(snap, ++snap.last, m);
    }
    snap.lastBlock += 1;
  }

  /**
   * The previous block, before the run, minus the postes already held. Never
   * below rank 0: the run starts at most a block's worth of new postes past the
   * start of its first block.
   */
  async function growBackward(snap: Snapshot) {
    const items = await fetchBlock(snap, snap.firstBlock - 1);
    for (let k = items.length - 1; k >= 0 && snap.first > 0; k--) {
      const m = items[k]!;
      if (snap.ranks.has(m.id)) continue;
      hold(snap, --snap.first, m);
    }
    snap.firstBlock -= 1;
  }

  /** The row at rank `rank` in the frozen order, or null past either end. */
  function rowAt(snap: Snapshot, rank: number): Promise<Machine | null> {
    if (rank < 0) return Promise.resolve(null);
    const held = snap.rows.get(rank);
    if (held) return Promise.resolve(held);
    return serialize(snap, async () => {
      if (snap.firstBlock < 0) await readFirst(snap, Math.floor(rank / BLOCK));
      let reads = 0;
      while (rank > snap.last && canGrowForward(snap) && reads++ < MAX_SCAN_BLOCKS) {
        await growForward(snap);
      }
      while (rank < snap.first && canGrowBackward(snap) && reads++ < MAX_SCAN_BLOCKS) {
        await growBackward(snap);
      }
      return snap.rows.get(rank) ?? null;
    });
  }

  /**
   * The rank of poste `id` in the frozen order, reading further blocks on
   * either side — alternately, since a heartbeat moves a poste up the default
   * order and a deleted poste moves the others down — up to MAX_SCAN_ROWS.
   * Null when it is not found there.
   */
  function rankOf(snap: Snapshot, id: string): Promise<number | null> {
    const held = snap.ranks.get(id);
    if (held !== undefined) return Promise.resolve(held);
    return serialize(snap, async () => {
      let forward = true;
      for (let reads = 0; reads < MAX_SCAN_BLOCKS; reads++) {
        const found = snap.ranks.get(id);
        if (found !== undefined) return found;
        const ahead = canGrowForward(snap);
        const behind = canGrowBackward(snap);
        if (!ahead && !behind) return null;
        if ((forward && ahead) || !behind) await growForward(snap);
        else await growBackward(snap);
        forward = !forward;
      }
      return snap.ranks.get(id) ?? null;
    });
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
    const snap = snapshot();
    try {
      let at = rank;
      const here = await rowAt(snap, rank);
      const current = String(route.params.id ?? '');
      if (current && here?.id !== current) {
        // Opened from a list read before the order moved: find the poste in
        // the snapshot, and walk from where it really is.
        const found = await rankOf(snap, current);
        if (found === null) {
          // Not within reach: neighbours and a position read around the
          // given rank would belong to other postes (audit B18). The arrows
          // stay disabled and the position unsaid.
          if (id !== resolutionId) return;
          previousMachine.value = null;
          nextMachine.value = null;
          total.value = null;
          return;
        }
        at = found;
      }
      const [before, after] = await Promise.all([rowAt(snap, at - 1), rowAt(snap, at + 1)]);
      if (id !== resolutionId) return;
      index.value = at;
      previousMachine.value = before;
      nextMachine.value = after;
      total.value = snap.total;
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

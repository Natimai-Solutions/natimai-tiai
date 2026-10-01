import { ref } from 'vue';
import {
  listAgentVersions,
  listAntivirusProducts,
  listChassisTypes,
  listLocations,
  listManufacturers,
  listModels,
  listOsVersions,
  listProcessors,
  type FleetValue,
} from 'src/services/machines';
import { getRoomConfig, listBuildings, listRooms, roomLabel, type Room } from 'src/services/rooms';
import { CHASSIS_TYPES } from 'src/utils/machineQuery';
import {
  AGENT_OUTDATED,
  ROOM_NONE,
  initialFleetOptions,
  type MachineFleetOptions,
} from 'src/utils/machineListFilters';

/** The chassis kind in the console's words — the fleet reports the raw key. */
export function chassisLabelOf(name: string): string {
  return CHASSIS_TYPES.find((c) => c.value === name)?.label ?? name;
}

/**
 * The machine list's dropdowns that are filled from the fleet, and the rooms
 * the console holds — loaded once with the page.
 *
 * Every listing degrades on its own: a filter that failed to populate must not
 * blank the machine list, so a failed listing leaves its « Tous » entry alone
 * (the filter is still typeable in the URL) and says nothing.
 */
export function useMachineFleetOptions() {
  const options = ref<MachineFleetOptions>(initialFleetOptions());
  const rooms = ref<Room[]>([]);
  // Moving postes by hand needs a server not in a directory mode. Assumed
  // manual until said otherwise: the worst case is a 409 the notification
  // explains.
  const manualMode = ref(true);

  /**
   * Fill one inventory dropdown from a fleet listing: what a parc contains is
   * data, and the counts double as an inventory the renewal plan is read off.
   */
  async function loadFleet(
    key: keyof MachineFleetOptions,
    fetch: () => Promise<FleetValue[]>,
    labelOf: (name: string) => string = (name) => name,
  ) {
    try {
      const values = await fetch();
      const all = options.value[key][0]!;
      options.value[key] = [
        all,
        ...values.map((v) => ({ label: `${labelOf(v.name)} (${v.count})`, value: v.name })),
      ];
    } catch {
      // See above.
    }
  }

  // The products installed are data, not a list the console can know in
  // advance. The count sits in the label so the dropdown doubles as an
  // inventory of a mixed parc.
  async function loadAntivirus() {
    try {
      const products = await listAntivirusProducts();
      options.value.antivirus = [
        { label: 'Tous les antivirus', value: null },
        ...products.map((p) => ({ label: `${p.name} (${p.count})`, value: p.name })),
      ];
    } catch {
      // The dropdown simply keeps its « Tous les antivirus » entry.
    }
  }

  // The versions installed are data too; the count doubles as a migration
  // progress bar.
  async function loadOs() {
    try {
      const versions = await listOsVersions();
      options.value.os = [
        { label: 'Tous les OS', value: null },
        ...versions.map((v) => ({ label: `${v.name} (${v.count})`, value: v.name })),
      ];
    } catch {
      // Degrades to « Tous les OS ».
    }
  }

  // The versions running, and the counts as the deployment's progress bar.
  // « Obsolète » first, because it is the entry reached for the morning after
  // a push.
  async function loadAgent() {
    try {
      const fleet = await listAgentVersions();
      const behind = fleet.versions.filter((v) => v.outdated).reduce((n, v) => n + v.count, 0);
      options.value.agent = [
        { label: 'Agent : toutes versions', value: null },
        { label: `Agent obsolète (${behind})`, value: AGENT_OUTDATED },
        ...fleet.versions.map((v) => ({
          label: `Agent ${v.name}${v.name === fleet.latest ? ' · référence' : ''} (${v.count})`,
          value: v.name,
        })),
      ];
    } catch {
      // Degrades to « toutes versions ».
    }
  }

  /**
   * The rooms and buildings, for their two dropdowns and for « Affecter à une
   * salle ». The room entries carry their building so two « B12 » read apart.
   */
  async function loadRooms() {
    try {
      manualMode.value = (await getRoomConfig()).manual;
    } catch {
      // Assumed manual, see above.
    }
    try {
      rooms.value = await listRooms();
      options.value.room = [
        { label: 'Toutes les salles', value: null },
        { label: 'Sans salle', value: ROOM_NONE },
        ...rooms.value.map((r) => ({
          label: `${roomLabel(r)} (${r.machine_count})`,
          value: r.id,
        })),
      ];
      const buildings = await listBuildings();
      options.value.building = [
        { label: 'Tous les bâtiments', value: null },
        ...buildings.map((b) => ({
          label: `${b.name}${b.location ? ` — ${b.location}` : ''} (${b.machine_count})`,
          value: b.id,
        })),
      ];
    } catch {
      // The list still works without the two dropdowns.
    }
  }

  /** Every listing at once, each on its own. */
  function loadAll() {
    void loadAntivirus();
    void loadOs();
    void loadAgent();
    // The sites are whatever the deployments wrote in their agents'
    // configuration, and the counts are a head count per site.
    void loadFleet('location', listLocations);
    void loadRooms();
    void loadFleet('model', listModels);
    void loadFleet('manufacturer', listManufacturers);
    void loadFleet('processor', listProcessors);
    void loadFleet('chassis', listChassisTypes, chassisLabelOf);
  }

  return { options, rooms, manualMode, loadAll, loadRooms };
}

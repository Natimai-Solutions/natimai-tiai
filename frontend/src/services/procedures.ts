import { api } from 'boot/axios';

/**
 * Procedure notes per hardware model (C11, dev/plan-procedures-pieces-jointes.md
 * §3): one plain-text note per `hw_model`, shown on the page of every poste
 * of that model. Read with `procedure:read`; written with `procedure:write`
 * by the accounts that see every poste only (`procedure.scope_limited`
 * otherwise). An edit or a deletion names the version it was made from
 * (`expected_updated_at`): another's change in between is `procedure.changed`.
 */

export interface Procedure {
  id: string;
  hw_model: string;
  body: string;
  created_by: string;
  created_at: string;
  updated_by: string;
  updated_at: string;
}

export interface ProcedureListItem extends Procedure {
  /** Postes of the model in the caller's scope, retired ones excluded. */
  machine_count: number;
}

export interface MachineProcedure {
  /** Null when the inventory has not reported one. */
  hw_model: string | null;
  procedure: Procedure | null;
  /** The account is confined to some sites: it reads, never writes.
   * Absent from a server older than the console: read as not confined. */
  scope_limited?: boolean;
}

/** The note's longest text, as the server bounds it. */
export const PROCEDURE_BODY_MAX = 5000;

export async function getMachineProcedure(machineId: string): Promise<MachineProcedure> {
  const { data } = await api.get<MachineProcedure>(`/machines/${machineId}/procedure`);
  return data;
}

export async function listProcedures(): Promise<ProcedureListItem[]> {
  const { data } = await api.get<ProcedureListItem[]>('/procedures');
  return data;
}

export async function createProcedure(hwModel: string, body: string): Promise<Procedure> {
  const { data } = await api.post<Procedure>('/procedures', { hw_model: hwModel, body });
  return data;
}

export async function updateProcedure(
  id: string,
  body: string,
  expectedUpdatedAt: string,
): Promise<Procedure> {
  const { data } = await api.patch<Procedure>(`/procedures/${id}`, {
    body,
    expected_updated_at: expectedUpdatedAt,
  });
  return data;
}

export async function deleteProcedure(id: string, expectedUpdatedAt: string): Promise<void> {
  await api.delete(`/procedures/${id}`, { params: { expected_updated_at: expectedUpdatedAt } });
}

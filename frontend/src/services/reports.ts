import { api } from 'boot/axios';
import type { CheckPriority } from 'src/services/checks';

/**
 * Reports (C4): what somebody in front of a poste, without an account, says
 * is wrong — left through the label's QR code — and the queue the
 * technicians sort into verifications.
 */

export interface ReportForm {
  enabled: boolean;
  categories: string[];
}

export interface ReportIn {
  category: string;
  text: string;
  contact?: string | null;
  language?: 'fr' | 'en';
}

export interface Report {
  id: string;
  asset_id: string | null;
  machine_id: string | null;
  subject: string | null;
  room_name: string | null;
  building_name: string | null;
  category: string;
  text: string;
  contact: string | null;
  language: string | null;
  status: 'new' | 'converted' | 'attached' | 'closed' | 'rejected';
  created_at: string;
  handled_at: string | null;
  handled_by: string | null;
  handling_note: string | null;
  check_id: string | null;
  open_check_id: string | null;
}

export interface ReportList {
  items: Report[];
  total: number;
  page: number;
  page_size: number;
  new: number;
  enabled: boolean;
}

export async function getReportForm(token: string): Promise<ReportForm> {
  const { data } = await api.get<ReportForm>(`/public/reports/${encodeURIComponent(token)}`);
  return data;
}

export async function submitReport(token: string, payload: ReportIn): Promise<void> {
  await api.post(`/public/reports/${encodeURIComponent(token)}`, payload);
}

export async function listReports(
  params: { state?: 'new' | 'handled' | 'all'; page?: number; page_size?: number } = {},
): Promise<ReportList> {
  const { data } = await api.get<ReportList>('/reports', { params });
  return data;
}

export async function convertReport(
  id: string,
  payload: { assigned_to_id?: string | null; priority?: CheckPriority; due_date?: string | null },
): Promise<Report> {
  const { data } = await api.post<Report>(`/reports/${id}/convert`, payload);
  return data;
}

export async function attachReport(id: string): Promise<Report> {
  const { data } = await api.post<Report>(`/reports/${id}/attach`);
  return data;
}

export async function closeReport(
  id: string,
  note: string | null,
  reject: boolean,
): Promise<Report> {
  const { data } = await api.post<Report>(
    `/reports/${id}/close`,
    { note },
    { params: reject ? { reject: true } : {} },
  );
  return data;
}

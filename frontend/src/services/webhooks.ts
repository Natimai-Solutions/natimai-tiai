import { api } from 'boot/axios';

/** Outbound webhooks (plan `dev/plan-webhooks-jetons.md`, C8). */

export const WEBHOOK_EVENTS = [
  'threat.detected',
  'alert.opened',
  'alert.resolved',
  'check.created',
  'check.closed',
  'command.failed',
] as const;
export type WebhookEvent = (typeof WEBHOOK_EVENTS)[number];
export const WEBHOOK_FORMATS = ['json', 'teams', 'mattermost'] as const;
export type WebhookFormat = (typeof WEBHOOK_FORMATS)[number];

export interface Webhook {
  id: string;
  name: string;
  url: string;
  format: WebhookFormat;
  language: 'fr' | 'en';
  events: string[];
  enabled: boolean;
  created_by: string;
  created_at: string;
  updated_at: string;
  last_success_at: string | null;
  last_failure_at: string | null;
  last_error: string | null;
  consecutive_failures: number;
  pending: number;
}

/** Returned at creation and at each renewal of the secret, never otherwise. */
export interface WebhookWithSecret extends Webhook {
  secret: string;
}

export interface WebhookFields {
  name: string;
  url: string;
  format: WebhookFormat;
  language: 'fr' | 'en';
  events: WebhookEvent[];
  enabled: boolean;
}

export interface WebhookDelivery {
  id: string;
  event: string;
  status: 'pending' | 'sent' | 'failed';
  attempts: number;
  response_status: number | null;
  last_error: string | null;
  created_at: string;
  sent_at: string | null;
  next_attempt_at: string;
}

export interface WebhookTest {
  ok: boolean;
  response_status: number | null;
  error: string | null;
}

export async function listWebhooks(): Promise<Webhook[]> {
  const { data } = await api.get<Webhook[]>('/webhooks');
  return data;
}

export async function createWebhook(fields: WebhookFields): Promise<WebhookWithSecret> {
  const { data } = await api.post<WebhookWithSecret>('/webhooks', fields);
  return data;
}

export async function updateWebhook(id: string, fields: Partial<WebhookFields>): Promise<Webhook> {
  const { data } = await api.patch<Webhook>(`/webhooks/${id}`, fields);
  return data;
}

export async function deleteWebhook(id: string): Promise<void> {
  await api.delete(`/webhooks/${id}`);
}

export async function renewWebhookSecret(id: string): Promise<WebhookWithSecret> {
  const { data } = await api.post<WebhookWithSecret>(`/webhooks/${id}/secret`);
  return data;
}

export async function testWebhook(id: string): Promise<WebhookTest> {
  const { data } = await api.post<WebhookTest>(`/webhooks/${id}/test`);
  return data;
}

export async function listWebhookDeliveries(id: string): Promise<WebhookDelivery[]> {
  const { data } = await api.get<WebhookDelivery[]>(`/webhooks/${id}/deliveries`);
  return data;
}

// Shared steps: the administrator the stack seeds at start-up, and agents
// enrolled through the real enrollment endpoint — the console has nothing to
// show until a poste has reported.
import { expect, type APIRequestContext, type Page } from '@playwright/test';

export const ADMIN_EMAIL = process.env.E2E_ADMIN_EMAIL ?? 'admin@natimai.solutions';
export const ADMIN_PASSWORD = process.env.E2E_ADMIN_PASSWORD ?? 'changeme-strong-admin-password';
const ENROLLMENT_SECRET = process.env.E2E_ENROLLMENT_SECRET ?? 'changeme-shared-enrollment-secret';

/** Log in through the form, as a person would, and wait for the dashboard. */
export async function login(page: Page): Promise<void> {
  await page.goto('/login');
  await page.getByLabel('E-mail').fill(ADMIN_EMAIL);
  await page.getByLabel('Mot de passe', { exact: true }).fill(ADMIN_PASSWORD);
  await page.getByRole('button', { name: 'Se connecter' }).click();
  await expect(page.getByText('Tableau de bord').first()).toBeVisible();
}

/**
 * Enroll a poste and send one heartbeat, with Defender up to date. Unique per
 * run: the database outlives a test, and a hostname seen twice would make the
 * assertions ambiguous.
 */
export async function enrollPoste(
  request: APIRequestContext,
  hostname: string,
): Promise<{ machineId: string; token: string }> {
  const enroll = await request.post('/api/v1/agent/enroll', {
    headers: { 'X-Enrollment-Secret': ENROLLMENT_SECRET },
    data: { machine_uuid: `e2e-${hostname}`, hostname, location: 'Lycée e2e' },
  });
  expect(enroll.ok(), await enroll.text()).toBeTruthy();
  const { machine_id: machineId, token } = (await enroll.json()) as {
    machine_id: string;
    token: string;
  };
  const beat = await request.post('/api/v1/agent/heartbeat', {
    headers: { Authorization: `Bearer ${token}` },
    data: {
      hostname,
      agent_version: '1.1.0',
      defender: { av_enabled: true, rtp_enabled: true, signature_age_days: 0 },
    },
  });
  expect(beat.ok(), await beat.text()).toBeTruthy();
  return { machineId, token };
}

/** A name no earlier run has used. */
export function uniqueName(prefix: string): string {
  return `${prefix}-${Date.now().toString(36)}`;
}

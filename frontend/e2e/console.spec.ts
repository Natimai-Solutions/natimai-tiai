// The console's critical paths, end to end. Each test starts from a fresh
// browser context: no session carried from one to the next.
import { expect, test } from '@playwright/test';
import { enrollPoste, login, uniqueName } from './fixtures';

test('une session survit au rechargement et la déconnexion la ferme vraiment', async ({ page }) => {
  await login(page);

  // The access token lives in memory only: a reload keeps the user logged in
  // through the session cookie and the silent refresh.
  await page.reload();
  await expect(page.getByText('Tableau de bord').first()).toBeVisible();
  await expect(page).not.toHaveURL(/\/login/);

  await page.getByRole('button', { name: 'Déconnexion' }).click();
  await expect(page).toHaveURL(/\/login/);

  // Server-side logout: the cookie is gone *and* the session is revoked, so
  // going back to a protected page lands on the login form again.
  await page.goto('/machines');
  await expect(page).toHaveURL(/\/login/);
});

test('un poste enrôlé apparaît dans la liste et reçoit une commande depuis sa fiche', async ({
  page,
  request,
}) => {
  const hostname = uniqueName('PC-E2E');
  await enrollPoste(request, hostname);
  await login(page);

  await page.goto(`/machines?search=${hostname}`);
  const row = page.getByRole('row', { name: new RegExp(hostname) });
  await expect(row).toBeVisible();
  await row.click();

  await expect(page.getByText(hostname).first()).toBeVisible();
  await page.getByRole('button', { name: 'Action' }).click();
  // Quasar gives a clickable list entry the button role.
  await page.locator('.q-menu').getByRole('button', { name: 'Scan rapide', exact: true }).click();

  await expect(page.getByText('Commande envoyée')).toBeVisible();

  // The command row the fiche reads back from the API, in its own tab.
  await page.getByRole('tab', { name: 'Commandes' }).click();
  await expect(page.getByRole('cell', { name: /Scan rapide/ }).first()).toBeVisible();
});

test("le journal d'audit montre une action d'administration", async ({ page, request }) => {
  const hostname = uniqueName('PC-AUDIT');
  const { machineId } = await enrollPoste(request, hostname);
  await login(page);

  await page.goto(`/machines/${machineId}`);
  await page.getByRole('button', { name: 'Révoquer le token' }).click();
  // Quasar's confirmation dialog: its accept button is « OK ».
  await page.getByRole('dialog').getByRole('button', { name: 'OK' }).click();
  await expect(page.getByText('Token révoqué')).toBeVisible();

  await page.goto('/audit?action=machine.revoke_token');
  await expect(page.getByRole('cell', { name: /Révocation du token/ }).first()).toBeVisible();
  await expect(page.getByText(hostname).first()).toBeVisible();
});

test('un seuil enregistré dans les paramètres est relu après rechargement', async ({ page }) => {
  await login(page);
  await page.goto('/settings');

  const field = page.getByLabel('Poste inactif après');
  const value = String(20 + Math.floor(Math.random() * 60));
  await field.fill(value);
  const card = page.locator('.q-card', { hasText: 'Supervision du parc' });
  await card.getByRole('button', { name: 'Enregistrer' }).click();
  await expect(page.getByText('Paramètres enregistrés')).toBeVisible();

  await page.reload();
  await expect(page.getByLabel('Poste inactif après')).toHaveValue(value);
});

// The console's language, end to end: a reader whose browser speaks English
// gets the console in English, and the choice made in « Mon compte » wins
// over the browser, at once and after a reload. The account is left as found
// (« follow the browser »), since the other scenarios read the console in
// French with a French browser.
import { expect, test } from '@playwright/test';
import { ADMIN_EMAIL, ADMIN_PASSWORD } from './fixtures';

test.use({ locale: 'en-GB' });

test('an English browser gets English, and the account’s choice wins over it', async ({ page }) => {
  await page.goto('/login');
  await page.getByLabel('Email').fill(ADMIN_EMAIL);
  await page.getByLabel('Password', { exact: true }).fill(ADMIN_PASSWORD);
  await page.getByRole('button', { name: 'Sign in' }).click();
  await expect(page.getByText('Dashboard').first()).toBeVisible();
  await expect(page.locator('html')).toHaveAttribute('lang', /^en/);

  try {
    await page.goto('/account');
    const card = page.locator('[data-test="language-card"]');
    await card.getByRole('radio', { name: 'Français' }).click();
    // At once, without a reload: the page, the menu and the tab's title.
    await expect(page.getByRole('heading', { name: 'Mon compte' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Déconnexion' })).toBeVisible();
    await expect(page.locator('html')).toHaveAttribute('lang', 'fr');

    // Stored on the account: a reload in the same English browser stays French.
    await page.reload();
    await expect(page.getByRole('heading', { name: 'Mon compte' })).toBeVisible();
  } finally {
    // Back to « follow the browser », as the account was.
    await page.goto('/account');
    await page
      .locator('[data-test="language-card"]')
      .getByRole('radio', { name: /Celle du navigateur|Same as the browser/ })
      .click();
  }
  await expect(page.getByRole('heading', { name: 'My account' })).toBeVisible();
});

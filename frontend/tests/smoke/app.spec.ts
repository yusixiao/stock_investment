import { expect, test } from '@playwright/test';

test('opens the backtest workbench from the root route', async ({ page }) => {
  await page.goto('/');

  await expect(page).toHaveURL(/\/backtest$/);
  await expect(page.getByText('回测平台')).toBeVisible();
  await expect(page.getByRole('tab', { name: '策略回测' })).toBeVisible();
});

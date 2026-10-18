import { expect, test, type Page } from '@playwright/test';

// These match docker-compose.e2e.yml.
const EMAIL = 'e2e@example.com';
const PASSWORD = 'e2e-password-123';
const MOCK = 'http://mock-services:8000';

// Set E2E_SCREENSHOTS=<dir> to also save the pictures used in the documentation.
const SHOTS = process.env.E2E_SCREENSHOTS;

async function shot(page: Page, name: string): Promise<void> {
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/${name}.png` });
}

async function signIn(page: Page): Promise<void> {
  await page.goto('/login');
  await page.getByPlaceholder('Email address').fill(EMAIL);
  await page.getByPlaceholder('Password').fill(PASSWORD);
  await page.getByRole('button', { name: 'Sign in' }).click();
  await expect(page.getByRole('navigation', { name: 'Main' })).toBeVisible();
}

test('a clean install makes a published episode that is in the feed', async ({ page, request }) => {
  // The page runs under a strict Content-Security-Policy (docker/nginx.conf): nothing may be blocked.
  const blocked: string[] = [];
  page.on('console', (message) => {
    if (/content security policy|refused to/i.test(message.text())) blocked.push(message.text());
  });
  page.on('pageerror', (error) => blocked.push(error.message));

  await signIn(page);

  // A fresh instance starts with the getting-started checklist.
  const checklist = page.getByTestId('onboarding');
  await expect(checklist).toBeVisible();
  await expect(checklist.getByRole('listitem')).toHaveCount(3);

  // 1. Connect a language model: the mock server speaks the OpenAI API.
  await page.getByRole('link', { name: 'Open integrations' }).click();
  const card = page.getByRole('article', { name: 'OpenAI-compatible' });
  await card.getByRole('button', { name: /Configure|Set up|Edit/ }).click();
  await page.getByLabel('Base URL').fill(`${MOCK}/v1`);
  await page.getByRole('button', { name: /^Save/ }).click();
  await expect(card.getByText(/Connection works|Configured|Your key/i).first()).toBeVisible();

  // The mock model is not in the price table, so give it a price: its calls then have a cost.
  const price = await page.request.put('/api/pricing/overrides', {
    data: { kind: 'llm', name: 'mock-model', input_per_million: '0.15', output_per_million: '0.6' },
  });
  expect(price.ok()).toBe(true);

  // 2. Create a show: Kokoro voices (the defaults), the mock model, the mock news feed.
  await page.goto('/shows/new');
  await page.getByLabel('Title').fill('E2E Briefing');
  await page.getByLabel('Topic').fill('Open-source AI tooling');
  await page.getByLabel('Target length (minutes)').fill('2');
  await page.getByLabel('Stories per episode').fill('3');
  await page.getByRole('button', { name: 'Next' }).click();
  await expect(page.getByLabel('Voice provider').first()).toHaveValue('kokoro');
  await page.getByRole('button', { name: 'Next' }).click();
  await page.getByLabel('Language model provider').selectOption('openai_compatible');
  await page.getByLabel('Model', { exact: true }).selectOption('mock-model');
  await page.getByRole('button', { name: 'Next' }).click();
  await page.getByRole('button', { name: 'Next' }).click(); // sources are added once the show exists
  await page.getByRole('button', { name: 'Next' }).click(); // manual schedule
  await page.getByRole('button', { name: 'Create show' }).click();
  await expect(page.getByRole('heading', { name: 'E2E Briefing' })).toBeVisible();

  // The mock news feed is the show's only source.
  await page.getByRole('link', { name: 'Sources' }).click();
  await page.getByRole('button', { name: 'Add source' }).click();
  await page.getByLabel('Feed URL').fill(`${MOCK}/feed.xml`);
  await page.getByRole('dialog').getByRole('button', { name: 'Add source' }).click();
  await expect(page.getByText('Open Source AI Weekly')).toBeVisible();

  // 3. Generate now: confirm the estimate, then watch the run to its end.
  await page.getByRole('button', { name: 'Generate now: E2E Briefing' }).click();
  await page.getByRole('dialog').getByRole('button', { name: 'Generate' }).click();
  await expect(page.getByTestId('run-status')).toHaveText('Needs review', { timeout: 180_000 });
  await expect(page.getByRole('table', { name: 'Cost by stage and model' })).toBeVisible();
  await shot(page, 'run');

  // 4. The episode is there and plays.
  await page.getByRole('link', { name: 'Review episode' }).click();
  const audio = page.locator('audio');
  await expect(audio).toHaveAttribute('src', /\/api\/episodes\/.+\/audio/);
  await expect
    .poll(
      () => audio.evaluate((el: HTMLAudioElement) => (Number.isFinite(el.duration) ? el.duration : 0)),
      { timeout: 30_000 },
    )
    .toBeGreaterThan(1);
  await expect(page.getByRole('list', { name: 'Script' }).or(page.getByLabel('Text of line 1'))).toBeVisible();

  // 5. Publish it and find it in the public feed, with its audio.
  await shot(page, 'episode-review');
  await page.getByRole('button', { name: /Approve/ }).click();
  await expect(page.getByText('Published', { exact: true }).first()).toBeVisible();
  const feed = await request.get('/feeds/e2e-briefing.xml');
  expect(feed.ok()).toBe(true);
  const xml = await feed.text();
  expect(xml).toContain('<title>E2E Briefing</title>');
  expect(xml).toContain('Open tools, one step at a time');
  const enclosure = /<enclosure url="([^"]+)" length="(\d+)" type="audio\/mpeg"/.exec(xml);
  expect(enclosure).not.toBeNull();
  const media = new URL(enclosure?.[1] ?? '').pathname;
  const part = await request.get(media, { headers: { Range: 'bytes=0-99' } });
  expect(part.status()).toBe(206);
  expect((await part.body()).length).toBe(100);

  // 6. The dashboard and the cost overview know about it.
  await page.goto('/');
  await expect(page.getByText('Episodes this month')).toBeVisible();
  await expect(page.getByRole('link', { name: 'Open tools, one step at a time' })).toBeVisible();
  await shot(page, 'dashboard');
  await page.goto('/history');
  await expect(page.getByRole('link', { name: 'E2E Briefing' }).first()).toBeVisible();
  await page.goto('/costs');
  await expect(page.getByText('Average per episode')).toBeVisible();
  await expect(page.getByText(/unpriced/)).toHaveCount(0); // every call has a known price
  await shot(page, 'costs');
  await page.goto('/shows');
  await page.getByRole('link', { name: 'E2E Briefing' }).first().click();
  await expect(page.getByLabel('Feed address')).toBeVisible();
  await shot(page, 'show');

  // 7. The security headers are on, and nothing the app needed was blocked by them.
  const home = await request.get('/');
  const headers = home.headers();
  expect(headers['content-security-policy']).toContain("frame-ancestors 'none'");
  expect(headers['x-content-type-options']).toBe('nosniff');
  expect(headers['x-frame-options']).toBe('DENY');
  expect(headers['referrer-policy']).toBeTruthy();
  expect(blocked).toEqual([]);
});

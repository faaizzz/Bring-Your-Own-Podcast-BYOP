import { expect, test, type APIRequestContext, type Page } from '@playwright/test';

// Regenerates the pictures in docs/images from the e2e stack: `make screenshots`. It seeds a demo
// show (three runs through the mock model and voices) and takes every picture at 1440x900 in the
// light theme, plus one dark one. Nothing here is real: the data comes from the mock servers.
const SHOTS = process.env.E2E_SCREENSHOTS;
test.skip(!SHOTS, 'Set E2E_SCREENSHOTS=<dir> (see `make screenshots`) to capture the images');

test.use({ viewport: { width: 1440, height: 900 }, colorScheme: 'light', locale: 'en-US' });

const EMAIL = 'e2e@example.com';
const PASSWORD = 'e2e-password-123';
// The mock server under the names the pictures show (see docker-compose.e2e.yml).
const MODEL_URL = 'http://ollama:8000/v1';
const VOICE_URL = 'http://kokoro-gateway:8000/v1';
const FEED = 'http://mock-services:8000/demo-feed.xml';

async function shot(page: Page, name: string): Promise<void> {
  await page.waitForLoadState('networkidle');
  await page.evaluate(() => document.fonts.ready);
  await page.screenshot({ path: `${SHOTS ?? '.'}/${name}.png` });
}

async function signIn(page: Page): Promise<void> {
  await page.goto('/login');
  await page.getByPlaceholder('Email address').fill(EMAIL);
  await page.getByPlaceholder('Password').fill(PASSWORD);
  await page.getByRole('button', { name: 'Sign in' }).click();
  await expect(page.getByRole('navigation', { name: 'Main' })).toBeVisible();
}

async function post<T>(request: APIRequestContext, path: string, data?: object): Promise<T> {
  const response = await request.post(path, { data });
  expect(response.ok(), `${path}: ${await response.text()}`).toBe(true);
  return (response.status() === 204 ? undefined : await response.json()) as T;
}

type Run = { id: string; status: string; episode_id: string | null };

/** Start a run and wait for it to need review. Returns it, with the draft episode it made. */
async function generate(request: APIRequestContext, showId: string): Promise<Run> {
  const started = await post<Run>(request, `/api/shows/${showId}/runs`);
  for (let i = 0; i < 120; i += 1) {
    const run = (await (await request.get(`/api/runs/${started.id}`)).json()) as Run & {
      error: string | null;
    };
    if (run.status === 'awaiting_review') return run;
    expect(['queued', 'running'], `run ${run.status}: ${run.error ?? ''}`).toContain(run.status);
    await new Promise((resolve) => setTimeout(resolve, 2000));
  }
  throw new Error('the run did not finish');
}

test('regenerates the documentation images', async ({ page }) => {
  test.setTimeout(10 * 60_000);
  await signIn(page);
  const api = page.request;

  // --- demo data --------------------------------------------------------------------------------
  // Two connections: a model server (no web search) and a voice server behind a gateway.
  const ollama = await post<{ id: string }>(api, '/api/connections', {
    name: 'Local Ollama',
    base_url: MODEL_URL,
    llm: true,
    headers: [{ name: 'X-Gateway-Token', value: 'demo-gateway-token-1234' }],
  });
  await post(api, '/api/connections', {
    name: 'Studio voices',
    base_url: VOICE_URL,
    api_key: 'sk-demo-studio-key-0000',
    llm: false,
    tts: true,
  });
  const price = await api.put('/api/pricing/overrides', {
    data: { kind: 'llm', name: 'mock-model', input_per_million: '0.15', output_per_million: '0.6' },
  });
  expect(price.ok()).toBe(true);

  const show = await post<{ id: string }>(api, '/api/shows', {
    title: 'Open Source AI Weekly',
    topic: 'News about open-source AI tooling: models, inference servers, speech and agents',
    description: 'A short weekly briefing for people who build with open tools.',
    style: 'conversational',
    target_minutes: 3,
    items_per_episode: 4,
    llm_provider: `conn:${ollama.id}`,
    llm_model: 'mock-model',
    schedule_kind: 'weekly',
    schedule_time: '07:30',
    schedule_weekday: 0,
    timezone: 'Europe/Berlin',
  });
  await post(api, `/api/shows/${show.id}/sources`, {
    kind: 'rss',
    value: FEED,
    name: 'Open Source AI Weekly',
  });

  // Three runs: the first two published, the last one left as a draft to review.
  const first = await generate(api, show.id);
  await post(api, `/api/episodes/${first.episode_id ?? ''}/approve`);
  const second = await generate(api, show.id);
  await post(api, `/api/episodes/${second.episode_id ?? ''}/approve`);
  const draft = await generate(api, show.id);

  // --- the pictures -----------------------------------------------------------------------------
  await page.goto('/');
  await expect(page.getByText('Episodes this month')).toBeVisible();
  await expect(page.getByRole('link', { name: /, plus \d+ more/ }).first()).toBeVisible();
  await shot(page, 'dashboard');

  await page.goto(`/shows/${show.id}`);
  await expect(page.getByLabel('Feed address')).toBeVisible();
  await shot(page, 'show');

  await page.goto(`/runs/${draft.id}`);
  await expect(page.getByTestId('run-status')).toHaveText('Needs review');
  await expect(page.getByRole('table', { name: 'Cost by stage and model' })).toBeVisible();
  await shot(page, 'run');

  await page.goto(`/episodes/${draft.episode_id ?? ''}`);
  await expect(page.locator('audio')).toHaveAttribute('src', /\/api\/episodes\/.+\/audio/);
  await expect(page.getByLabel('Text of line 1').first()).toBeVisible();
  await shot(page, 'episode-review');

  await page.goto('/costs');
  await expect(page.getByText('Average per episode')).toBeVisible();
  await shot(page, 'costs');

  // v0.2: connections.
  await page.goto('/settings/integrations');
  const connections = page.getByRole('heading', { name: 'OpenAI-compatible connections' });
  await expect(connections).toBeVisible();
  for (const name of ['Local Ollama', 'Studio voices']) {
    const card = page.getByRole('article', { name });
    await card.getByRole('button', { name: 'Test connection' }).click();
    await expect(card.getByLabel('Test result')).toContainText('Works');
  }
  // The test toasts fade out after a few seconds; the pictures are taken without them.
  await expect(page.locator('.toast')).toHaveCount(0, { timeout: 15_000 });
  await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur());
  await page.mouse.move(0, 0);
  // Just the connections section: the built-in cards above it are not what this picture is about.
  await page.locator('section[aria-labelledby="connections-title"]').screenshot({
    path: `${SHOTS ?? '.'}/connections.png`,
  });
  await page.getByRole('article', { name: 'Local Ollama' }).getByRole('button', { name: 'Edit' }).click();
  await expect(page.getByRole('dialog').getByLabel('Header 1 name')).toHaveValue('X-Gateway-Token');
  await page.waitForTimeout(600); // the dialog's fade-in
  await shot(page, 'connection-edit');
  await page.getByRole('dialog').getByRole('button', { name: 'Cancel' }).click();

  // v0.2: searchable dropdowns, here the voices of the wizard's speakers step.
  await page.goto('/shows/new');
  await page.getByLabel('Title').fill('Rust Weekly');
  await page.getByLabel('Topic').fill('News about the Rust language and its ecosystem.');
  await page.getByRole('button', { name: 'Next' }).click();
  await expect(page.getByLabel('Voice', { exact: true }).first()).toBeVisible();
  await page.getByLabel('Voice', { exact: true }).first().click();
  await expect(page.getByRole('option').first()).toBeVisible();
  await page.evaluate(() => window.scrollBy(0, 40));
  await shot(page, 'dropdown');
  await page.keyboard.press('Escape');

  // v0.2: discovery says up front that this model cannot search the web.
  await page.goto(`/shows/${show.id}/sources`);
  await page.getByRole('button', { name: 'Discover sources' }).click();
  const dialog = page.getByRole('dialog');
  await expect(dialog.getByTestId('discovery-model')).toContainText('No web search');
  await page.waitForTimeout(600); // the dialog's fade-in
  await shot(page, 'discovery');

  // One picture in the dark theme.
  await page.goto('/');
  await page.getByRole('button', { name: 'Switch to dark mode' }).click();
  await expect(page.getByText('Episodes this month')).toBeVisible();
  await shot(page, 'dashboard-dark');
});

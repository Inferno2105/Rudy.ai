import { expect, test, type Page } from '@playwright/test'

/** A valid 1-second silent 16 kHz mono WAV, built in memory. */
function silentWav(seconds = 1, sampleRate = 16_000): Buffer {
  const samples = seconds * sampleRate
  const buffer = Buffer.alloc(44 + samples * 2)
  buffer.write('RIFF', 0)
  buffer.writeUInt32LE(36 + samples * 2, 4)
  buffer.write('WAVE', 8)
  buffer.write('fmt ', 12)
  buffer.writeUInt32LE(16, 16)
  buffer.writeUInt16LE(1, 20) // PCM
  buffer.writeUInt16LE(1, 22) // mono
  buffer.writeUInt32LE(sampleRate, 24)
  buffer.writeUInt32LE(sampleRate * 2, 28)
  buffer.writeUInt16LE(2, 32)
  buffer.writeUInt16LE(16, 34)
  buffer.write('data', 36)
  buffer.writeUInt32LE(samples * 2, 40)
  return buffer
}

// The account backend/tests/e2e_server.py creates at startup.
const USER = { username: 'demo', password: 'demo-password-123' }

async function openApp(page: Page) {
  await page.goto('/meetings')
  // Signed out, so the app sends us to sign in, then back to the meetings.
  await expect(page.getByRole('heading', { name: 'Welcome back' })).toBeVisible()
  await page.getByLabel('Username').fill(USER.username)
  await page.getByLabel('Password', { exact: true }).fill(USER.password)
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page.getByRole('heading', { name: 'Meetings', level: 1 })).toBeVisible()
}

async function openNav(page: Page, name: string) {
  const menu = page.getByRole('button', { name: 'Open menu' })
  if (await menu.isVisible()) await menu.click()
  await page.getByRole('navigation', { name: 'Main' }).getByRole('link', { name }).click()
}

test('the landing page leads to sign-in, which refuses a wrong password', async ({ page }) => {
  await page.goto('/')
  await expect(
    page.getByRole('heading', { level: 1, name: 'Every voice in your meeting, understood.' }),
  ).toBeVisible()
  await page
    .getByRole('link', { name: /Get started/ })
    .first()
    .click()
  await expect(page.getByRole('heading', { name: 'Welcome back' })).toBeVisible()
  await page.getByLabel('Username').fill(USER.username)
  await page.getByLabel('Password', { exact: true }).fill('not-the-password')
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page.getByText('Incorrect username or password.')).toBeVisible()
})

test('the data API refuses requests without a session', async ({ request }) => {
  expect((await request.get('/api/runs')).status()).toBe(401)
  expect((await request.get('/api/health')).status()).toBe(200)
})

test('upload a recording, process it, and read the results', async ({ page }) => {
  await openApp(page)
  await openNav(page, 'New run')

  await page.getByLabel('Recording file').setInputFiles({
    name: 'E2E Standup.wav',
    mimeType: 'audio/wav',
    buffer: silentWav(),
  })
  // The phone project reuses the server, where the same file is then already present.
  await expect(page.getByText(/e2e-standup.wav .*selected it./)).toBeVisible()
  await page.getByLabel('Number of speakers').fill('2')
  await page.getByRole('button', { name: 'Start processing' }).click()

  // Progress streams in, then the run completes and the page reloads its data.
  await expect(page.getByRole('heading', { level: 1, name: 'e2e-standup.wav' })).toBeVisible()
  await expect(page.getByText('Completed', { exact: true })).toBeVisible({ timeout: 30_000 })
  await expect(page.getByText(/^Synthetic/).first()).toBeVisible()

  const transcript = page.getByRole('list', { name: 'Transcript' })
  await expect(transcript.getByText('Let us review the release plan first')).toBeVisible()
  await page.getByText('Original script').click()
  await expect(transcript.getByText('नमस्ते सबको, मीटिंग शुरू करते हैं')).toBeVisible()

  // The player: its waveform comes from the real recording, and the recording
  // is served with Range support so it can seek.
  await expect(page.getByRole('button', { name: 'Play', exact: true })).toBeVisible()
  await expect(page.getByRole('slider', { name: /Recording position/ })).toBeVisible()
  const src = await page.locator('audio').getAttribute('src')
  expect(src).toMatch(/\/api\/runs\/[^/]+\/audio$/)
  const audio = await page.request.get(src!, { headers: { Range: 'bytes=0-9' } })
  expect(audio.status()).toBe(206)
  const wave = await page.request.get(src!.replace(/audio$/, 'waveform?bins=50'))
  expect((await wave.json()).peaks).toHaveLength(50)

  // Clicking a timestamp plays from there and marks that line as current
  // (this test's recording is 1 s long, so the first line is the one to try).
  await transcript.getByRole('button', { name: 'Play from 0:00' }).click()
  await expect(transcript.locator('li[aria-current="true"]')).toContainText(
    'नमस्ते सबको, मीटिंग शुरू करते हैं',
  )

  await page.getByRole('tab', { name: /Summary/ }).click()
  await expect(page.getByText('The team agreed to ship the release on Friday')).toBeVisible()
  await expect(page.getByRole('cell', { name: 'Finish testing' })).toBeVisible()

  await page.getByRole('tab', { name: /Speakers/ }).click()
  await expect(page.getByRole('img', { name: /Bar chart of speaking time/ })).toBeVisible()

  await page.getByRole('tab', { name: /Provenance/ }).click()
  await expect(page.getByText('Not eligible for reported results')).toBeVisible()

  // Reloading a deep link keeps the view (SPA fallback + tab in the URL).
  await page.reload()
  await expect(page.getByText('Not eligible for reported results')).toBeVisible()

  await openNav(page, 'Meetings')
  await expect(page.getByRole('link', { name: 'e2e-standup.wav' }).first()).toBeVisible()
})

test('a long transcript renders only the rows near the viewport', async ({ page }) => {
  const errors: string[] = []
  page.on('pageerror', (error) => errors.push(String(error)))
  await openApp(page)
  await openNav(page, 'New run')
  await page.getByLabel('Recording file').setInputFiles({
    name: 'long-meeting.wav',
    mimeType: 'audio/wav',
    buffer: silentWav(),
  })
  await expect(page.getByText(/long-meeting\.wav .*selected it\./)).toBeVisible()
  await page.getByRole('button', { name: 'Start processing' }).click()
  await expect(page.getByText('Completed', { exact: true })).toBeVisible({ timeout: 30_000 })

  const transcript = page.getByRole('list', { name: 'Transcript' })
  await expect(transcript.getByText('long meeting line 0', { exact: true })).toBeVisible()
  const rendered = await transcript.getByRole('listitem').count()
  expect(rendered).toBeGreaterThan(0)
  expect(rendered).toBeLessThan(100) // of 400
  await expect(transcript.getByRole('listitem').first()).toHaveAttribute('aria-setsize', '400')

  // Scrolling to the end brings the last line into the DOM.
  await page.keyboard.press('End')
  await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight))
  await expect(transcript.getByText('long meeting line 399', { exact: true })).toBeVisible()
  expect(errors).toEqual([])
})

test('live session: segments stream in, then stop', async ({ page }) => {
  await openApp(page)
  await openNav(page, 'Live')
  // The e2e machine may have no microphone; the stub pipeline does not use one.
  await page.getByRole('button', { name: 'Get ready' }).click()
  await expect(page.getByText('Getting ready…')).toBeVisible()
  // Nothing records until everything is ready and the user says go.
  await expect(page.getByText('All systems go')).toBeVisible({ timeout: 15_000 })
  await expect(page.getByText('The microphone is picking you up.')).toBeVisible({
    timeout: 10_000,
  })
  await page.getByRole('button', { name: 'Start recording' }).click()
  const transcript = page.getByRole('list', { name: 'Live transcript' })
  await expect(transcript.getByText('live chunk 2')).toBeVisible({ timeout: 15_000 })
  await page.getByRole('button', { name: 'Stop' }).click()
  await expect(page.getByText('Session finished')).toBeVisible({ timeout: 15_000 })
  await page.getByRole('link', { name: /Open meeting/ }).click()
  await expect(
    page.getByRole('list', { name: 'Transcript' }).getByText('live chunk 0'),
  ).toBeVisible()
})

test('a second account signs up and sees none of the first account’s data', async ({
  page,
  browser,
}, testInfo) => {
  // The first account processes a recording.
  await openApp(page)
  await openNav(page, 'New run')
  await page.getByLabel('Recording file').setInputFiles({
    name: 'Private Notes.wav',
    mimeType: 'audio/wav',
    buffer: silentWav(),
  })
  await expect(page.getByText(/private-notes.wav .*selected it./)).toBeVisible()
  await page.getByRole('button', { name: 'Start processing' }).click()
  await expect(page.getByText('Completed', { exact: true })).toBeVisible({ timeout: 30_000 })
  const firstRunUrl = page.url()

  // Someone else, in their own browser, creates an account.
  const context = await browser.newContext()
  const other = await context.newPage()
  await other.goto('/login')
  await other.getByRole('link', { name: 'Create an account' }).click()
  await expect(other.getByRole('heading', { name: 'Create an account' })).toBeVisible()
  const name = `guest-${testInfo.project.name}-${Date.now() % 100000}`
  await other.getByLabel('Username').fill(name)
  await other.getByLabel('Password', { exact: true }).fill('guest-password-123')
  await other.getByLabel('Confirm password').fill('guest-password-123')
  await other.getByRole('button', { name: 'Create account' }).click()

  await expect(other.getByRole('heading', { name: 'Meetings', level: 1 })).toBeVisible()
  await expect(other.getByText('No meetings yet')).toBeVisible()
  await other.goto('/new')
  await expect(other.getByText('No recordings yet. Upload one above.')).toBeVisible()
  await other.goto(new URL(firstRunUrl).pathname)
  await expect(other.getByText('Meeting not found')).toBeVisible()
  await context.close()
})

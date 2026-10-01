import { expect, test, type Page } from '@playwright/test'

import { E2E_TOKEN } from './env.ts'

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

async function signIn(page: Page) {
  await page.goto('/')
  await page.getByLabel('API token').fill(E2E_TOKEN)
  await page.getByRole('button', { name: 'Continue' }).click()
  await expect(page.getByRole('heading', { name: 'Meetings', level: 1 })).toBeVisible()
}

async function openNav(page: Page, name: string) {
  const menu = page.getByRole('button', { name: 'Open menu' })
  if (await menu.isVisible()) await menu.click()
  await page.getByRole('navigation', { name: 'Main' }).getByRole('link', { name }).click()
}

test('rejects a wrong token', async ({ page }) => {
  await page.goto('/')
  await page.getByLabel('API token').fill('not-the-token')
  await page.getByRole('button', { name: 'Continue' }).click()
  await expect(page.getByText('That token was not accepted by the server.')).toBeVisible()
})

test('upload a recording, process it, and read the results', async ({ page }) => {
  await signIn(page)
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
  await expect(page.getByText('Synthetic', { exact: true })).toBeVisible()

  const transcript = page.getByRole('list', { name: 'Transcript' })
  await expect(transcript.getByText('Let us review the release plan first')).toBeVisible()
  await page.getByText('Original script').click()
  await expect(transcript.getByText('नमस्ते सबको, मीटिंग शुरू करते हैं')).toBeVisible()

  // The recording plays through a signed URL, never the token.
  const player = page.getByLabel('Meeting recording')
  await expect(player).toHaveAttribute('src', /\/audio\?ticket=\d+\./)
  expect(await player.getAttribute('src')).not.toContain(E2E_TOKEN)

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

test('live session: segments stream in, then stop', async ({ page }) => {
  await signIn(page)
  await openNav(page, 'Live')
  // The e2e machine may have no microphone; the stub pipeline does not use one.
  const start = page.getByRole('button', { name: 'Start recording' })
  await start.click()
  const transcript = page.getByRole('list', { name: 'Live transcript' })
  await expect(transcript.getByText('live chunk 2')).toBeVisible({ timeout: 15_000 })
  await page.getByRole('button', { name: 'Stop' }).click()
  await expect(page.getByText('Session finished')).toBeVisible({ timeout: 15_000 })
  await page.getByRole('link', { name: /Open meeting/ }).click()
  await expect(
    page.getByRole('list', { name: 'Transcript' }).getByText('live chunk 0'),
  ).toBeVisible()
})

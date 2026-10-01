/** Shared between the Playwright config (which starts the server) and the specs. */
export const E2E_TOKEN = process.env.E2E_API_TOKEN ?? 'e2e-token-0123456789abcdef0123456789abcdef'

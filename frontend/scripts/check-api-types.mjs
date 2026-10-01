// Fails if src/api/schema.d.ts is stale relative to src/api/openapi.json.
//
// The UI's types are generated, never hand-edited; the backend's test suite
// already checks openapi.json against the live server. Together the two
// checks mean the UI cannot compile against a contract the server no longer
// honours. Fix a failure with `npm run gen:api`.
import { execFileSync } from 'node:child_process'
import { mkdtempSync, readFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

const dir = mkdtempSync(join(tmpdir(), 'api-types-'))
const fresh = join(dir, 'schema.d.ts')
try {
  execFileSync(
    process.execPath,
    ['node_modules/openapi-typescript/bin/cli.js', 'src/api/openapi.json', '-o', fresh],
    { stdio: 'ignore' },
  )
  const normalise = (text) => text.replace(/\r\n/g, '\n')
  const committed = normalise(readFileSync('src/api/schema.d.ts', 'utf8'))
  if (normalise(readFileSync(fresh, 'utf8')) !== committed) {
    console.error('src/api/schema.d.ts is out of date. Run `npm run gen:api`.')
    process.exit(1)
  }
  console.log('API types are up to date.')
} finally {
  rmSync(dir, { recursive: true, force: true })
}

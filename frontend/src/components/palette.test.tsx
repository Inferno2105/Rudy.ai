import { screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import * as f from '../test/fixtures'
import { renderApp } from '../test/render'

describe('command palette', () => {
  it('opens with Ctrl+K and jumps to the moment a phrase was said', async () => {
    const { user, router } = renderApp('/meetings')
    await screen.findByRole('heading', { name: 'Meetings', level: 1 })

    await user.keyboard('{Control>}k{/Control}')
    const input = await screen.findByRole('combobox', { name: /Search meetings/ })
    expect(screen.getByRole('option', { name: 'Meetings' })).toBeInTheDocument()

    await user.type(input, 'friday')
    const results = screen.getByRole('listbox', { name: 'Results' })
    const said = await within(results).findByRole('option', { name: /release Friday ko hoga/ })
    expect(within(results).getByRole('group', { name: 'Said in a meeting' })).toContainElement(said)

    // Arrow down to the transcript line, then open it.
    while (input.getAttribute('aria-activedescendant') !== said.id) {
      await user.keyboard('{ArrowDown}')
    }
    await user.keyboard('{Enter}')
    // The run page loads lazily; the location changes once it has.
    await waitFor(() => expect(router.state.location.pathname).toBe(`/runs/${f.RUN_ID}`))
    expect(router.state.location.search).toBe(`?t=${f.searchHits[0]!.start}`)
  })

  it('filters pages by name', async () => {
    const { user } = renderApp('/meetings')
    await screen.findByRole('heading', { name: 'Meetings', level: 1 })
    await user.click(screen.getAllByRole('button', { name: /Search/ })[0]!)
    await user.type(await screen.findByRole('combobox'), 'live')
    expect(screen.getByRole('option', { name: 'Live recording' })).toBeInTheDocument()
    expect(screen.queryByRole('option', { name: 'Evaluation' })).not.toBeInTheDocument()
  })
})

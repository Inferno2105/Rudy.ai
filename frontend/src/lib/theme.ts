import { useCallback, useEffect, useState } from 'react'

export type ThemePreference = 'light' | 'dark' | 'system'

const KEY = 'meeting-assistant.theme'

function readPreference(): ThemePreference {
  try {
    const value = window.localStorage.getItem(KEY)
    if (value === 'light' || value === 'dark' || value === 'system') return value
  } catch {
    // Storage blocked: follow the system.
  }
  // Dark is the primary "studio" theme; the toggle offers light and system.
  return 'dark'
}

function systemPrefersDark(): boolean {
  return window.matchMedia?.('(prefers-color-scheme: dark)').matches ?? false
}

export function applyTheme(preference: ThemePreference): void {
  const dark = preference === 'dark' || (preference === 'system' && systemPrefersDark())
  document.documentElement.classList.toggle('dark', dark)
  // Browser chrome follows the chosen theme, not only the system one.
  for (const meta of document.querySelectorAll<HTMLMetaElement>('meta[name="theme-color"]')) {
    meta.content = dark ? '#0c0e1b' : '#f6f5fb'
  }
}

/** Apply the stored preference before React renders, avoiding a flash. */
export function initTheme(): void {
  applyTheme(readPreference())
}

export function useTheme(): [ThemePreference, (next: ThemePreference) => void] {
  const [preference, setPreference] = useState<ThemePreference>(readPreference)

  useEffect(() => {
    applyTheme(preference)
    if (preference !== 'system' || !window.matchMedia) return
    const media = window.matchMedia('(prefers-color-scheme: dark)')
    const onChange = () => applyTheme('system')
    media.addEventListener('change', onChange)
    return () => media.removeEventListener('change', onChange)
  }, [preference])

  const update = useCallback((next: ThemePreference) => {
    try {
      window.localStorage.setItem(KEY, next)
    } catch {
      // Not persisted; still applied for this page.
    }
    setPreference(next)
  }, [])

  return [preference, update]
}

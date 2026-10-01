/**
 * Language tags as the pipeline writes them (`English`, `Hindi`,
 * `Code-Mixed`), plus the HTML `lang` value for a segment's text, so screen
 * readers pronounce it correctly and Devanagari gets the right font metrics.
 */

const DEVANAGARI = /[ऀ-ॿ]/

export type LanguageTag = 'English' | 'Hindi' | 'Code-Mixed'

export interface LanguageStyle {
  label: string
  short: string
  className: string
}

const STYLES: Record<LanguageTag, LanguageStyle> = {
  English: {
    label: 'English',
    short: 'EN',
    className:
      'bg-blue-50 text-blue-800 ring-blue-200 dark:bg-blue-950 dark:text-blue-200 dark:ring-blue-800',
  },
  Hindi: {
    label: 'Hindi',
    short: 'HI',
    className:
      'bg-orange-50 text-orange-900 ring-orange-200 dark:bg-orange-950 dark:text-orange-200 dark:ring-orange-800',
  },
  'Code-Mixed': {
    label: 'Code-mixed',
    short: 'MIX',
    className:
      'bg-purple-50 text-purple-800 ring-purple-200 dark:bg-purple-950 dark:text-purple-200 dark:ring-purple-800',
  },
}

export function languageStyle(language: string | null | undefined): LanguageStyle | null {
  if (!language) return null
  return (
    STYLES[language as LanguageTag] ?? {
      label: language,
      short: language.slice(0, 3).toUpperCase(),
      className: 'bg-subtle text-muted ring-border',
    }
  )
}

export function hasDevanagari(text: string): boolean {
  return DEVANAGARI.test(text)
}

/** BCP 47 tag for a segment's text: `hi` (Devanagari), `hi-Latn` (romanized), `en`. */
export function textLang(text: string, language: string | null | undefined): string | undefined {
  if (hasDevanagari(text)) return 'hi'
  if (language === 'Hindi' || language === 'Code-Mixed') return 'hi-Latn'
  if (language === 'English') return 'en'
  return undefined
}

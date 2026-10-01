import { clsx, type ClassValue } from 'clsx'
import { useEffect } from 'react'
import { twMerge } from 'tailwind-merge'

/** Merge class names, letting later Tailwind utilities override earlier ones. */
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs))
}

/** Set the tab title for a page. */
export function useDocumentTitle(title: string | null | undefined): void {
  useEffect(() => {
    document.title = title ? `${title} · Meeting Assistant` : 'Meeting Assistant'
  }, [title])
}

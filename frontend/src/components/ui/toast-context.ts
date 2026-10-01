import { createContext, useContext } from 'react'

export interface ToastMessage {
  id: number
  title: string
  description?: string | undefined
  tone: 'success' | 'danger' | 'info'
}

export type Notify = (toast: Omit<ToastMessage, 'id'>) => void

export const ToastContext = createContext<Notify>(() => {})

export function useToast(): Notify {
  return useContext(ToastContext)
}

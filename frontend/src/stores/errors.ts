import { atom } from 'jotai'

/** Global error for app-wide display (e.g., auth failures). */
export const globalErrorAtom = atom<{ message: string; status?: number } | null>(null)

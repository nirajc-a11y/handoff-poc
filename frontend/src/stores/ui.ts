import { atom } from 'jotai'
import { atomWithStorage } from 'jotai/utils'
export const selectedConvIdAtom = atom<string | null>(null)
export const sidebarCollapsedAtom = atomWithStorage('sidebar-collapsed', false)

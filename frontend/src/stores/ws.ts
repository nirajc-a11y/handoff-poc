import { atom } from 'jotai'
import type { WSEvent } from '@/lib/types'
export const wsConnectedAtom = atom(false)
export const wsEventsAtom = atom<WSEvent[]>([])

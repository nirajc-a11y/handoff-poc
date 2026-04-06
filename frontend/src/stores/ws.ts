import { atom } from 'jotai'
import type { WSEvent } from '@/lib/types'

export const wsConnectedAtom = atom(false)
export const wsEventsAtom = atom<WSEvent[]>([])
export const wsExhaustedAtom = atom(false)
// True once the first WS connection attempt has been made — gates the offline indicator
export const wsInitializedAtom = atom(false)

import { atom } from 'jotai'
import { atomWithStorage } from 'jotai/utils'
export const tenantIdAtom = atomWithStorage<string>('handoff-tenant-id', '')
export const userIdAtom = atomWithStorage<string>('handoff-user-id', '')
export const isConnectedAtom = atom(false)

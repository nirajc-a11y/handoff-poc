import { atom } from 'jotai'
import { atomWithStorage } from 'jotai/utils'
export const tenantIdAtom = atomWithStorage<string>('handoff-tenant-id', '')
export const userIdAtom = atomWithStorage<string>('handoff-user-id', '00000000-0000-0000-0000-000000000000')
export const isConnectedAtom = atom(false)

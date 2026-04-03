import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useAtomValue } from 'jotai'
import { api } from '@/lib/api'
import { tenantIdAtom } from '@/stores/auth'
import type { Conversation } from '@/lib/types'

export function useEscalate() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: { conversation_id: string; reason?: string }) => api.post('/handoffs/escalate', body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['conversations'] }),
  })
}

export function useTransfer() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: { conversation_id: string; target_agent_id: string; warm: boolean }) =>
      api.post('/handoffs/transfer', body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['conversations'] }),
  })
}

export function useHandoffQueue() {
  const tenantId = useAtomValue(tenantIdAtom)
  return useQuery<Conversation[]>({
    queryKey: ['handoff-queue', tenantId],
    queryFn: () => api.get('/handoffs/queue'),
    enabled: !!tenantId,
  })
}

export function useIVRSkip() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: { conversation_id: string }) => api.post('/handoffs/ivr-skip', body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['conversations'] }),
  })
}

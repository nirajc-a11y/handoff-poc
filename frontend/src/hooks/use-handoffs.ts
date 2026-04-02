import { useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'

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

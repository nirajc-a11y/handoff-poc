import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useAtomValue } from 'jotai'
import { api } from '@/lib/api'
import { tenantIdAtom } from '@/stores/auth'
import type { Agent } from '@/lib/types'

export function useAgents() {
  const tenantId = useAtomValue(tenantIdAtom)
  return useQuery<Agent[]>({
    queryKey: ['agents', tenantId],
    queryFn: () => api.get('/agents'),
    enabled: !!tenantId,
  })
}

export function useAvailableAgents() {
  const tenantId = useAtomValue(tenantIdAtom)
  return useQuery<Agent[]>({
    queryKey: ['agents', tenantId, 'available'],
    queryFn: () => api.get('/agents/available'),
    enabled: !!tenantId,
  })
}

export function useAgent(id: string | null) {
  return useQuery<Agent>({ queryKey: ['agents', 'detail', id], queryFn: () => api.get(`/agents/${id}`), enabled: !!id })
}

export function useUpdateAgentStatus() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ agentId, status }: { agentId: string; status: string }) =>
      api.patch(`/agents/${agentId}/status`, { status }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['agents'] }),
  })
}

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useAtomValue } from 'jotai'
import { api } from '@/lib/api'
import { tenantIdAtom } from '@/stores/auth'
import type { Lead } from '@/lib/types'

export function useLeads(params?: { search?: string; limit?: number; offset?: number }) {
  const tenantId = useAtomValue(tenantIdAtom)
  const query = params ? `?${new URLSearchParams(Object.entries(params).filter(([, v]) => v != null).map(([k, v]) => [k, String(v)]))}` : ''
  return useQuery<Lead[]>({ queryKey: ['leads', params], queryFn: () => api.get(`/leads${query}`), enabled: !!tenantId })
}

export function useCreateLead() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: Partial<Lead>) => api.post('/leads', body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['leads'] }),
  })
}

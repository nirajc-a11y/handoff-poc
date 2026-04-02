import { useQuery } from '@tanstack/react-query'
import { useAtomValue } from 'jotai'
import { api } from '@/lib/api'
import { tenantIdAtom } from '@/stores/auth'
import type { Conversation } from '@/lib/types'

export function useActiveConversations() {
  const tenantId = useAtomValue(tenantIdAtom)
  return useQuery<Conversation[]>({
    queryKey: ['conversations', 'active'],
    queryFn: () => api.get('/conversations/active'),
    refetchInterval: 10_000,
    enabled: !!tenantId,
  })
}

export function useConversations(params?: { state?: string; channel?: string }) {
  const tenantId = useAtomValue(tenantIdAtom)
  const query = params ? `?${new URLSearchParams(params as Record<string, string>)}` : ''
  return useQuery<Conversation[]>({
    queryKey: ['conversations', params],
    queryFn: () => api.get(`/conversations${query}`),
    enabled: !!tenantId,
  })
}

export function useConversation(id: string | null) {
  return useQuery<Conversation>({
    queryKey: ['conversations', id],
    queryFn: () => api.get(`/conversations/${id}`),
    enabled: !!id,
  })
}

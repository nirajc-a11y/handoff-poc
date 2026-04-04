import { useQuery } from '@tanstack/react-query'
import { useAtomValue } from 'jotai'
import { api } from '@/lib/api'
import { tenantIdAtom } from '@/stores/auth'
import type { Conversation } from '@/lib/types'

export interface PaginatedConversations {
  items: Conversation[]
  total: number
  limit: number
  offset: number
}

export function useActiveConversations(limit = 50, offset = 0) {
  const tenantId = useAtomValue(tenantIdAtom)
  return useQuery<PaginatedConversations>({
    queryKey: ['conversations', tenantId, 'active', limit, offset],
    queryFn: () => api.get(`/conversations/active?limit=${limit}&offset=${offset}`),
    enabled: !!tenantId,
    refetchInterval: 10_000, // Fallback poll — catches any missed WebSocket events
  })
}

export function useConversations(params?: { state?: string; channel?: string }) {
  const tenantId = useAtomValue(tenantIdAtom)
  const query = params ? `?${new URLSearchParams(params as Record<string, string>)}` : ''
  return useQuery<Conversation[]>({
    queryKey: ['conversations', tenantId, params],
    queryFn: () => api.get(`/conversations${query}`),
    enabled: !!tenantId,
  })
}

export function useConversation(id: string | null) {
  return useQuery<Conversation>({
    queryKey: ['conversations', 'detail', id],
    queryFn: () => api.get(`/conversations/${id}`),
    enabled: !!id,
  })
}

export function useConversationHandoffs(id: string | null) {
  return useQuery<import('@/lib/types').HandoffEvent[]>({
    queryKey: ['conversations', 'handoffs', id],
    queryFn: () => api.get(`/conversations/${id}/handoffs`),
    enabled: !!id,
  })
}

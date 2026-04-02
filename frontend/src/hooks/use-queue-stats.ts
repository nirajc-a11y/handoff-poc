import { useQuery } from '@tanstack/react-query'
import { useAtomValue } from 'jotai'
import { api } from '@/lib/api'
import { tenantIdAtom } from '@/stores/auth'
import type { QueueStats } from '@/lib/types'

export function useQueueStats() {
  const tenantId = useAtomValue(tenantIdAtom)
  return useQuery<QueueStats>({ queryKey: ['queue-stats'], queryFn: () => api.get('/handoffs/queue/stats'), refetchInterval: 5000, enabled: !!tenantId })
}

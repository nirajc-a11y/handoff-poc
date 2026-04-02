import { useEffect } from 'react'
import { useAtom, useAtomValue } from 'jotai'
import { useQueryClient } from '@tanstack/react-query'
import { wsManager } from '@/lib/ws'
import { wsConnectedAtom, wsEventsAtom } from '@/stores/ws'
import { tenantIdAtom, isConnectedAtom } from '@/stores/auth'
import type { WSEvent } from '@/lib/types'

export function useWebSocket() {
  const [tenantId] = useAtom(tenantIdAtom)
  const isConnected = useAtomValue(isConnectedAtom)
  const [, setConnected] = useAtom(wsConnectedAtom)
  const [, setEvents] = useAtom(wsEventsAtom)
  const qc = useQueryClient()

  useEffect(() => {
    if (!tenantId || !isConnected) return
    wsManager.connect(tenantId, setConnected)
    const unsub = wsManager.subscribe((event: WSEvent) => {
      setEvents((prev) => [event, ...prev].slice(0, 100))
      if (event.type.startsWith('conversation.')) {
        qc.invalidateQueries({ queryKey: ['conversations'] })
        if (event.data?.conversation_id) {
          qc.invalidateQueries({ queryKey: ['conversations', event.data.conversation_id] })
          qc.invalidateQueries({ queryKey: ['messages', event.data.conversation_id] })
        }
      }
      if (event.type.startsWith('agent.')) qc.invalidateQueries({ queryKey: ['agents'] })
      if (event.type.startsWith('queue.')) qc.invalidateQueries({ queryKey: ['queue-stats'] })
      if (event.type.startsWith('campaign.')) qc.invalidateQueries({ queryKey: ['campaigns'] })
    })
    return () => { unsub(); wsManager.disconnect() }
  }, [tenantId, setConnected, setEvents, qc])
}

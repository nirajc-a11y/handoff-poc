/**
 * LiveKit-based softphone for human agents.
 *
 * Listens for conversation state changes via WebSocket. When the current agent
 * is assigned to a conversation (HUMAN_HANDLING), auto-connects to the LiveKit
 * room. Reuses the existing ActiveCall component for controls.
 */

import { useEffect, useRef } from 'react'
import { useAtomValue } from 'jotai'
import { Headphones, WifiOff } from 'lucide-react'
import { ActiveCall } from './active-call'
import { useLivekitAgent } from '@/hooks/use-livekit-agent'
import { wsEventsAtom } from '@/stores/ws'
import { userIdAtom } from '@/stores/auth'

export function LiveKitSoftphone() {
  const {
    isConnected,
    isMuted,
    isOnHold,
    error,
    roomName,
    duration,
    connect,
    disconnect,
    toggleMute,
    toggleHold,
  } = useLivekitAgent()

  const wsEvents = useAtomValue(wsEventsAtom)
  const userId = useAtomValue(userIdAtom)
  // Track which conversation we've already auto-joined (by conversation_id only,
  // not event type — prevents double-connect from duplicate WS events)
  const lastJoinedConvRef = useRef<string | null>(null)
  const connectingRef = useRef(false)

  // Auto-join LiveKit room when agent is assigned to a conversation
  useEffect(() => {
    if (isConnected || connectingRef.current || !userId) return

    for (const event of wsEvents) {
      if (!event.data) continue
      const { conversation_id, handler_id, to_state } = event.data as Record<string, string>
      if (!conversation_id) continue

      // Skip if we already joined this conversation
      if (lastJoinedConvRef.current === conversation_id) continue

      if (
        to_state === 'human_handling' &&
        handler_id === userId &&
        (event.type === 'conversation.handoff.handler_change' ||
          event.type === 'conversation.handoff.ai_to_human' ||
          event.type === 'conversation.state_changed')
      ) {
        lastJoinedConvRef.current = conversation_id
        connectingRef.current = true
        connect(conversation_id)
          .catch(() => {})
          .finally(() => { connectingRef.current = false })
        break
      }
    }
  }, [wsEvents, userId, isConnected, connect])

  // Connected — show active call controls
  if (isConnected) {
    return (
      <div className="rounded-sm border border-green-200 bg-green-50 p-1">
        <ActiveCall
          callerId={roomName || 'LiveKit Call'}
          duration={duration}
          isMuted={isMuted}
          isOnHold={isOnHold}
          onToggleMute={toggleMute}
          onToggleHold={toggleHold}
          onHangup={disconnect}
        />
      </div>
    )
  }

  // Error state
  if (error) {
    return (
      <div className="rounded-sm border border-red-200 bg-red-50 p-2">
        <div className="flex items-center gap-2 text-xs text-red-600">
          <WifiOff className="size-3.5" />
          <span>{error}</span>
        </div>
      </div>
    )
  }

  // Idle — waiting for assignment
  return (
    <div className="rounded-sm border border-gray-200 bg-gray-50 p-3">
      <div className="flex items-center justify-center gap-2 text-xs text-gray-500">
        <Headphones className="size-3.5" />
        <span>LiveKit ready — waiting for call assignment</span>
      </div>
    </div>
  )
}

/**
 * LiveKit-based softphone hook for human agents.
 *
 * Replaces the Plivo WebRTC softphone when LiveKit agent mode is enabled.
 * The agent joins a LiveKit room to hear the caller (via the Plivo-LiveKit
 * bridge) and speaks into the room (bridge forwards audio to Plivo).
 */

import { useState, useRef, useCallback, useEffect } from 'react'
import { api } from '@/lib/api'

interface LiveKitAgentState {
  isConnected: boolean
  isMuted: boolean
  isOnHold: boolean
  error: string | null
  roomName: string | null
  duration: number
}

interface LiveKitAgentActions {
  connect: (conversationId: string) => Promise<void>
  disconnect: () => Promise<void>
  toggleMute: () => void
  toggleHold: () => Promise<void>
}

export function useLivekitAgent(): LiveKitAgentState & LiveKitAgentActions {
  const [state, setState] = useState<LiveKitAgentState>({
    isConnected: false,
    isMuted: false,
    isOnHold: false,
    error: null,
    roomName: null,
    duration: 0,
  })

  const roomRef = useRef<any>(null)
  const convIdRef = useRef<string | null>(null)
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const startTimeRef = useRef<number>(0)

  // Clean up on unmount
  useEffect(() => {
    return () => {
      if (timerRef.current) clearInterval(timerRef.current)
      if (roomRef.current) {
        roomRef.current.disconnect().catch(() => {})
        roomRef.current = null
      }
    }
  }, [])

  const connect = useCallback(async (conversationId: string) => {
    if (roomRef.current) {
      // Already connected — disconnect first
      await roomRef.current.disconnect()
      roomRef.current = null
    }

    try {
      // Get token from backend
      const tokenRes = await api.post<{ token: string; url: string; room: string }>(
        `/agent/livekit-token/${conversationId}`,
      )

      // Dynamically import livekit-client (already in package.json)
      const { Room, RoomEvent } = await import('livekit-client')
      const room = new Room()
      roomRef.current = room
      convIdRef.current = conversationId

      // Handle disconnection
      room.on(RoomEvent.Disconnected, () => {
        roomRef.current = null
        convIdRef.current = null
        if (timerRef.current) {
          clearInterval(timerRef.current)
          timerRef.current = null
        }
        setState(prev => ({
          ...prev,
          isConnected: false,
          isMuted: false,
          isOnHold: false,
          roomName: null,
          duration: 0,
        }))
      })

      // Handle data messages (hold, transfer signals from backend)
      room.on(RoomEvent.DataReceived, (payload: Uint8Array) => {
        try {
          const msg = JSON.parse(new TextDecoder().decode(payload))
          if (msg.type === 'transfer_disconnect' || msg.type === 'call_ended') {
            // Backend wants us to leave (cold transfer or call ended)
            room.disconnect()
          } else if (msg.type === 'hold') {
            setState(prev => ({ ...prev, isOnHold: true }))
          } else if (msg.type === 'unhold') {
            setState(prev => ({ ...prev, isOnHold: false }))
          }
        } catch {
          // Ignore unparseable messages
        }
      })

      // Connect to room
      await room.connect(tokenRes.url, tokenRes.token)

      // Enable microphone
      await room.localParticipant.setMicrophoneEnabled(true)

      // Start call duration timer
      startTimeRef.current = Date.now()
      timerRef.current = setInterval(() => {
        setState(prev => ({
          ...prev,
          duration: Math.floor((Date.now() - startTimeRef.current) / 1000),
        }))
      }, 1000)

      setState({
        isConnected: true,
        isMuted: false,
        isOnHold: false,
        error: null,
        roomName: tokenRes.room,
        duration: 0,
      })
    } catch (err: any) {
      const message = err?.message || 'Failed to connect to LiveKit room'
      setState(prev => ({ ...prev, error: message }))
      throw err
    }
  }, [])

  const disconnect = useCallback(async () => {
    if (timerRef.current) {
      clearInterval(timerRef.current)
      timerRef.current = null
    }

    const convId = convIdRef.current
    if (roomRef.current) {
      await roomRef.current.disconnect()
      roomRef.current = null
    }

    // End the call via API
    if (convId) {
      try {
        await api.post(`/calls/${convId}/end`, {
          disposition: 'completed',
        })
      } catch {
        // Non-fatal — call may have already ended
      }
    }

    convIdRef.current = null
    setState({
      isConnected: false,
      isMuted: false,
      isOnHold: false,
      error: null,
      roomName: null,
      duration: 0,
    })
  }, [])

  const toggleMute = useCallback(() => {
    const room = roomRef.current
    if (!room) return

    const currentMuted = room.localParticipant.isMicrophoneEnabled
    // isMicrophoneEnabled is true when NOT muted
    room.localParticipant.setMicrophoneEnabled(!currentMuted ? false : true)

    setState(prev => ({ ...prev, isMuted: !prev.isMuted }))
  }, [])

  const toggleHold = useCallback(async () => {
    const convId = convIdRef.current
    if (!convId) return

    try {
      if (state.isOnHold) {
        await api.post(`/calls/${convId}/unhold`)
        setState(prev => ({ ...prev, isOnHold: false }))
      } else {
        await api.post(`/calls/${convId}/hold`)
        setState(prev => ({ ...prev, isOnHold: true }))
      }
    } catch (err: any) {
      setState(prev => ({ ...prev, error: err?.message || 'Hold/unhold failed' }))
    }
  }, [state.isOnHold])

  return {
    ...state,
    connect,
    disconnect,
    toggleMute,
    toggleHold,
  }
}

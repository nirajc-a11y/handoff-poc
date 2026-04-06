import { useState, useEffect, useRef, useCallback } from 'react'
import { useMutation } from '@tanstack/react-query'
import type { Room, RemoteTrack } from 'livekit-client'
import { api } from '@/lib/api'

// ---------------------------------------------------------------------------
// LiveKit Listen — join the LiveKit room and auto-play audio
// ---------------------------------------------------------------------------

interface ListenState {
  isListening: boolean
  error: string | null
}

export function useSupervisorListen(convId: string | null) {
  const [state, setState] = useState<ListenState>({ isListening: false, error: null })
  const roomRef = useRef<Room | null>(null)
  const userStoppedRef = useRef(false)

  const startListening = useCallback(async () => {
    if (!convId) return
    userStoppedRef.current = false

    try {
      const tokenRes = await api.post<{ token: string; url: string; room: string }>(
        `/supervisor/livekit-token/${convId}`,
        { mode: 'listen' },
      )

      const { Room, RoomEvent, Track } = await import('livekit-client')
      const room = new Room()
      roomRef.current = room

      // Attach an audio track to the DOM so the browser plays it.
      // room.startAudio() alone is insufficient in Chrome — the AudioContext
      // may remain suspended unless audio elements are explicitly attached.
      const attachTrack = (track: RemoteTrack) => {
        if (track.kind !== Track.Kind.Audio) return
        const el = track.attach()
        el.setAttribute('data-supervisor-audio', 'true')
        document.body.appendChild(el)
      }

      room.on(RoomEvent.TrackSubscribed, (track) => {
        attachTrack(track)
      })

      room.on(RoomEvent.TrackUnsubscribed, (track) => {
        track.detach()
      })

      room.on(RoomEvent.Disconnected, () => {
        setState({ isListening: false, error: null })
        roomRef.current = null
        // Clean up any lingering audio elements
        document.querySelectorAll('[data-supervisor-audio]').forEach(el => el.remove())
      })

      room.on(RoomEvent.Reconnecting, () => {
        setState({ isListening: true, error: 'Reconnecting...' })
      })

      room.on(RoomEvent.Reconnected, () => {
        setState({ isListening: true, error: null })
      })

      await room.connect(tokenRes.url, tokenRes.token)
      // Enable audio playback — required by browsers due to autoplay policy
      await room.startAudio()

      // Attach tracks from participants already in the room when we join
      for (const participant of room.remoteParticipants.values()) {
        for (const publication of participant.audioTrackPublications.values()) {
          if (publication.track) attachTrack(publication.track)
        }
      }

      setState({ isListening: true, error: null })
    } catch {
      setState({ isListening: false, error: 'Failed to connect to call audio' })
    }
  }, [convId])

  const stopListening = useCallback(() => {
    userStoppedRef.current = true
    if (roomRef.current) {
      roomRef.current.disconnect()
      roomRef.current = null
    }
    document.querySelectorAll('[data-supervisor-audio]').forEach(el => el.remove())
    setState({ isListening: false, error: null })
  }, [])

  useEffect(() => {
    return () => {
      roomRef.current?.disconnect()
      roomRef.current = null
    }
  }, [convId])

  return { ...state, startListening, stopListening }
}

// ---------------------------------------------------------------------------
// Whisper — send guidance to AI (LiveKit data channel)
// ---------------------------------------------------------------------------

export function useSupervisorWhisper(convId: string | null) {
  return useMutation({
    mutationFn: async (message: string) => {
      if (!convId) throw new Error('No conversation selected')
      return api.post(`/supervisor/livekit-whisper/${convId}`, { message })
    },
  })
}

// ---------------------------------------------------------------------------
// Barge — take over call via LiveKit
// ---------------------------------------------------------------------------

interface BargeResult {
  status: string
  conference_name?: string
  token?: string
  url?: string
  room?: string
  message: string
}

export function useSupervisorBarge(convId: string | null) {
  return useMutation({
    mutationFn: async (): Promise<BargeResult> => {
      if (!convId) throw new Error('No conversation selected')
      const result = await api.post<BargeResult>(`/supervisor/livekit-barge/${convId}`)
      if (result.token && result.url) {
        const { Room } = await import('livekit-client')
        const room = new Room()
        await room.connect(result.url, result.token)
        await room.localParticipant.setMicrophoneEnabled(true)
      }
      return result
    },
  })
}

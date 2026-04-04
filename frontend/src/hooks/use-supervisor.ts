import { useState, useEffect, useRef, useCallback } from 'react'
import { useMutation } from '@tanstack/react-query'
import type { Room } from 'livekit-client'
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
  // Legacy fallback refs
  const wsRef = useRef<WebSocket | null>(null)
  const audioCtxRef = useRef<AudioContext | null>(null)
  const nextPlayTimeRef = useRef(0)

  const startListening = useCallback(async () => {
    if (!convId) return
    userStoppedRef.current = false

    // Try LiveKit first
    try {
      const tokenRes = await api.post<{ token: string; url: string; room: string }>(
        `/supervisor/livekit-token/${convId}`,
        { mode: 'listen' },
      )

      // Dynamically import livekit-client
      const { Room, RoomEvent } = await import('livekit-client')
      const room = new Room()
      roomRef.current = room

      room.on(RoomEvent.Disconnected, () => {
        setState({ isListening: false, error: null })
        roomRef.current = null
      })

      room.on(RoomEvent.Reconnecting, () => {
        setState({ isListening: true, error: 'Reconnecting...' })
      })

      room.on(RoomEvent.Reconnected, () => {
        setState({ isListening: true, error: null })
      })

      await room.connect(tokenRes.url, tokenRes.token)
      setState({ isListening: true, error: null })
      return
    } catch {
      // LiveKit not available, fall back to legacy WebSocket
    }

    // Legacy WebSocket fallback
    if (wsRef.current) return
    const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
    const url = `${proto}://${window.location.host}/api/v1/supervisor/listen/${convId}`
    const ws = new WebSocket(url)
    wsRef.current = ws

    const audioCtx = new AudioContext({ sampleRate: 8000 })
    audioCtxRef.current = audioCtx
    nextPlayTimeRef.current = 0

    ws.onopen = () => setState({ isListening: true, error: null })

    ws.onmessage = (evt) => {
      try {
        const data = JSON.parse(evt.data)
        if (data.keepalive || !data.audio) return
        if (data.error) {
          setState({ isListening: false, error: data.error })
          ws.close()
          return
        }

        const raw = atob(data.audio)
        const mulaw = new Uint8Array(raw.length)
        for (let i = 0; i < raw.length; i++) mulaw[i] = raw.charCodeAt(i)

        const pcm = decodeMulaw(mulaw)
        const buffer = audioCtx.createBuffer(1, pcm.length, 8000)
        buffer.getChannelData(0).set(pcm)
        const source = audioCtx.createBufferSource()
        source.buffer = buffer
        source.connect(audioCtx.destination)

        const now = audioCtx.currentTime
        const startAt = Math.max(now, nextPlayTimeRef.current)
        source.start(startAt)
        nextPlayTimeRef.current = startAt + buffer.duration
      } catch {
        // ignore decode errors
      }
    }

    let reconnectAttempts = 0
    const maxReconnectAttempts = 3

    ws.onerror = () => setState({ isListening: false, error: 'WebSocket connection failed' })
    ws.onclose = () => {
      wsRef.current = null
      // Auto-reconnect if we were listening and stop wasn't user-initiated
      if (reconnectAttempts < maxReconnectAttempts && !userStoppedRef.current) {
        reconnectAttempts++
        setState({ isListening: true, error: `Reconnecting (${reconnectAttempts}/${maxReconnectAttempts})...` })
        setTimeout(() => {
          if (!wsRef.current) startListening()
        }, 1000 * reconnectAttempts) // backoff: 1s, 2s, 3s
      } else {
        setState({
          isListening: false,
          error: reconnectAttempts >= maxReconnectAttempts ? 'Connection lost after retries' : null,
        })
      }
    }
  }, [convId])

  const stopListening = useCallback(() => {
    userStoppedRef.current = true
    // LiveKit cleanup
    if (roomRef.current) {
      roomRef.current.disconnect()
      roomRef.current = null
    }
    // Legacy cleanup
    wsRef.current?.close()
    wsRef.current = null
    audioCtxRef.current?.close()
    audioCtxRef.current = null
    nextPlayTimeRef.current = 0
    setState({ isListening: false, error: null })
  }, [])

  useEffect(() => {
    return () => {
      roomRef.current?.disconnect()
      roomRef.current = null
      wsRef.current?.close()
      wsRef.current = null
      audioCtxRef.current?.close()
      audioCtxRef.current = null
    }
  }, [convId])

  return { ...state, startListening, stopListening }
}

// ---------------------------------------------------------------------------
// Whisper — send guidance to AI (LiveKit data channel or legacy HTTP)
// ---------------------------------------------------------------------------

export function useSupervisorWhisper(convId: string | null) {
  return useMutation({
    mutationFn: async (message: string) => {
      if (!convId) throw new Error('No conversation selected')
      // Try LiveKit whisper first, fall back to legacy
      try {
        return await api.post(`/supervisor/livekit-whisper/${convId}`, { message })
      } catch {
        return api.post(`/supervisor/whisper/${convId}`, { message })
      }
    },
  })
}

// ---------------------------------------------------------------------------
// Barge — take over call (LiveKit or legacy)
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
      // Try LiveKit barge first, fall back to legacy
      try {
        const result = await api.post<BargeResult>(`/supervisor/livekit-barge/${convId}`)
        // If LiveKit barge returns a token, connect to room with mic
        if (result.token && result.url) {
          const { Room } = await import('livekit-client')
          const room = new Room()
          await room.connect(result.url, result.token)
          await room.localParticipant.setMicrophoneEnabled(true)
        }
        return result
      } catch {
        return api.post(`/supervisor/barge/${convId}`)
      }
    },
  })
}

// ---------------------------------------------------------------------------
// Mulaw decoder (legacy fallback — ITU G.711 mu-law -> Float32 PCM)
// ---------------------------------------------------------------------------

const MULAW_BIAS = 33

function decodeMulaw(mulaw: Uint8Array): Float32Array {
  const pcm = new Float32Array(mulaw.length)
  for (let i = 0; i < mulaw.length; i++) {
    let mu = ~mulaw[i] & 0xff
    const sign = (mu & 0x80) ? -1 : 1
    const exponent = (mu >> 4) & 0x07
    const mantissa = mu & 0x0f
    let sample = ((mantissa << 1) + MULAW_BIAS) << exponent
    sample = sign * (sample - MULAW_BIAS)
    pcm[i] = sample / 32768.0
  }
  return pcm
}

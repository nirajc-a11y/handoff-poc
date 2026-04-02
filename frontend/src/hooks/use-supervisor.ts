import { useState, useEffect, useRef, useCallback } from 'react'
import { useMutation } from '@tanstack/react-query'
import { api } from '@/lib/api'

// ---------------------------------------------------------------------------
// Listen — stream live audio from an active call
// ---------------------------------------------------------------------------

interface ListenState {
  isListening: boolean
  error: string | null
}

export function useSupervisorListen(convId: string | null) {
  const [state, setState] = useState<ListenState>({ isListening: false, error: null })
  const wsRef = useRef<WebSocket | null>(null)
  const audioCtxRef = useRef<AudioContext | null>(null)
  const nextPlayTimeRef = useRef(0)

  const startListening = useCallback(() => {
    if (!convId || wsRef.current) return

    const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
    const url = `${proto}://${window.location.host}/api/v1/supervisor/listen/${convId}`
    const ws = new WebSocket(url)
    wsRef.current = ws

    // Web Audio API — schedule buffers sequentially to avoid overlaps/gaps
    const audioCtx = new AudioContext({ sampleRate: 8000 })
    audioCtxRef.current = audioCtx
    nextPlayTimeRef.current = 0

    ws.onopen = () => {
      setState({ isListening: true, error: null })
    }

    ws.onmessage = (evt) => {
      try {
        const data = JSON.parse(evt.data)
        if (data.keepalive || !data.audio) return
        if (data.error) {
          setState({ isListening: false, error: data.error })
          ws.close()
          return
        }

        // Decode base64 mulaw
        const raw = atob(data.audio)
        const mulaw = new Uint8Array(raw.length)
        for (let i = 0; i < raw.length; i++) mulaw[i] = raw.charCodeAt(i)

        // Convert mulaw -> PCM float32
        const pcm = decodeMulaw(mulaw)

        // Create audio buffer and schedule it after the previous one
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

    ws.onerror = () => {
      setState({ isListening: false, error: 'WebSocket connection failed' })
    }

    ws.onclose = () => {
      setState((s) => ({ ...s, isListening: false }))
      wsRef.current = null
    }
  }, [convId])

  const stopListening = useCallback(() => {
    wsRef.current?.close()
    wsRef.current = null
    audioCtxRef.current?.close()
    audioCtxRef.current = null
    nextPlayTimeRef.current = 0
    setState({ isListening: false, error: null })
  }, [])

  // Clean up on unmount or convId change
  useEffect(() => {
    return () => {
      wsRef.current?.close()
      wsRef.current = null
      audioCtxRef.current?.close()
      audioCtxRef.current = null
    }
  }, [convId])

  return { ...state, startListening, stopListening }
}

// ---------------------------------------------------------------------------
// Whisper — send guidance to AI
// ---------------------------------------------------------------------------

export function useSupervisorWhisper(convId: string | null) {
  return useMutation({
    mutationFn: async (message: string) => {
      if (!convId) throw new Error('No conversation selected')
      return api.post(`/supervisor/whisper/${convId}`, { message })
    },
  })
}

// ---------------------------------------------------------------------------
// Barge — take over call
// ---------------------------------------------------------------------------

interface BargeResult {
  status: string
  conference_name: string
  message: string
}

export function useSupervisorBarge(convId: string | null) {
  return useMutation({
    mutationFn: async (): Promise<BargeResult> => {
      if (!convId) throw new Error('No conversation selected')
      return api.post(`/supervisor/barge/${convId}`)
    },
  })
}

// ---------------------------------------------------------------------------
// Mulaw decoder (ITU G.711 mu-law -> Float32 PCM)
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

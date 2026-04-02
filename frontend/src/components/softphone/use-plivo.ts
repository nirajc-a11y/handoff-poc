import { useState, useCallback, useEffect, useRef } from 'react'
import { useSetAtom } from 'jotai'
import { plivoRegisteredAtom, plivoOnCallAtom, plivoRingingAtom } from '@/stores/softphone'

declare global {
  interface Window {
    Plivo: any
  }
}

interface PlivoState {
  isRegistered: boolean
  isRinging: boolean
  isOnCall: boolean
  isMuted: boolean
  isOnHold: boolean
  callerId: string | null
  callDuration: number
}

export function usePlivo() {
  const [state, setState] = useState<PlivoState>({
    isRegistered: false, isRinging: false, isOnCall: false,
    isMuted: false, isOnHold: false, callerId: null, callDuration: 0,
  })
  const plivoRef = useRef<any>(null)
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const setGlobalRegistered = useSetAtom(plivoRegisteredAtom)
  const setGlobalOnCall = useSetAtom(plivoOnCallAtom)
  const setGlobalRinging = useSetAtom(plivoRingingAtom)

  // Load Plivo SDK script dynamically
  useEffect(() => {
    if (document.querySelector('script[src*="plivo.min.js"]')) return
    const script = document.createElement('script')
    script.src = 'https://cdn.plivo.com/sdk/browser/v2/plivo.min.js'
    script.async = true
    document.head.appendChild(script)
  }, [])

  // Clean up timer on unmount
  useEffect(() => {
    return () => {
      if (timerRef.current) {
        clearInterval(timerRef.current)
        timerRef.current = null
      }
    }
  }, [])

  // Sync local state to global atoms for header indicator
  useEffect(() => {
    setGlobalRegistered(state.isRegistered)
    setGlobalOnCall(state.isOnCall)
    setGlobalRinging(state.isRinging)
  }, [state.isRegistered, state.isOnCall, state.isRinging, setGlobalRegistered, setGlobalOnCall, setGlobalRinging])

  const startTimer = useCallback(() => {
    if (timerRef.current) { clearInterval(timerRef.current); timerRef.current = null }
    setState(s => ({ ...s, callDuration: 0 }))
    timerRef.current = setInterval(() => {
      setState(s => ({ ...s, callDuration: s.callDuration + 1 }))
    }, 1000)
  }, [])

  const stopTimer = useCallback(() => {
    if (timerRef.current) { clearInterval(timerRef.current); timerRef.current = null }
    setState(s => ({ ...s, callDuration: 0 }))
  }, [])

  const login = useCallback((username: string, password: string) => {
    if (!window.Plivo) { console.error('Plivo SDK not loaded'); return }
    try {
      const p = new window.Plivo({ debug: 'ALL', permOnClick: true, enableTracking: true })
      plivoRef.current = p

      p.client.on('onLogin', () => setState(s => ({ ...s, isRegistered: true })))
      p.client.on('onLoginFailed', () => setState(s => ({ ...s, isRegistered: false })))
      p.client.on('onIncomingCall', (callerId: string) => {
        setState(s => ({ ...s, isRinging: true, callerId }))
      })
      p.client.on('onIncomingCallCanceled', () => {
        setState(s => ({ ...s, isRinging: false, callerId: null }))
      })
      p.client.on('onCallAnswered', () => {
        setState(s => ({ ...s, isRinging: false, isOnCall: true }))
        startTimer()
      })
      p.client.on('onCallTerminated', () => {
        setState(s => ({ ...s, isOnCall: false, isRinging: false, isMuted: false, isOnHold: false, callerId: null }))
        stopTimer()
      })
      p.client.on('onCallFailed', () => {
        setState(s => ({ ...s, isOnCall: false, isRinging: false, callerId: null }))
        stopTimer()
      })

      p.client.login(username, password)
    } catch (e) { console.error('Plivo init failed:', e) }
  }, [startTimer, stopTimer])

  const logout = useCallback(() => {
    plivoRef.current?.client?.logout()
    stopTimer()
    setState(s => ({ ...s, isRegistered: false }))
  }, [stopTimer])

  const answer = useCallback(() => plivoRef.current?.client?.answer(), [])

  const reject = useCallback(() => {
    plivoRef.current?.client?.reject()
    setState(s => ({ ...s, isRinging: false, callerId: null }))
  }, [])

  const call = useCallback((number: string) => {
    plivoRef.current?.client?.call(number, {})
    setState(s => ({ ...s, callerId: number }))
  }, [])

  const hangup = useCallback(() => plivoRef.current?.client?.hangup(), [])

  const toggleMute = useCallback(() => {
    if (state.isMuted) plivoRef.current?.client?.unmute()
    else plivoRef.current?.client?.mute()
    setState(s => ({ ...s, isMuted: !s.isMuted }))
  }, [state.isMuted])

  const toggleHold = useCallback(() => {
    if (state.isOnHold) plivoRef.current?.client?.unhold()
    else plivoRef.current?.client?.hold()
    setState(s => ({ ...s, isOnHold: !s.isOnHold }))
  }, [state.isOnHold])

  return { ...state, login, logout, answer, reject, call, hangup, toggleMute, toggleHold }
}

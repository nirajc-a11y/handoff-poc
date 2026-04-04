import { usePlivo } from './use-plivo'
import { SoftphoneLogin } from './softphone-login'
import { IncomingCall } from './incoming-call'
import { ActiveCall } from './active-call'
import { OutboundDialer } from '@/components/live/outbound-dialer'
import { LiveKitSoftphone } from './livekit-softphone'

// When USE_LIVEKIT is set, show the LiveKit-based softphone instead of Plivo.
// Both are rendered — Plivo handles SIP registration/outbound, LiveKit handles
// in-call audio for conversations routed through the LiveKit room.
const USE_LIVEKIT = import.meta.env.VITE_USE_LIVEKIT_AGENT === 'true'

export function SoftphonePanel() {
  const {
    isRegistered,
    isRinging,
    isOnCall,
    isMuted,
    isOnHold,
    callerId,
    callDuration,
    login,
    logout,
    answer,
    reject,
    hangup,
    toggleMute,
    toggleHold,
  } = usePlivo()

  return (
    <div className="flex flex-col gap-3">
      {/* LiveKit softphone for in-call audio (when enabled) */}
      {USE_LIVEKIT && <LiveKitSoftphone />}

      {/* Plivo SIP login / registration (still needed for outbound) */}
      {!USE_LIVEKIT && (
        <SoftphoneLogin
          isRegistered={isRegistered}
          onLogin={login}
          onLogout={logout}
        />
      )}

      {/* Incoming call (Plivo SIP) */}
      {isRinging && callerId && (
        <div className="rounded-sm border border-blue-200 bg-blue-50 p-1">
          <IncomingCall
            callerId={callerId}
            onAnswer={answer}
            onReject={reject}
          />
        </div>
      )}

      {/* Active call (Plivo — only when NOT using LiveKit) */}
      {!USE_LIVEKIT && isOnCall && callerId && (
        <div className="rounded-sm border border-green-200 bg-green-50 p-1">
          <ActiveCall
            callerId={callerId}
            duration={callDuration}
            isMuted={isMuted}
            isOnHold={isOnHold}
            onToggleMute={toggleMute}
            onToggleHold={toggleHold}
            onHangup={hangup}
          />
        </div>
      )}

      {/* Number pad — visible when registered and idle (Plivo) */}
      {!USE_LIVEKIT && isRegistered && !isRinging && !isOnCall && (
        <OutboundDialer />
      )}
    </div>
  )
}

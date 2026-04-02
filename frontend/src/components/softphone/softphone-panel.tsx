import { usePlivo } from './use-plivo'
import { SoftphoneLogin } from './softphone-login'
import { IncomingCall } from './incoming-call'
import { ActiveCall } from './active-call'
import { OutboundDialer } from '@/components/live/outbound-dialer'

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
      {/* Login / registration */}
      <SoftphoneLogin
        isRegistered={isRegistered}
        onLogin={login}
        onLogout={logout}
      />

      {/* Incoming call */}
      {isRinging && callerId && (
        <div className="rounded-sm border border-blue-200 bg-blue-50 p-1">
          <IncomingCall
            callerId={callerId}
            onAnswer={answer}
            onReject={reject}
          />
        </div>
      )}

      {/* Active call */}
      {isOnCall && callerId && (
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

      {/* Number pad — visible when registered and idle */}
      {isRegistered && !isRinging && !isOnCall && (
        <OutboundDialer />
      )}
    </div>
  )
}

import { useState } from 'react'
import { PhoneCall, ChevronDown, ChevronUp } from 'lucide-react'
import { usePlivo } from './use-plivo'
import { SoftphoneLogin } from './softphone-login'
import { IncomingCall } from './incoming-call'
import { ActiveCall } from './active-call'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

export function SoftphonePanel() {
  const [collapsed, setCollapsed] = useState(false)
  const [dialNumber, setDialNumber] = useState('')

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
    call,
    hangup,
    toggleMute,
    toggleHold,
  } = usePlivo()

  // Status dot color
  const statusDotClass = isOnCall
    ? 'bg-green-500'
    : isRinging
      ? 'bg-blue-500 animate-pulse'
      : isRegistered
        ? 'bg-green-400'
        : 'bg-gray-300'

  return (
    <div
      className={cn(
        'fixed bottom-4 right-4 z-50 w-[280px] overflow-hidden rounded-xl border border-gray-200 bg-white shadow-lg'
      )}
    >
      {/* Header */}
      <button
        onClick={() => setCollapsed(c => !c)}
        className="flex w-full items-center justify-between border-b border-gray-100 bg-gray-50 px-3 py-2 hover:bg-gray-100 transition-colors"
      >
        <div className="flex items-center gap-2">
          <PhoneCall className="size-3.5 text-gray-500" />
          <span className="text-xs font-semibold text-gray-700">Softphone</span>
          <span className={cn('inline-block size-2 rounded-full', statusDotClass)} />
        </div>
        {collapsed ? (
          <ChevronUp className="size-3.5 text-gray-400" />
        ) : (
          <ChevronDown className="size-3.5 text-gray-400" />
        )}
      </button>

      {/* Body */}
      {!collapsed && (
        <div className="flex flex-col">
          {/* Login / registered section */}
          <SoftphoneLogin
            isRegistered={isRegistered}
            onLogin={login}
            onLogout={logout}
          />

          {/* Incoming call overlay */}
          {isRinging && callerId && (
            <div className="border-t border-blue-100 bg-blue-50">
              <IncomingCall
                callerId={callerId}
                onAnswer={answer}
                onReject={reject}
              />
            </div>
          )}

          {/* Active call */}
          {isOnCall && callerId && (
            <div className="border-t border-green-100 bg-green-50">
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

          {/* Outbound dial pad — visible when registered & idle */}
          {isRegistered && !isRinging && !isOnCall && (
            <div className="flex gap-1.5 border-t border-gray-100 px-3 py-2">
              <Input
                placeholder="Enter number..."
                value={dialNumber}
                onChange={e => setDialNumber(e.target.value)}
                onKeyDown={e => {
                  if (e.key === 'Enter' && dialNumber.trim()) {
                    call(dialNumber.trim())
                    setDialNumber('')
                  }
                }}
                className="flex-1 text-xs"
              />
              <Button
                size="icon"
                disabled={!dialNumber.trim()}
                onClick={() => {
                  if (dialNumber.trim()) {
                    call(dialNumber.trim())
                    setDialNumber('')
                  }
                }}
                title="Call"
              >
                <PhoneCall className="size-3.5" />
              </Button>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

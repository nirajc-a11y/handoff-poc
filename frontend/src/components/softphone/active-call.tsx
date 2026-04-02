import { Mic, MicOff, Pause, Play, PhoneOff } from 'lucide-react'
import { cn } from '@/lib/utils'
import { formatDuration } from '@/lib/utils'

interface ActiveCallProps {
  callerId: string
  duration: number
  isMuted: boolean
  isOnHold: boolean
  onToggleMute: () => void
  onToggleHold: () => void
  onHangup: () => void
}

export function ActiveCall({
  callerId,
  duration,
  isMuted,
  isOnHold,
  onToggleMute,
  onToggleHold,
  onHangup,
}: ActiveCallProps) {
  return (
    <div className="flex flex-col items-center gap-4 p-4">
      {/* Caller info */}
      <div className="text-center">
        <p className="text-[10px] uppercase tracking-wider text-gray-400">On Call</p>
        <p className="mt-0.5 text-sm font-semibold text-gray-800">{callerId}</p>
        <p className="mt-0.5 font-mono text-lg font-bold tabular-nums text-green-600">
          {formatDuration(duration)}
        </p>
      </div>

      {/* Controls */}
      <div className="flex items-center gap-2">
        {/* Mute */}
        <button
          onClick={onToggleMute}
          title={isMuted ? 'Unmute' : 'Mute'}
          className={cn(
            'flex size-10 items-center justify-center rounded-lg border transition-colors active:scale-95',
            isMuted
              ? 'border-orange-300 bg-orange-100 text-orange-600'
              : 'border-gray-200 bg-gray-100 text-gray-600 hover:bg-gray-200'
          )}
        >
          {isMuted ? <MicOff className="size-4" /> : <Mic className="size-4" />}
        </button>

        {/* Hold */}
        <button
          onClick={onToggleHold}
          title={isOnHold ? 'Resume' : 'Hold'}
          className={cn(
            'flex size-10 items-center justify-center rounded-lg border transition-colors active:scale-95',
            isOnHold
              ? 'border-yellow-300 bg-yellow-100 text-yellow-700'
              : 'border-gray-200 bg-gray-100 text-gray-600 hover:bg-gray-200'
          )}
        >
          {isOnHold ? <Play className="size-4" /> : <Pause className="size-4" />}
        </button>

        {/* Hang up */}
        <button
          onClick={onHangup}
          title="End Call"
          className="flex size-10 items-center justify-center rounded-full bg-red-500 text-white shadow transition-colors hover:bg-red-600 active:scale-95"
        >
          <PhoneOff className="size-4" />
        </button>
      </div>
    </div>
  )
}

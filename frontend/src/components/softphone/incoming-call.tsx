import { Phone, PhoneOff } from 'lucide-react'

interface IncomingCallProps {
  callerId: string
  onAnswer: () => void
  onReject: () => void
}

export function IncomingCall({ callerId, onAnswer, onReject }: IncomingCallProps) {
  return (
    <div className="flex flex-col items-center gap-3 px-3 py-3">
      {/* Pulsing ring animation */}
      <div className="relative flex items-center justify-center">
        <span className="absolute inline-flex size-12 animate-ping rounded-full bg-green-400 opacity-40" />
        <span className="relative inline-flex size-9 items-center justify-center rounded-full bg-green-100">
          <Phone className="size-4 text-green-600" />
        </span>
      </div>

      <div className="text-center">
        <p className="text-[10px] uppercase tracking-wider text-gray-400">Incoming Call</p>
        <p className="mt-0.5 text-sm font-semibold text-gray-800">{callerId}</p>
      </div>

      <div className="flex items-center gap-3">
        <button
          onClick={onReject}
          className="flex size-11 items-center justify-center rounded-lg bg-red-500 text-white shadow transition-transform hover:bg-red-600 active:scale-95"
          title="Reject"
        >
          <PhoneOff className="size-4" />
        </button>
        <button
          onClick={onAnswer}
          className="flex size-11 items-center justify-center rounded-lg bg-green-500 text-white shadow transition-transform hover:bg-green-600 active:scale-95"
          title="Answer"
        >
          <Phone className="size-4" />
        </button>
      </div>
    </div>
  )
}

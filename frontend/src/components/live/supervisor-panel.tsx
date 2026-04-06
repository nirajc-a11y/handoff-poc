import { useState, useEffect } from 'react'
import { Headphones, Square, MessageSquare, PhoneForwarded, Send, AlertTriangle } from 'lucide-react'
import { useSupervisorListen, useSupervisorWhisper, useSupervisorBarge } from '@/hooks/use-supervisor'
import { cn } from '@/lib/utils'

interface SupervisorPanelProps {
  conversationId: string
  /** False when the call has ended — disables all controls */
  isActive: boolean
}

export function SupervisorPanel({ conversationId, isActive }: SupervisorPanelProps) {
  const listen = useSupervisorListen(conversationId)
  const whisper = useSupervisorWhisper(conversationId)
  const barge = useSupervisorBarge(conversationId)
  const [whisperText, setWhisperText] = useState('')
  const [bargeConfirm, setBargeConfirm] = useState(false)

  // Auto-stop listening when call ends
  useEffect(() => {
    if (!isActive && listen.isListening) {
      listen.stopListening()
    }
  }, [isActive, listen.isListening, listen.stopListening])

  const disabled = !isActive

  const handleWhisper = () => {
    if (!whisperText.trim() || disabled) return
    whisper.mutate(whisperText.trim(), {
      onSuccess: () => setWhisperText(''),
    })
  }

  const handleBarge = () => {
    if (disabled) return
    if (!bargeConfirm) {
      setBargeConfirm(true)
      return
    }
    barge.mutate(undefined, {
      onSuccess: () => setBargeConfirm(false),
    })
  }

  return (
    <div className="flex flex-col gap-4 p-4">
      {!isActive && (
        <div className="rounded-md bg-gray-50 border border-gray-200 px-3 py-2 text-center">
          <p className="text-xs text-gray-500">Call has ended. Supervision controls are disabled.</p>
        </div>
      )}

      {/* Listen Section */}
      <div className={cn('rounded-lg border bg-card p-3', disabled && 'opacity-50')}>
        <div className="flex items-center justify-between mb-2">
          <div className="flex items-center gap-2">
            <Headphones className="size-4 text-gray-500" />
            <span className="text-sm font-medium">Live Listen</span>
          </div>
          {listen.isListening && (
            <span className="flex items-center gap-1">
              <span className="size-2 rounded-full bg-green-500 animate-pulse" />
              <span className="text-xs text-green-600">Listening</span>
            </span>
          )}
        </div>
        <p className="text-xs text-muted-foreground mb-3">
          Hear the live call audio (caller + AI) without being heard.
        </p>
        {listen.error && (
          <p className="text-xs text-red-500 mb-2">{listen.error}</p>
        )}
        <button
          onClick={listen.isListening ? listen.stopListening : listen.startListening}
          disabled={disabled && !listen.isListening}
          className={cn(
            'w-full rounded-md px-3 py-2 text-sm font-medium transition-colors',
            listen.isListening
              ? 'bg-red-50 text-red-700 hover:bg-red-100 border border-red-200'
              : 'bg-green-50 text-green-700 hover:bg-green-100 border border-green-200',
            disabled && !listen.isListening && 'cursor-not-allowed'
          )}
        >
          {listen.isListening ? (
            <span className="flex items-center justify-center gap-2">
              <Square className="size-4" /> Stop Listening
            </span>
          ) : (
            <span className="flex items-center justify-center gap-2">
              <Headphones className="size-4" /> Start Listening
            </span>
          )}
        </button>
      </div>

      {/* Whisper Section */}
      <div className={cn('rounded-lg border bg-card p-3', disabled && 'opacity-50')}>
        <div className="flex items-center gap-2 mb-2">
          <MessageSquare className="size-4 text-gray-500" />
          <span className="text-sm font-medium">Whisper to AI</span>
        </div>
        <p className="text-xs text-muted-foreground mb-3">
          Send guidance to the AI agent. The customer won't hear this — the AI will incorporate it in its next response.
        </p>
        <div className="flex gap-2">
          <input
            type="text"
            value={whisperText}
            onChange={(e) => setWhisperText(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && handleWhisper()}
            placeholder="e.g. Mention the Pro plan discount..."
            disabled={disabled}
            className="flex-1 rounded-md border px-3 py-1.5 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-blue-400 disabled:cursor-not-allowed"
          />
          <button
            onClick={handleWhisper}
            disabled={!whisperText.trim() || whisper.isPending || disabled}
            className="rounded-md bg-blue-600 px-3 py-1.5 text-white text-sm hover:bg-blue-700 disabled:opacity-50 transition-colors"
          >
            <Send className="size-4" />
          </button>
        </div>
        {whisper.isSuccess && (
          <p className="text-xs text-green-600 mt-2">Hint sent — AI will use it next turn.</p>
        )}
        {whisper.isError && (
          <p className="text-xs text-red-500 mt-2">Failed to send hint.</p>
        )}
      </div>

      {/* Barge Section */}
      <div className={cn('rounded-lg border bg-card p-3', disabled && 'opacity-50')}>
        <div className="flex items-center gap-2 mb-2">
          <PhoneForwarded className="size-4 text-gray-500" />
          <span className="text-sm font-medium">Take Over Call</span>
        </div>
        <p className="text-xs text-muted-foreground mb-3">
          Mute the AI agent and join the call directly. The AI will stop and you'll speak to the customer via softphone.
        </p>
        {barge.isSuccess && (
          <div className="rounded-md bg-green-50 border border-green-200 p-2 mb-3">
            <p className="text-xs text-green-700 font-medium">Call taken over successfully.</p>
            <p className="text-xs text-green-600 mt-1">
              Room: <code className="bg-green-100 px-1 rounded">{barge.data?.room}</code>
            </p>
            <p className="text-xs text-green-600">You are now connected — your mic is live.</p>
          </div>
        )}
        {barge.isError && (
          <p className="text-xs text-red-500 mb-2">Failed to take over call.</p>
        )}
        <button
          onClick={handleBarge}
          disabled={barge.isPending || barge.isSuccess || disabled}
          className={cn(
            'w-full rounded-md px-3 py-2 text-sm font-medium transition-colors',
            bargeConfirm
              ? 'bg-red-600 text-white hover:bg-red-700'
              : 'bg-orange-50 text-orange-700 hover:bg-orange-100 border border-orange-200',
            (barge.isPending || barge.isSuccess || disabled) && 'opacity-50 cursor-not-allowed'
          )}
        >
          {barge.isPending ? (
            'Taking over...'
          ) : bargeConfirm ? (
            <span className="flex items-center justify-center gap-2">
              <AlertTriangle className="size-4" /> Confirm: Mute AI & Take Over
            </span>
          ) : (
            <span className="flex items-center justify-center gap-2">
              <PhoneForwarded className="size-4" /> Take Over Call
            </span>
          )}
        </button>
        {bargeConfirm && !barge.isPending && (
          <button
            onClick={() => setBargeConfirm(false)}
            className="w-full mt-1 rounded-md px-3 py-1.5 text-xs text-gray-500 hover:text-gray-700 transition-colors"
          >
            Cancel
          </button>
        )}
      </div>
    </div>
  )
}

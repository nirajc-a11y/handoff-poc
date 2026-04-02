import { useState, useEffect, useRef } from 'react'
import { useAtomValue, useSetAtom } from 'jotai'
import { Phone, PhoneIncoming, PhoneOutgoing, Clock, Bot, Headphones, GitBranch, Copy, Check, X } from 'lucide-react'
import { selectedConvIdAtom } from '@/stores/ui'
import { useConversation, useConversationHandoffs } from '@/hooks/use-conversations'
import { useEmailThread } from '@/hooks/use-email-thread'
import { cn, stateColors, channelIcons, formatDuration, formatTime, timeSince } from '@/lib/utils'
import { Badge } from '@/components/ui/badge'
import { Separator } from '@/components/ui/separator'
import { MessageThread } from './message-thread'
import { MessageInput } from './message-input'
import { TranscriptPanel } from './transcript-panel'
import { ActionBar } from './action-bar'

const FLOW_STEPS = [
  { key: 'initiated', label: 'Initiated', icon: Phone },
  { key: 'ringing', label: 'Ringing', icon: PhoneOutgoing },
  { key: 'ivr', label: 'IVR', icon: GitBranch },
  { key: 'ai_handling', label: 'AI Agent', icon: Bot },
  { key: 'queued_for_human', label: 'Queued', icon: Clock },
  { key: 'human_handling', label: 'Agent', icon: Headphones },
  { key: 'ended', label: 'Ended', icon: Phone },
] as const

function CallFlowBar({ state }: { state: string }) {
  const currentIdx = FLOW_STEPS.findIndex(s => s.key === state)

  return (
    <div className="flex items-center gap-0.5 overflow-x-auto">
      {FLOW_STEPS.map((step, i) => {
        const Icon = step.icon
        const isPast = i < currentIdx
        const isCurrent = step.key === state
        const isFuture = i > currentIdx

        return (
          <div key={step.key} className="flex items-center">
            {i > 0 && (
              <div className={cn(
                'h-px w-3 shrink-0',
                isPast ? 'bg-green-400' : isCurrent ? 'bg-blue-400' : 'bg-gray-200'
              )} />
            )}
            <div className={cn(
              'flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-medium whitespace-nowrap transition-all',
              isCurrent && 'bg-blue-100 text-blue-700 ring-1 ring-blue-300',
              isPast && 'bg-green-50 text-green-600',
              isFuture && 'bg-gray-50 text-gray-400',
            )}>
              <Icon className="size-3" />
              <span className="hidden sm:inline">{step.label}</span>
            </div>
          </div>
        )
      })}
    </div>
  )
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false)
  const handleCopy = () => {
    navigator.clipboard.writeText(text)
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }
  return (
    <button onClick={handleCopy} className="text-gray-400 hover:text-gray-600 transition-colors">
      {copied ? <Check className="size-3 text-green-500" /> : <Copy className="size-3" />}
    </button>
  )
}

function LiveTimer({ startedAt, endedAt }: { startedAt: string; endedAt: string | null }) {
  const [elapsed, setElapsed] = useState(() => timeSince(startedAt))

  useEffect(() => {
    if (endedAt) return
    const timer = setInterval(() => setElapsed(timeSince(startedAt)), 1000)
    return () => clearInterval(timer)
  }, [startedAt, endedAt])

  return (
    <span className="font-mono text-xs tabular-nums">
      {endedAt ? formatDuration(Math.floor((new Date(endedAt).getTime() - new Date(startedAt).getTime()) / 1000)) : formatDuration(elapsed)}
    </span>
  )
}

export function ConversationDetail() {
  const selectedId = useAtomValue(selectedConvIdAtom)
  const setSelectedId = useSetAtom(selectedConvIdAtom)
  const { data: conversation, isLoading } = useConversation(selectedId)
  const { data: handoffs = [] } = useConversationHandoffs(selectedId)
  const [tab, setTab] = useState<'messages' | 'transcript' | 'handoffs' | 'email-thread'>('messages')
  const scrollRef = useRef<HTMLDivElement>(null)

  if (!selectedId) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3 bg-white border-x border-gray-200">
        <div className="flex size-16 items-center justify-center rounded-2xl bg-gray-50">
          <Phone className="size-7 text-gray-300" />
        </div>
        <div className="text-center">
          <p className="text-sm font-medium text-gray-500">No conversation selected</p>
          <p className="text-xs text-gray-400 mt-1">Click a conversation from the list to view details</p>
        </div>
      </div>
    )
  }

  if (isLoading || !conversation) {
    return (
      <div className="flex h-full items-center justify-center bg-white border-x border-gray-200">
        <div className="flex items-center gap-2 text-gray-400">
          <div className="size-4 animate-spin rounded-full border-2 border-gray-300 border-t-blue-500" />
          <p className="text-sm">Loading...</p>
        </div>
      </div>
    )
  }

  const channelIcon = channelIcons[conversation.channel] ?? '?'
  const stateClass = stateColors[conversation.state] ?? 'bg-gray-100 text-gray-700'
  const displayName = conversation.customer_name || 'Unknown'
  const phoneNumber = conversation.customer_identifier
  const isInbound = conversation.direction === 'inbound'
  const lang = (conversation.context as Record<string, string>)?.language

  return (
    <div className="flex h-full flex-col overflow-hidden bg-white border-x border-gray-200">
      {/* Customer header */}
      <div className="shrink-0 border-b border-gray-200 px-4 py-3 space-y-2.5">
        {/* Row 1: Customer info */}
        <div className="flex items-start justify-between gap-3">
          <div className="flex items-center gap-3">
            <div className={cn(
              'flex size-10 items-center justify-center rounded-full text-lg',
              isInbound ? 'bg-green-50' : 'bg-blue-50'
            )}>
              {isInbound ? <PhoneIncoming className="size-5 text-green-600" /> : <PhoneOutgoing className="size-5 text-blue-600" />}
            </div>
            <div className="flex flex-col gap-0.5">
              <div className="flex items-center gap-2">
                <span className="text-sm font-semibold text-gray-900">{displayName}</span>
                {lang && (
                  <Badge variant="secondary" className="h-4 text-[9px] font-medium uppercase">
                    {lang === 'mr' ? '🇮🇳 MR' : '🇬🇧 EN'}
                  </Badge>
                )}
              </div>
              <div className="flex items-center gap-1.5">
                <span className="text-xs text-gray-600 font-mono">{phoneNumber}</span>
                <CopyButton text={phoneNumber} />
              </div>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <Badge variant="secondary" className="h-5 text-[10px] gap-1">
              <span>{channelIcon}</span> {conversation.channel}
            </Badge>
            <Badge variant="secondary" className={cn('h-5 text-[10px]', stateClass)}>
              {conversation.state.replace(/_/g, ' ')}
            </Badge>
            <button
              onClick={() => setSelectedId(null)}
              className="ml-1 rounded-md p-1 text-gray-400 hover:bg-gray-100 hover:text-gray-600 transition-colors"
              aria-label="Close panel"
            >
              <X className="size-4" />
            </button>
          </div>
        </div>

        {/* Row 2: Call flow + duration */}
        <div className="flex items-center justify-between gap-3">
          <CallFlowBar state={conversation.state} />
          <div className="flex items-center gap-1.5 shrink-0 text-gray-500">
            <Clock className="size-3" />
            <LiveTimer startedAt={conversation.started_at} endedAt={conversation.ended_at} />
          </div>
        </div>

        {/* Row 3: Handler info */}
        <div className="flex items-center gap-3 text-[11px] text-gray-500">
          <div className="flex items-center gap-1">
            {conversation.current_handler_type === 'ai' && <Bot className="size-3" />}
            {conversation.current_handler_type === 'human' && <Headphones className="size-3" />}
            {conversation.current_handler_type === 'ivr' && <GitBranch className="size-3" />}
            {conversation.current_handler_type === 'system' && <Phone className="size-3" />}
            <span className="capitalize">{conversation.current_handler_type}</span>
            {conversation.current_handler_id && <span className="text-gray-400">({conversation.current_handler_id.slice(0, 8)})</span>}
          </div>
          <Separator orientation="vertical" className="h-3" />
          <span>{isInbound ? 'Inbound' : 'Outbound'}</span>
          {conversation.ai_confidence_score != null && (
            <>
              <Separator orientation="vertical" className="h-3" />
              <span>AI Confidence: {(conversation.ai_confidence_score * 100).toFixed(0)}%</span>
            </>
          )}
          {conversation.disposition && (
            <>
              <Separator orientation="vertical" className="h-3" />
              <Badge variant="secondary" className="h-4 text-[9px]">{conversation.disposition}</Badge>
            </>
          )}
        </div>

        {/* Full call recording player */}
        {conversation.recording_url && (
          <div className="flex items-center gap-2 pt-1">
            <span className="text-[10px] font-medium text-gray-500 shrink-0">Recording</span>
            <audio controls src={conversation.recording_url} className="h-7 w-full" controlsList="nodownload" preload="none" />
          </div>
        )}
      </div>

      {/* Tab bar */}
      <div className="shrink-0 flex gap-1 border-b border-gray-100 px-4 pt-1">
        {([
          { key: 'messages', label: 'Messages' },
          { key: 'transcript', label: 'Transcript' },
          { key: 'handoffs', label: `Handoffs${handoffs.length > 0 ? ` (${handoffs.length})` : ''}` },
          ...(conversation.channel === 'email' ? [{ key: 'email-thread', label: 'Email Thread' }] : []),
        ] as const).map((t) => (
          <button
            key={t.key}
            onClick={() => setTab(t.key as typeof tab)}
            className={cn(
              'px-2 py-1.5 text-xs font-medium transition-colors border-b-2 -mb-px',
              tab === t.key
                ? 'border-foreground text-foreground'
                : 'border-transparent text-muted-foreground hover:text-foreground'
            )}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* Scrollable content area */}
      <div
        ref={scrollRef}
        data-scroll-container
        className="min-h-0 flex-1 overflow-y-auto"
        style={{ scrollbarWidth: 'thin', scrollbarColor: '#cbd5e1 transparent' }}
      >
        {tab === 'messages' && <MessageThread conversationId={conversation.id} />}
        {tab === 'transcript' && <TranscriptPanel conversationId={conversation.id} />}
        {tab === 'handoffs' && <HandoffTimeline events={handoffs} />}
        {tab === 'email-thread' && <EmailThreadPanel conversationId={conversation.id} />}
      </div>

      {/* Message input (only on messages tab) */}
      {tab === 'messages' && (
        <div className="shrink-0">
          <MessageInput conversationId={conversation.id} channel={conversation.channel} />
        </div>
      )}

      {/* Action bar */}
      <ActionBar conversation={conversation} />
    </div>
  )
}

function HandoffTimeline({ events }: { events: import('@/lib/types').HandoffEvent[] }) {
  if (events.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center gap-2 py-12">
        <GitBranch className="size-6 text-gray-300" />
        <p className="text-xs text-gray-400">No handoff events yet</p>
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-2 p-4">
      {events.map((event, i) => (
        <div key={event.id ?? i} className="flex items-start gap-2">
          <div className="mt-0.5 size-5 rounded-full bg-gray-100 flex items-center justify-center shrink-0">
            <Phone className="size-3 text-gray-500" />
          </div>
          <div className="flex flex-col gap-0.5 min-w-0">
            <div className="flex items-center gap-1.5 text-xs">
              <span className="font-medium capitalize">{event.event_type.replace(/_/g, ' ')}</span>
              <span className="text-gray-400">{formatTime(event.created_at)}</span>
            </div>
            <div className="flex items-center gap-1 text-xs text-gray-500">
              {event.from_state && <span className="capitalize">{event.from_state.replace(/_/g, ' ')}</span>}
              {event.from_state && event.to_state && <span className="text-gray-300">-&gt;</span>}
              {event.to_state && <span className="capitalize">{event.to_state.replace(/_/g, ' ')}</span>}
            </div>
            {event.from_handler_type && event.to_handler_type && (
              <div className="flex items-center gap-1 text-[11px] text-gray-400">
                <span className="capitalize">{event.from_handler_type}</span>
                <span>-&gt;</span>
                <span className="capitalize">{event.to_handler_type}</span>
              </div>
            )}
            {event.reason && <p className="text-xs text-gray-400 truncate">{event.reason}</p>}
          </div>
        </div>
      ))}
    </div>
  )
}

function EmailThreadPanel({ conversationId }: { conversationId: string }) {
  const { data: thread = [], isLoading } = useEmailThread(conversationId)

  if (isLoading) {
    return <p className="py-8 text-center text-xs text-gray-400">Loading email thread…</p>
  }

  if (thread.length === 0) {
    return <p className="py-8 text-center text-xs text-gray-400">No emails in this thread</p>
  }

  return (
    <div className="flex flex-col gap-3 p-4">
      {thread.map((msg) => (
        <div key={msg.id} className="rounded-lg border bg-white p-3">
          <div className="flex items-center justify-between mb-1.5">
            <div className="flex items-center gap-2">
              <span className={cn(
                'text-xs font-medium capitalize',
                msg.sender_type === 'customer' ? 'text-blue-600' : 'text-gray-700'
              )}>
                {msg.sender_type}
              </span>
              {msg.email_subject && (
                <span className="text-xs text-gray-500 truncate max-w-48">{msg.email_subject}</span>
              )}
            </div>
            <span className="text-[10px] text-gray-400">{formatTime(msg.created_at)}</span>
          </div>
          <div
            className="text-xs text-gray-600 prose prose-xs max-w-none"
            dangerouslySetInnerHTML={{ __html: msg.content ?? '' }}
          />
        </div>
      ))}
    </div>
  )
}

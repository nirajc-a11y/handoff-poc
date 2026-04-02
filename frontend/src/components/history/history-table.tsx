import { useState } from 'react'
import { useConversations } from '@/hooks/use-conversations'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { Badge } from '@/components/ui/badge'
import { cn, formatDuration, stateColors, channelIcons } from '@/lib/utils'
import type { Conversation } from '@/lib/types'
import type { HistoryFiltersState } from './history-filters'
import { ArrowUpDown } from 'lucide-react'

interface HistoryTableProps {
  filters: HistoryFiltersState
  onSelectConversation: (id: string) => void
}

export function HistoryTable({ filters, onSelectConversation }: HistoryTableProps) {
  const [sortDesc, setSortDesc] = useState(true)

  const params: Record<string, string> = {}
  if (filters.channel && filters.channel !== 'all') params.channel = filters.channel
  if (filters.state && filters.state !== 'all') params.state = filters.state

  const { data: conversations = [], isLoading } = useConversations(
    Object.keys(params).length ? params : undefined
  )

  const filtered = conversations
    .filter((c) => {
      if (!filters.search) return true
      const q = filters.search.toLowerCase()
      return (
        c.customer_identifier.toLowerCase().includes(q) ||
        (c.customer_name?.toLowerCase().includes(q) ?? false)
      )
    })
    .sort((a, b) => {
      const ta = new Date(a.created_at).getTime()
      const tb = new Date(b.created_at).getTime()
      return sortDesc ? tb - ta : ta - tb
    })

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-16">
        <p className="text-sm text-muted-foreground">Loading conversations...</p>
      </div>
    )
  }

  if (filtered.length === 0) {
    return (
      <div className="flex items-center justify-center py-16">
        <p className="text-sm text-muted-foreground">No conversations found.</p>
      </div>
    )
  }

  return (
    <div className="rounded-xl ring-1 ring-foreground/10 overflow-hidden bg-card">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Customer</TableHead>
            <TableHead>Channel</TableHead>
            <TableHead>State</TableHead>
            <TableHead>Handler</TableHead>
            <TableHead>Duration</TableHead>
            <TableHead>Disposition</TableHead>
            <TableHead>
              <button
                className="flex items-center gap-1 hover:text-foreground"
                onClick={() => setSortDesc(!sortDesc)}
              >
                Date
                <ArrowUpDown className="size-3" />
              </button>
            </TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {filtered.map((conv) => (
            <ConversationRow
              key={conv.id}
              conversation={conv}
              onClick={() => onSelectConversation(conv.id)}
            />
          ))}
        </TableBody>
      </Table>
    </div>
  )
}

function ConversationRow({
  conversation: c,
  onClick,
}: {
  conversation: Conversation
  onClick: () => void
}) {
  const date = new Date(c.created_at)
  const dateStr = date.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
  const timeStr = date.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', hour12: false })

  return (
    <TableRow
      className="cursor-pointer hover:bg-muted/50"
      onClick={onClick}
    >
      <TableCell>
        <div>
          <p className="font-medium text-foreground">
            {c.customer_name ?? c.customer_identifier}
          </p>
          {c.customer_name && (
            <p className="text-xs text-muted-foreground">{c.customer_identifier}</p>
          )}
        </div>
      </TableCell>
      <TableCell>
        <span className="text-base" title={c.channel}>
          {channelIcons[c.channel] ?? c.channel}
        </span>
      </TableCell>
      <TableCell>
        <span
          className={cn(
            'inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium',
            stateColors[c.state] ?? 'bg-gray-100 text-gray-700'
          )}
        >
          {c.state.replace(/_/g, ' ')}
        </span>
      </TableCell>
      <TableCell>
        <span className="text-xs text-muted-foreground capitalize">
          {c.current_handler_type}
        </span>
      </TableCell>
      <TableCell>
        <span className="tabular-nums text-xs">{formatDuration(c.duration_seconds)}</span>
      </TableCell>
      <TableCell>
        {c.disposition ? (
          <Badge variant="outline" className="text-xs">
            {c.disposition}
          </Badge>
        ) : (
          <span className="text-xs text-muted-foreground">—</span>
        )}
      </TableCell>
      <TableCell>
        <div>
          <p className="text-xs">{dateStr}</p>
          <p className="text-xs text-muted-foreground">{timeStr}</p>
        </div>
      </TableCell>
    </TableRow>
  )
}

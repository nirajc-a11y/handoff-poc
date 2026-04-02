import { useState } from 'react'
import { HistoryFilters, type HistoryFiltersState } from '@/components/history/history-filters'
import { HistoryTable } from '@/components/history/history-table'
import { HistoryDetail } from '@/components/history/history-detail'
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet'
import { History } from 'lucide-react'

const defaultFilters: HistoryFiltersState = {
  channel: 'all',
  state: 'all',
  search: '',
}

export function HistoryPage() {
  const [filters, setFilters] = useState<HistoryFiltersState>(defaultFilters)
  const [selectedId, setSelectedId] = useState<string | null>(null)

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Page header */}
      <div className="flex items-center gap-2 border-b bg-background px-6 py-4 shrink-0">
        <History className="size-5 text-muted-foreground" />
        <h1 className="font-heading text-base font-medium">Conversation History</h1>
      </div>

      {/* Filters */}
      <div className="border-b bg-background px-6 py-3 shrink-0">
        <HistoryFilters filters={filters} onChange={setFilters} />
      </div>

      {/* Table */}
      <div className="flex-1 overflow-y-auto px-6 py-4">
        <HistoryTable
          filters={filters}
          onSelectConversation={setSelectedId}
        />
      </div>

      {/* Detail sheet */}
      <Sheet open={!!selectedId} onOpenChange={(open) => { if (!open) setSelectedId(null) }}>
        <SheetContent
          side="right"
          className="w-full sm:max-w-xl flex flex-col overflow-hidden p-0 gap-0"
        >
          <SheetHeader className="px-4 py-3 border-b shrink-0">
            <SheetTitle>Conversation Detail</SheetTitle>
          </SheetHeader>
          <div className="flex-1 overflow-y-auto">
            {selectedId && <HistoryDetail conversationId={selectedId} />}
          </div>
        </SheetContent>
      </Sheet>
    </div>
  )
}

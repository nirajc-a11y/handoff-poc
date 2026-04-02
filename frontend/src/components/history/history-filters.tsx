import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Search } from 'lucide-react'

export interface HistoryFiltersState {
  channel: string
  state: string
  search: string
}

interface HistoryFiltersProps {
  filters: HistoryFiltersState
  onChange: (filters: HistoryFiltersState) => void
}

export function HistoryFilters({ filters, onChange }: HistoryFiltersProps) {
  return (
    <div className="flex items-center gap-3">
      <Select
        value={filters.channel}
        onValueChange={(value) => onChange({ ...filters, channel: value ?? 'all' })}
      >
        <SelectTrigger className="w-36">
          <SelectValue placeholder="All Channels" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="all">All Channels</SelectItem>
          <SelectItem value="voice">Voice</SelectItem>
          <SelectItem value="whatsapp">WhatsApp</SelectItem>
          <SelectItem value="email">Email</SelectItem>
          <SelectItem value="sms">SMS</SelectItem>
        </SelectContent>
      </Select>

      <Select
        value={filters.state}
        onValueChange={(value) => onChange({ ...filters, state: value ?? 'all' })}
      >
        <SelectTrigger className="w-36">
          <SelectValue placeholder="All States" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="all">All States</SelectItem>
          <SelectItem value="ended">Ended</SelectItem>
          <SelectItem value="failed">Failed</SelectItem>
        </SelectContent>
      </Select>

      <div className="relative flex-1 max-w-xs">
        <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 size-3.5 text-muted-foreground pointer-events-none" />
        <Input
          className="pl-8"
          placeholder="Search customer..."
          value={filters.search}
          onChange={(e) => onChange({ ...filters, search: e.target.value })}
        />
      </div>
    </div>
  )
}

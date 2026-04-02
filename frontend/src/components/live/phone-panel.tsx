import { ScrollArea } from '@/components/ui/scroll-area'
import { SoftphonePanel } from '@/components/softphone/softphone-panel'

export function PhonePanel() {
  return (
    <div className="flex h-full flex-col border-l border-border bg-card">
      <div className="shrink-0 border-b border-border px-4 py-2">
        <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">
          Phone
        </h3>
      </div>
      <ScrollArea className="flex-1">
        <div className="p-3">
          <SoftphonePanel />
        </div>
      </ScrollArea>
    </div>
  )
}

import { cn } from '@/lib/utils'
import { Badge } from '@/components/ui/badge'
import type { IVRMenu } from '@/lib/types'
import { ListTree } from 'lucide-react'

interface IVRNodeProps {
  menu: IVRMenu
  selected: boolean
  onClick: () => void
}

export function IVRNode({ menu, selected, onClick }: IVRNodeProps) {
  const preview = menu.welcome_message
    ? menu.welcome_message.length > 60
      ? menu.welcome_message.slice(0, 60) + '…'
      : menu.welcome_message
    : 'No welcome message set'

  return (
    <button
      onClick={onClick}
      className={cn(
        'w-full text-left rounded-xl border bg-card p-3 transition-all hover:shadow-sm hover:border-ring/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50',
        selected && 'border-ring/60 bg-muted/50 shadow-sm'
      )}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          <div className="size-7 rounded-lg bg-violet-100 flex items-center justify-center shrink-0">
            <ListTree className="size-3.5 text-violet-700" />
          </div>
          <div className="min-w-0">
            <p className="text-sm font-medium truncate">{menu.name}</p>
            <p className="text-xs text-muted-foreground mt-0.5 truncate">{preview}</p>
          </div>
        </div>
        <div className="flex flex-col items-end gap-1 shrink-0">
          {menu.is_root && (
            <Badge variant="default" className="text-[10px] h-4">Root</Badge>
          )}
          <span className="text-[10px] text-muted-foreground">
            {(menu.options ?? []).length} option{(menu.options ?? []).length !== 1 ? 's' : ''}
          </span>
        </div>
      </div>
    </button>
  )
}

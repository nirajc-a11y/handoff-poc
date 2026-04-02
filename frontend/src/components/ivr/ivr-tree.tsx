import { useState } from 'react'
import { useIVRMenus } from '@/hooks/use-ivr'
import { IVRNode } from './ivr-node'
import { IVROptionForm } from './ivr-option-form'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import type { IVRMenuOption } from '@/lib/types'
import { Plus } from 'lucide-react'

const actionTypeStyles: Record<string, string> = {
  submenu: 'bg-blue-100 text-blue-700',
  ai_handoff: 'bg-violet-100 text-violet-700',
  human_queue: 'bg-green-100 text-green-700',
  play_message: 'bg-amber-100 text-amber-700',
  hangup: 'bg-red-100 text-red-700',
}

export function IVRTree() {
  const { data: menus = [], isLoading } = useIVRMenus()
  const [selectedMenuId, setSelectedMenuId] = useState<string | null>(null)
  const [showOptionForm, setShowOptionForm] = useState(false)

  const rootMenus = menus.filter((m) => m.is_root)
  const subMenus = menus.filter((m) => !m.is_root)
  const orderedMenus = [...rootMenus, ...subMenus]

  const selectedMenu = menus.find((m) => m.id === selectedMenuId)

  if (isLoading) {
    return (
      <div className="flex flex-1 items-center justify-center py-16">
        <p className="text-sm text-muted-foreground">Loading IVR menus...</p>
      </div>
    )
  }

  if (menus.length === 0) {
    return (
      <div className="flex flex-1 items-center justify-center py-16">
        <p className="text-sm text-muted-foreground">No IVR menus configured yet.</p>
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-2">
      {orderedMenus.map((menu) => (
        <div key={menu.id} className={cn(!menu.is_root && 'pl-4')}>
          <IVRNode
            menu={menu}
            selected={selectedMenuId === menu.id}
            onClick={() =>
              setSelectedMenuId(selectedMenuId === menu.id ? null : menu.id)
            }
          />

          {/* Options panel */}
          {selectedMenuId === menu.id && (
            <div className="mt-2 ml-2 rounded-xl border bg-muted/30 p-3">
              <div className="flex items-center justify-between mb-2">
                <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
                  Options
                </p>
                <Button
                  size="xs"
                  variant="outline"
                  onClick={() => setShowOptionForm(true)}
                  className="gap-1"
                >
                  <Plus className="size-3" />
                  Add Option
                </Button>
              </div>

              {(menu.options ?? []).length === 0 ? (
                <p className="text-xs text-muted-foreground py-2">No options configured.</p>
              ) : (
                <div className="flex flex-col gap-1.5">
                  {[...(menu.options ?? [])]
                    .sort((a, b) => a.sort_order - b.sort_order)
                    .map((opt) => (
                      <OptionRow key={opt.id} option={opt} />
                    ))}
                </div>
              )}
            </div>
          )}
        </div>
      ))}

      {selectedMenu && showOptionForm && (
        <IVROptionForm
          menuId={selectedMenu.id}
          open={showOptionForm}
          onClose={() => setShowOptionForm(false)}
        />
      )}
    </div>
  )
}

function OptionRow({ option }: { option: IVRMenuOption }) {
  const targetInfo =
    (option.target_config?.queue_name as string | undefined) ??
    (option.target_config?.label as string | undefined) ??
    option.target_id ??
    null

  return (
    <div className="flex items-center gap-2 rounded-lg bg-background border px-3 py-2">
      <div className="size-6 rounded-md bg-gray-100 flex items-center justify-center shrink-0">
        <span className="text-xs font-bold text-gray-700">{option.digit}</span>
      </div>
      <div className="flex-1 min-w-0">
        <p className="text-xs font-medium truncate">
          {option.label ?? '(no label)'}
        </p>
        {targetInfo && (
          <p className="text-[10px] text-muted-foreground truncate">{targetInfo}</p>
        )}
      </div>
      <span
        className={cn(
          'inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-medium whitespace-nowrap',
          actionTypeStyles[option.action_type] ?? 'bg-gray-100 text-gray-700'
        )}
      >
        {option.action_type.replace(/_/g, ' ')}
      </span>
    </div>
  )
}

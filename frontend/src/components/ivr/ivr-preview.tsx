import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import type { IVRMenu } from '@/lib/types'
import { Eye, Phone, ArrowRight } from 'lucide-react'
import { cn } from '@/lib/utils'

interface IVRPreviewProps {
  menus: IVRMenu[]
}

const actionTypeColors: Record<string, string> = {
  submenu: 'text-blue-600',
  ai_handoff: 'text-violet-600',
  human_queue: 'text-green-600',
  play_message: 'text-amber-600',
  hangup: 'text-red-600',
}

const actionTypeLabel: Record<string, string> = {
  submenu: 'Submenu',
  ai_handoff: 'AI',
  human_queue: 'Agent',
  play_message: 'Message',
  hangup: 'Hangup',
}

export function IVRPreview({ menus }: IVRPreviewProps) {
  const rootMenu = menus.find((m) => m.is_root)

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Eye className="size-4" />
          Call Flow Preview
        </CardTitle>
      </CardHeader>
      <CardContent>
        {!rootMenu ? (
          <p className="text-sm text-muted-foreground">No root menu configured.</p>
        ) : (
          <div className="flex flex-col gap-4">
            {/* Step 1: Customer calls */}
            <FlowStep
              number={1}
              label="Customer calls"
              description="Welcome message plays"
              message={rootMenu.welcome_message ?? undefined}
            />

            {/* Divider */}
            {(rootMenu.options ?? []).length > 0 && (
              <div className="flex items-center gap-2">
                <div className="flex-1 h-px bg-border" />
                <span className="text-xs text-muted-foreground">Press a key</span>
                <div className="flex-1 h-px bg-border" />
              </div>
            )}

            {/* Step 2: Options */}
            {(rootMenu.options ?? []).length > 0 && (
              <div className="rounded-xl border bg-muted/30 p-3">
                <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide mb-2">
                  Key Options
                </p>
                <div className="flex flex-col gap-2">
                  {[...(rootMenu.options ?? [])]
                    .sort((a, b) => a.sort_order - b.sort_order)
                    .map((opt) => {
                      const targetInfo =
                        (opt.target_config?.queue_name as string | undefined) ??
                        opt.label ??
                        opt.action_type

                      return (
                        <div key={opt.id} className="flex items-center gap-2 text-sm">
                          <div className="size-6 rounded-md bg-background border flex items-center justify-center shrink-0">
                            <span className="text-xs font-bold">{opt.digit}</span>
                          </div>
                          <ArrowRight className="size-3 text-muted-foreground shrink-0" />
                          <span className="text-xs">{opt.label ?? '(no label)'}</span>
                          <ArrowRight className="size-3 text-muted-foreground shrink-0" />
                          <span
                            className={cn(
                              'text-xs font-medium',
                              actionTypeColors[opt.action_type] ?? 'text-gray-600'
                            )}
                          >
                            {targetInfo} ({actionTypeLabel[opt.action_type] ?? opt.action_type})
                          </span>
                        </div>
                      )
                    })}
                </div>
              </div>
            )}

            {/* Sub-menus */}
            {menus.filter((m) => !m.is_root).length > 0 && (
              <>
                <div className="flex items-center gap-2">
                  <div className="flex-1 h-px bg-border" />
                  <span className="text-xs text-muted-foreground">Sub-menus</span>
                  <div className="flex-1 h-px bg-border" />
                </div>
                <div className="flex flex-col gap-2">
                  {menus
                    .filter((m) => !m.is_root)
                    .map((menu) => (
                      <div
                        key={menu.id}
                        className="rounded-lg border bg-muted/20 px-3 py-2"
                      >
                        <p className="text-xs font-medium">{menu.name}</p>
                        {(menu.options ?? []).length > 0 && (
                          <div className="mt-1.5 flex flex-col gap-1">
                            {[...(menu.options ?? [])]
                              .sort((a, b) => a.sort_order - b.sort_order)
                              .map((opt) => (
                                <div key={opt.id} className="flex items-center gap-1.5 text-xs text-muted-foreground">
                                  <span className="font-medium text-foreground">{opt.digit}</span>
                                  <ArrowRight className="size-2.5" />
                                  <span>{opt.label ?? opt.action_type}</span>
                                </div>
                              ))}
                          </div>
                        )}
                      </div>
                    ))}
                </div>
              </>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  )
}

function FlowStep({
  number,
  label,
  description,
  message,
}: {
  number: number
  label: string
  description: string
  message?: string
}) {
  return (
    <div className="flex items-start gap-3">
      <div className="size-6 rounded-full bg-primary text-primary-foreground flex items-center justify-center shrink-0 text-xs font-bold">
        {number}
      </div>
      <div className="flex flex-col gap-1 min-w-0">
        <div className="flex items-center gap-2">
          <Phone className="size-3 text-muted-foreground" />
          <span className="text-sm font-medium">{label}</span>
          <ArrowRight className="size-3 text-muted-foreground" />
          <span className="text-sm text-muted-foreground">{description}</span>
        </div>
        {message && (
          <p className="text-xs text-muted-foreground bg-muted/50 rounded-md px-2 py-1 italic">
            "{message.length > 80 ? message.slice(0, 80) + '…' : message}"
          </p>
        )}
      </div>
    </div>
  )
}

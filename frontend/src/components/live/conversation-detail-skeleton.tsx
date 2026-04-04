import { Skeleton } from '@/components/ui/skeleton'
import { MessageThreadSkeleton } from './message-thread-skeleton'

export function ConversationDetailSkeleton() {
  return (
    <div className="flex h-full flex-col overflow-hidden bg-white border-x border-border">
      {/* Header skeleton */}
      <div className="shrink-0 border-b border-border px-4 py-3 space-y-2.5">
        {/* Row 1: Customer info */}
        <div className="flex items-start justify-between gap-3">
          <div className="flex items-center gap-3">
            <Skeleton className="size-10 rounded-lg" />
            <div className="flex flex-col gap-1">
              <Skeleton className="h-4 w-32" />
              <Skeleton className="h-3 w-24" />
            </div>
          </div>
          <div className="flex items-center gap-2">
            <Skeleton className="h-5 w-16 rounded-full" />
            <Skeleton className="h-5 w-20 rounded-full" />
          </div>
        </div>
        {/* Row 2: Call flow */}
        <div className="flex items-center gap-1">
          {Array.from({ length: 7 }, (_, i) => (
            <Skeleton key={i} className="h-5 w-14 rounded-sm" />
          ))}
        </div>
        {/* Row 3: Handler info */}
        <Skeleton className="h-3 w-48" />
      </div>

      {/* Tab bar skeleton */}
      <div className="shrink-0 flex gap-1 border-b border-gray-100 px-4 pt-1">
        <Skeleton className="h-7 w-16" />
        <Skeleton className="h-7 w-16" />
        <Skeleton className="h-7 w-20" />
      </div>

      {/* Message thread skeleton */}
      <div className="min-h-0 flex-1 overflow-y-auto">
        <MessageThreadSkeleton count={5} />
      </div>
    </div>
  )
}

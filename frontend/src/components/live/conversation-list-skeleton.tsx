import { Skeleton } from '@/components/ui/skeleton'

export function ConversationListSkeleton({ count = 5 }: { count?: number }) {
  return (
    <div className="flex flex-col gap-0.5 p-1">
      {Array.from({ length: count }, (_, i) => (
        <div key={i} className="flex w-full items-start gap-2.5 rounded-sm border border-transparent p-2.5">
          {/* Channel icon */}
          <Skeleton className="mt-0.5 h-5 w-5 rounded" />

          <div className="flex flex-1 flex-col gap-1 overflow-hidden">
            {/* Name + duration row */}
            <div className="flex items-center justify-between gap-1">
              <Skeleton className="h-4 w-28" />
              <Skeleton className="h-3 w-12" />
            </div>
            {/* Phone number */}
            <Skeleton className="h-3 w-24" />
            {/* State badge + handler */}
            <div className="flex items-center gap-1.5">
              <Skeleton className="h-4 w-20 rounded-full" />
              <Skeleton className="h-3 w-10" />
            </div>
          </div>
        </div>
      ))}
    </div>
  )
}

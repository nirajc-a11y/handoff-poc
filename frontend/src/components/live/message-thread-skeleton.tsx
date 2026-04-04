import { Skeleton } from '@/components/ui/skeleton'

export function MessageThreadSkeleton({ count = 4 }: { count?: number }) {
  return (
    <div className="flex flex-col gap-3 px-4 py-3">
      {Array.from({ length: count }, (_, i) => {
        const isCustomer = i % 2 === 0
        const align = isCustomer ? 'items-start' : 'items-end'

        return (
          <div key={i} className={`flex flex-col gap-0.5 ${align}`}>
            {/* Sender + time */}
            <div className="flex items-center gap-1.5">
              <Skeleton className="h-2.5 w-12" />
              <Skeleton className="h-2.5 w-14" />
            </div>
            {/* Message bubble */}
            <Skeleton className={`h-14 rounded-lg ${isCustomer ? 'w-48' : 'w-56'}`} />
          </div>
        )
      })}
    </div>
  )
}

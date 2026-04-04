import { useAtomValue } from 'jotai'
import { wsConnectedAtom, wsExhaustedAtom } from '@/stores/ws'
import { wsManager } from '@/lib/ws'

export function OfflineIndicator() {
  const connected = useAtomValue(wsConnectedAtom)
  const exhausted = useAtomValue(wsExhaustedAtom)

  if (connected) return null

  return (
    <div className="bg-amber-500 text-white px-4 py-2 text-center text-sm font-medium flex items-center justify-center gap-2">
      {exhausted ? (
        <>
          <span>Connection lost.</span>
          <button
            onClick={() => wsManager.reconnect()}
            className="underline font-semibold hover:text-amber-100"
          >
            Click to retry
          </button>
        </>
      ) : (
        <span>Reconnecting to server...</span>
      )}
    </div>
  )
}

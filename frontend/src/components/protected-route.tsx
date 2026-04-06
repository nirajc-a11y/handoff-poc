import { useAtomValue } from 'jotai'
import { Navigate, Outlet } from 'react-router-dom'
import { tenantIdAtom, isConnectedAtom } from '@/stores/auth'

export function ProtectedRoute() {
  const tenantId = useAtomValue(tenantIdAtom)
  const isConnected = useAtomValue(isConnectedAtom)

  if (!tenantId || !isConnected) {
    return <Navigate to="/login" replace />
  }

  return <Outlet />
}

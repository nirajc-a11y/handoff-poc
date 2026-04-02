import { getDefaultStore } from 'jotai'
import { tenantIdAtom, userIdAtom } from '@/stores/auth'

const store = getDefaultStore()

async function apiFetch<T>(path: string, options: RequestInit = {}): Promise<T> {
  const tenantId = store.get(tenantIdAtom)
  const userId = store.get(userIdAtom)

  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(options.headers as Record<string, string> || {}),
  }
  if (tenantId) headers['X-Tenant-Id'] = tenantId
  if (userId) headers['X-User-Id'] = userId

  const res = await fetch(`/api/v1${path}`, { ...options, headers })

  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error((error as { detail?: string }).detail || `API error: ${res.status}`)
  }

  return res.json() as Promise<T>
}

export const api = {
  get: <T>(path: string) => apiFetch<T>(path),
  post: <T>(path: string, body?: unknown) => apiFetch<T>(path, { method: 'POST', body: body ? JSON.stringify(body) : undefined }),
  patch: <T>(path: string, body?: unknown) => apiFetch<T>(path, { method: 'PATCH', body: body ? JSON.stringify(body) : undefined }),
  delete: <T>(path: string) => apiFetch<T>(path, { method: 'DELETE' }),
}

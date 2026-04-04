import { getDefaultStore } from 'jotai'
import { tenantIdAtom, userIdAtom } from '@/stores/auth'
import { ApiError, AuthError, NotFoundError, ConflictError, ValidationError, RateLimitError, PayloadTooLargeError } from './errors'

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
    const body = await res.json().catch(() => ({ detail: res.statusText }))
    const detail = (body as { detail?: string }).detail || `API error: ${res.status}`

    switch (res.status) {
      case 401: throw new AuthError(detail)
      case 404: throw new NotFoundError(detail)
      case 409: throw new ConflictError(detail)
      case 413: throw new PayloadTooLargeError(detail)
      case 422: throw new ValidationError(detail)
      case 429: throw new RateLimitError(detail)
      default: throw new ApiError(res.status, detail)
    }
  }

  return res.json() as Promise<T>
}

export const api = {
  get: <T>(path: string) => apiFetch<T>(path),
  post: <T>(path: string, body?: unknown) => apiFetch<T>(path, { method: 'POST', body: body ? JSON.stringify(body) : undefined }),
  patch: <T>(path: string, body?: unknown) => apiFetch<T>(path, { method: 'PATCH', body: body ? JSON.stringify(body) : undefined }),
  delete: <T>(path: string) => apiFetch<T>(path, { method: 'DELETE' }),
}

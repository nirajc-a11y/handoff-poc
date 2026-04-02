import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useAtomValue } from 'jotai'
import { api } from '@/lib/api'
import { tenantIdAtom } from '@/stores/auth'
import type { IVRMenu } from '@/lib/types'

export function useIVRMenus() {
  const tenantId = useAtomValue(tenantIdAtom)
  return useQuery<IVRMenu[]>({ queryKey: ['ivr-menus', tenantId], queryFn: () => api.get('/ivr/menus'), enabled: !!tenantId })
}

export function useIVRMenu(id: string | null) {
  return useQuery<IVRMenu>({ queryKey: ['ivr-menus', 'detail', id], queryFn: () => api.get(`/ivr/menus/${id}`), enabled: !!id })
}

export function useCreateIVRMenu() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: { name: string; is_root?: boolean; welcome_message?: string }) => api.post('/ivr/menus', body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['ivr-menus'] }),
  })
}

export function useUpdateIVRMenu() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, ...body }: { id: string; name?: string; is_root?: boolean; welcome_message?: string }) =>
      api.patch(`/ivr/menus/${id}`, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['ivr-menus'] }),
  })
}

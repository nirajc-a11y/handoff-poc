import { useState } from 'react'
import { useLeads, useCreateLead, useUpdateLead, useDeleteLead } from '@/hooks/use-leads'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter,
} from '@/components/ui/dialog'
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table'
import { toast } from 'sonner'
import { Plus, Pencil, Trash2, Search, Contact } from 'lucide-react'
import type { Lead } from '@/lib/types'

export function LeadsPage() {
  const [search, setSearch] = useState('')
  const { data: leads = [], isLoading } = useLeads({ search: search || undefined })
  const [editLead, setEditLead] = useState<Lead | null>(null)
  const [showCreate, setShowCreate] = useState(false)
  const [deleteId, setDeleteId] = useState<string | null>(null)

  return (
    <div className="flex h-[calc(100vh-64px)] flex-col gap-4 overflow-y-auto bg-white p-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-gray-900">Leads</h1>
          <p className="text-sm text-gray-500 mt-0.5">Manage your lead database</p>
        </div>
        <Button size="sm" onClick={() => setShowCreate(true)}>
          <Plus size={14} />
          Add Lead
        </Button>
      </div>

      <div className="relative max-w-xs">
        <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 size-4 text-gray-400" />
        <Input
          placeholder="Search leads…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="pl-9"
        />
      </div>

      <div className="rounded-xl border border-gray-200 bg-white overflow-hidden">
        {isLoading ? (
          <p className="py-10 text-center text-sm text-gray-400">Loading…</p>
        ) : leads.length === 0 ? (
          <div className="flex flex-col items-center gap-2 py-12">
            <Contact className="size-8 text-gray-300" />
            <p className="text-sm text-gray-400">No leads found</p>
          </div>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Name</TableHead>
                <TableHead>Phone</TableHead>
                <TableHead>Email</TableHead>
                <TableHead>WhatsApp</TableHead>
                <TableHead className="w-24">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {leads.map((lead) => (
                <TableRow key={lead.id}>
                  <TableCell className="font-medium text-gray-900">{lead.name ?? '—'}</TableCell>
                  <TableCell className="text-gray-600 font-mono text-xs">{lead.phone ?? '—'}</TableCell>
                  <TableCell className="text-gray-600">{lead.email ?? '—'}</TableCell>
                  <TableCell className="text-gray-600 font-mono text-xs">{lead.whatsapp_number ?? '—'}</TableCell>
                  <TableCell>
                    <div className="flex items-center gap-1">
                      <Button variant="ghost" size="icon-sm" onClick={() => setEditLead(lead)}>
                        <Pencil className="size-3.5" />
                      </Button>
                      <Button variant="ghost" size="icon-sm" onClick={() => setDeleteId(lead.id)} className="text-red-500 hover:text-red-700">
                        <Trash2 className="size-3.5" />
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </div>

      <LeadFormDialog
        open={showCreate}
        onClose={() => setShowCreate(false)}
      />

      {editLead && (
        <LeadFormDialog
          open={!!editLead}
          lead={editLead}
          onClose={() => setEditLead(null)}
        />
      )}

      <DeleteLeadDialog
        leadId={deleteId}
        onClose={() => setDeleteId(null)}
      />
    </div>
  )
}

function LeadFormDialog({ open, lead, onClose }: { open: boolean; lead?: Lead; onClose: () => void }) {
  const createLead = useCreateLead()
  const updateLead = useUpdateLead()
  const isEdit = !!lead

  const [name, setName] = useState(lead?.name ?? '')
  const [phone, setPhone] = useState(lead?.phone ?? '')
  const [email, setEmail] = useState(lead?.email ?? '')
  const [whatsapp, setWhatsapp] = useState(lead?.whatsapp_number ?? '')

  const handleSubmit = async () => {
    try {
      const body = {
        name: name || null,
        phone: phone || null,
        email: email || null,
        whatsapp_number: whatsapp || null,
      }
      if (isEdit) {
        await updateLead.mutateAsync({ id: lead.id, ...body })
        toast.success('Lead updated')
      } else {
        await createLead.mutateAsync(body)
        toast.success('Lead created')
      }
      onClose()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to save lead')
    }
  }

  const isPending = createLead.isPending || updateLead.isPending

  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) onClose() }}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{isEdit ? 'Edit Lead' : 'Add Lead'}</DialogTitle>
        </DialogHeader>
        <div className="flex flex-col gap-3">
          <div className="flex flex-col gap-1.5">
            <Label>Name</Label>
            <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="John Doe" />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label>Phone</Label>
            <Input value={phone} onChange={(e) => setPhone(e.target.value)} placeholder="+91..." />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label>Email</Label>
            <Input value={email} onChange={(e) => setEmail(e.target.value)} placeholder="john@example.com" />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label>WhatsApp</Label>
            <Input value={whatsapp} onChange={(e) => setWhatsapp(e.target.value)} placeholder="+91..." />
          </div>
        </div>
        <DialogFooter>
          <Button onClick={handleSubmit} disabled={isPending}>
            {isPending ? 'Saving…' : isEdit ? 'Save Changes' : 'Create Lead'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function DeleteLeadDialog({ leadId, onClose }: { leadId: string | null; onClose: () => void }) {
  const deleteLead = useDeleteLead()

  const handleDelete = async () => {
    if (!leadId) return
    try {
      await deleteLead.mutateAsync(leadId)
      toast.success('Lead deleted')
      onClose()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to delete lead')
    }
  }

  return (
    <Dialog open={!!leadId} onOpenChange={(o) => { if (!o) onClose() }}>
      <DialogContent className="sm:max-w-sm">
        <DialogHeader>
          <DialogTitle>Delete Lead</DialogTitle>
        </DialogHeader>
        <p className="text-sm text-gray-600">Are you sure you want to delete this lead? This action cannot be undone.</p>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Cancel</Button>
          <Button variant="destructive" onClick={handleDelete} disabled={deleteLead.isPending}>
            {deleteLead.isPending ? 'Deleting…' : 'Delete'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

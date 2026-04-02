import { useRef, useState } from 'react'
import { toast } from 'sonner'
import { api } from '@/lib/api'
import { Button } from '@/components/ui/button'
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter,
} from '@/components/ui/dialog'
import { Upload } from 'lucide-react'
import type { Campaign } from '@/lib/types'

interface Props {
  campaign: Campaign
  open: boolean
  onClose: () => void
}

type CsvRow = Record<string, string>

function parseCsv(text: string): CsvRow[] {
  const lines = text.trim().split('\n')
  if (lines.length < 2) return []
  const headers = lines[0].split(',').map(h => h.trim().replace(/^"|"$/g, ''))
  return lines.slice(1).map(line => {
    const values = line.split(',').map(v => v.trim().replace(/^"|"$/g, ''))
    const row: CsvRow = {}
    headers.forEach((h, i) => { row[h] = values[i] ?? '' })
    return row
  })
}

export function LeadUpload({ campaign, open, onClose }: Props) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [preview, setPreview] = useState<CsvRow[]>([])
  const [allRows, setAllRows] = useState<CsvRow[]>([])
  const [loading, setLoading] = useState(false)

  function handleFile(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file) return
    const reader = new FileReader()
    reader.onload = (ev) => {
      const text = ev.target?.result as string
      const rows = parseCsv(text)
      setAllRows(rows)
      setPreview(rows.slice(0, 5))
    }
    reader.readAsText(file)
  }

  async function handleImport() {
    if (allRows.length === 0) {
      toast.error('No data to import')
      return
    }
    setLoading(true)
    try {
      // Map CSV rows to lead objects
      const leads = allRows.map(row => ({
        name: row['name'] ?? row['Name'] ?? null,
        phone: row['phone'] ?? row['Phone'] ?? row['phone_number'] ?? null,
        email: row['email'] ?? row['Email'] ?? null,
        whatsapp_number: row['whatsapp'] ?? row['whatsapp_number'] ?? null,
        metadata: row,
      }))

      // Import leads
      const imported = await api.post<{ ids: string[] }>('/leads/import', { leads })
      const leadIds = imported.ids ?? []

      if (leadIds.length > 0) {
        // Add to campaign
        await api.post(`/campaigns/${campaign.id}/leads`, { lead_ids: leadIds })
        toast.success(`Imported ${leadIds.length} leads into ${campaign.name}`)
      } else {
        toast.warning('No leads were imported')
      }

      onClose()
    } catch (err) {
      toast.error((err as Error).message)
    } finally {
      setLoading(false)
    }
  }

  const headers = preview.length > 0 ? Object.keys(preview[0]) : []

  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) onClose() }}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Upload Leads — {campaign.name}</DialogTitle>
        </DialogHeader>

        <div className="flex flex-col gap-4">
          <div
            className="flex flex-col items-center gap-2 rounded-lg border-2 border-dashed border-gray-200 p-8 cursor-pointer hover:border-gray-300 transition-colors"
            onClick={() => inputRef.current?.click()}
          >
            <Upload size={24} className="text-gray-400" />
            <p className="text-sm text-gray-500">Click to select a CSV file</p>
            <p className="text-xs text-gray-400">Columns: name, phone, email, whatsapp</p>
            <input ref={inputRef} type="file" accept=".csv" className="hidden" onChange={handleFile} />
          </div>

          {preview.length > 0 && (
            <div>
              <p className="text-xs font-medium text-gray-600 mb-1">
                Preview (first {preview.length} rows of {allRows.length})
              </p>
              <div className="overflow-x-auto rounded-lg border border-gray-100">
                <table className="w-full text-xs">
                  <thead className="bg-gray-50">
                    <tr>
                      {headers.map(h => (
                        <th key={h} className="px-2 py-1.5 text-left font-medium text-gray-600">{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {preview.map((row, i) => (
                      <tr key={i} className="border-t border-gray-100">
                        {headers.map(h => (
                          <td key={h} className="px-2 py-1.5 text-gray-500 max-w-24 truncate">{row[h]}</td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>

        <DialogFooter>
          <Button
            onClick={handleImport}
            disabled={loading || allRows.length === 0}
          >
            {loading ? 'Importing…' : `Import ${allRows.length > 0 ? `${allRows.length} Leads` : ''}`}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

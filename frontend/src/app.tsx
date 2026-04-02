import { AppShell } from '@/components/layout/app-shell'
import { Toaster } from 'sonner'

export default function App() {
  return (
    <>
      <AppShell />
      <Toaster position="bottom-right" richColors />
    </>
  )
}

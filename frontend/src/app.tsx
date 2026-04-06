import { Navigate, Route, Routes } from 'react-router-dom'
import { Toaster } from 'sonner'
import { AppShell } from '@/components/layout/app-shell'
import { ProtectedRoute } from '@/components/protected-route'
import { LoginPage } from '@/pages/login'
import { LivePage } from '@/pages/live'
import { AnalyticsPage } from '@/pages/analytics'
import { CampaignsPage } from '@/pages/campaigns'
import { AgentsPage } from '@/pages/agents'
import { LeadsPage } from '@/pages/leads'
import { HistoryPage } from '@/pages/history'
import { IVRPage } from '@/pages/ivr'
import { SettingsPage } from '@/pages/settings'

export default function App() {
  return (
    <>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route element={<ProtectedRoute />}>
          <Route element={<AppShell />}>
            <Route index element={<Navigate to="/live" replace />} />
            <Route path="/live" element={<LivePage />} />
            <Route path="/analytics" element={<AnalyticsPage />} />
            <Route path="/campaigns" element={<CampaignsPage />} />
            <Route path="/leads" element={<LeadsPage />} />
            <Route path="/agents" element={<AgentsPage />} />
            <Route path="/history" element={<HistoryPage />} />
            <Route path="/ivr" element={<IVRPage />} />
            <Route path="/settings" element={<SettingsPage />} />
          </Route>
        </Route>
        {/* Catch-all: redirect unknown paths to /live (or /login if not authed — ProtectedRoute handles it) */}
        <Route path="*" element={<Navigate to="/live" replace />} />
      </Routes>
      <Toaster position="bottom-right" richColors />
    </>
  )
}

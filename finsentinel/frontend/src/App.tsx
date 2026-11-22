import { useEffect, useState } from 'react'
import { clearUnauthenticatedHandler, setUnauthenticatedHandler } from './api/client'
import { useAuth } from './hooks/useAuth'
import Login from './pages/Login'
import Layout from './components/Layout'
import Dashboard from './pages/Dashboard'
import Approvals from './pages/Approvals'
import TrustedKeys from './pages/TrustedKeys'
import ModelSchemas from './pages/ModelSchemas'
import AuditOutbox from './pages/AuditOutbox'
import Aggregation from './pages/Aggregation'
import DetectionConfig from './pages/DetectionConfig'
import HealthMonitor from './pages/HealthMonitor'
import SecurityEvents from './pages/SecurityEvents'

export type PageId =
  | 'dashboard'
  | 'approvals'
  | 'trusted-keys'
  | 'model-schemas'
  | 'audit-outbox'
  | 'aggregation'
  | 'detection'
  | 'health'
  | 'security-events'

export default function App() {
  const auth = useAuth()
  const [page, setPage] = useState<PageId>('dashboard')

  // Register auto-logout on 401 so that if the operator token is rotated
  // while this session is open, the next API call returns the user to login.
  useEffect(() => {
    if (auth.token) {
      setUnauthenticatedHandler(auth.logout)
    } else {
      clearUnauthenticatedHandler()
    }
    return clearUnauthenticatedHandler
  }, [auth.token, auth.logout])

  if (!auth.token) {
    return <Login onLogin={auth.login} />
  }

  const renderPage = () => {
    switch (page) {
      case 'dashboard':
        return <Dashboard token={auth.token!} onNavigate={(p) => setPage(p as PageId)} />
      case 'approvals':
        return <Approvals token={auth.token!} />
      case 'trusted-keys':
        return <TrustedKeys token={auth.token!} />
      case 'model-schemas':
        return <ModelSchemas token={auth.token!} />
      case 'audit-outbox':
        return <AuditOutbox token={auth.token!} />
      case 'aggregation':
        return <Aggregation token={auth.token!} />
      case 'detection':
        return <DetectionConfig token={auth.token!} />
      case 'health':
        return <HealthMonitor token={auth.token!} />
      case 'security-events':
        return <SecurityEvents token={auth.token!} />
    }
  }

  return (
    <Layout currentPage={page} onNavigate={setPage} onLogout={auth.logout}>
      {renderPage()}
    </Layout>
  )
}

import type { ReactNode } from 'react'
import type { PageId } from '../App'

interface NavEntry {
  id: PageId
  label: string
  icon: string
  section?: string
}

const NAV: NavEntry[] = [
  { id: 'dashboard',     label: 'Dashboard',       icon: '⊞', section: 'Overview'    },
  { id: 'approvals',     label: 'Approvals',        icon: '◎', section: 'Operations'  },
  { id: 'trusted-keys',  label: 'Trusted Keys',     icon: '⌘', section: 'Registry'    },
  { id: 'model-schemas', label: 'Model Schemas',    icon: '▣'                          },
  { id: 'audit-outbox',     label: 'Audit Outbox',      icon: '◉', section: 'System'   },
  { id: 'security-events', label: 'Security Center',   icon: '⚑'                       },
  { id: 'aggregation',     label: 'Aggregation',       icon: '⊕'                       },
  { id: 'detection',       label: 'Detection',         icon: '◈'                       },
  { id: 'health',          label: 'Health Monitor',    icon: '◑'                       },
]

const PAGE_TITLES: Record<PageId, string> = {
  'dashboard':        'Operator Dashboard',
  'approvals':        'Approval Queue',
  'trusted-keys':     'Trusted Key Registry',
  'model-schemas':    'Model Schema Registry',
  'audit-outbox':     'Audit Outbox',
  'security-events':  'Security Center',
  'aggregation':      'Aggregation Control',
  'detection':        'Detection Configuration',
  'health':           'Health Monitor',
}

interface Props {
  currentPage: PageId
  onNavigate: (page: PageId) => void
  onLogout: () => void
  children: ReactNode
}

export default function Layout({ currentPage, onNavigate, onLogout, children }: Props) {
  return (
    <div className="layout">
      <aside className="sidebar">
        <div className="sidebar-header">
          <div className="sidebar-logo">
            <div className="sidebar-logo-mark">FS</div>
            <div className="sidebar-title">Fin<span>Sentinel</span></div>
          </div>
          <div className="sidebar-subtitle">FL Security & Trust Intelligence</div>
        </div>

        <nav className="sidebar-nav">
          {NAV.map((entry) => (
            <div key={entry.id}>
              {entry.section && (
                <div className="nav-section-label">{entry.section}</div>
              )}
              <a
                className={`nav-item${currentPage === entry.id ? ' active' : ''}`}
                onClick={(e) => { e.preventDefault(); onNavigate(entry.id) }}
                href="#"
              >
                <span className="nav-icon">{entry.icon}</span>
                {entry.label}
              </a>
            </div>
          ))}
        </nav>

        <div className="sidebar-footer">
          <div className="sidebar-status">
            <span className="dot dot-cyan dot-pulse" />
            <span className="sidebar-status-text">Operator session active</span>
          </div>
          <button
            className="btn btn-danger"
            style={{ width: '100%', fontSize: 12, justifyContent: 'center' }}
            onClick={onLogout}
          >
            End Session
          </button>
        </div>
      </aside>

      <div className="main-content">
        <header className="topbar">
          <div className="topbar-breadcrumb">
            <span style={{ color: 'var(--text-muted)', fontSize: 12 }}>FinSentinel</span>
            <span className="topbar-breadcrumb-sep">/</span>
            <span className="topbar-title">{PAGE_TITLES[currentPage]}</span>
          </div>
          <div className="topbar-actions">
            <div className="topbar-status">
              <span className="dot dot-green" />
              <span>Authenticated</span>
            </div>
            <div className="topbar-divider" />
            <span className="mono" style={{ fontSize: 10, color: 'var(--text-muted)' }}>v0.1</span>
          </div>
        </header>
        <main className="page-body">{children}</main>
      </div>
    </div>
  )
}

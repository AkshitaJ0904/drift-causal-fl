import { api, type DashboardResponse } from '../api/client'
import { useApi } from '../hooks/useApi'
import Explain from '../components/Explain'

interface Props {
  token: string
}

export default function AuditOutbox({ token }: Props) {
  const { data, loading, error, refresh } = useApi<DashboardResponse>(
    () => api.getDashboard(token),
    [token],
  )

  const outbox = data?.outbox
  const worker = data?.worker

  const hasDeadLetters = !!(outbox?.dead_letter_count && outbox.dead_letter_count > 0)

  return (
    <div>
      <div className="section-header">
        <div>
          <div className="section-title">Audit Outbox</div>
          <div className="section-desc">
            Every security decision is written here before being forwarded to the SIEM. Dead-lettered events are ones the forwarder could not deliver after 10 attempts — they need manual investigation.
          </div>
        </div>
        <button className="btn" onClick={refresh}>↻ Refresh</button>
      </div>

      {error && <div className="alert alert-error mb-16">{error}</div>}

      {!loading && outbox?.alert && (
        <div className="alert alert-warn mb-16">
          <strong>Dead-letter alert:</strong>&nbsp;
          {outbox.dead_letter_count} event(s) exceeded maximum delivery attempts.
          Manual investigation required — these records will not be retried automatically.
        </div>
      )}

      <div className="stat-grid">
        <div className="stat-card">
          <div className="stat-label" style={{ display: 'flex', alignItems: 'center', gap: 4 }}>Pending Events <Explain term="outbox" /></div>
          <div
            className="stat-value"
            style={outbox?.pending_count ? { color: 'var(--accent-amber)' } : undefined}
          >
            {loading
              ? <span className="spinner" style={{ width: 16, height: 16 }} />
              : (outbox?.pending_count ?? '?')}
          </div>
        </div>
        <div className="stat-card">
          <div className="stat-label" style={{ display: 'flex', alignItems: 'center', gap: 4 }}>Dead-lettered <Explain term="dead_letter" /></div>
          <div
            className="stat-value"
            style={hasDeadLetters ? { color: 'var(--accent-red)' } : undefined}
          >
            {loading
              ? <span className="spinner" style={{ width: 16, height: 16 }} />
              : (outbox?.dead_letter_count ?? '?')}
          </div>
        </div>
      </div>

      {/* Worker status */}
      <div className="card">
        <div className="card-header">
          <span className="card-title">Delivery Worker</span>
          {!loading && (
            <span className={worker?.enabled ? 'badge badge-green' : 'badge badge-muted'}>
              {worker?.enabled ? 'running' : 'disabled'}
            </span>
          )}
        </div>
        {loading ? (
          <div className="loading-row"><span className="spinner" /> Loading…</div>
        ) : (
          <>
            <div className="status-row">
              <span className={`dot ${worker?.enabled ? 'dot-green' : 'dot-red'}`} />
              <span className="status-row-label">Background delivery worker</span>
              <span className="status-row-value mono">{worker?.enabled ? 'enabled' : 'disabled'}</span>
            </div>
            <div className="status-row">
              <span className={`dot ${worker?.webhook_configured ? 'dot-green' : 'dot-yellow'}`} />
              <span className="status-row-label">Webhook URL</span>
              <span className="status-row-value mono">{worker?.webhook_configured ? 'configured' : 'not configured'}</span>
            </div>
          </>
        )}
      </div>

      {/* Dead-letter recovery */}
      <div className={`card ${hasDeadLetters ? 'card-warn' : ''}`}>
        <div className="card-header">
          <span className="card-title">Dead-letter Recovery</span>
          {hasDeadLetters && (
            <span className="badge badge-red">{outbox?.dead_letter_count} require investigation</span>
          )}
        </div>
        <p className="text-muted" style={{ marginBottom: 12 }}>
          Dead-lettered records require manual investigation and cannot be re-queued automatically.
          Use the CLI to inspect and replay records:
        </p>
        <div className="code-block">
          <pre className="mono" style={{ margin: 0, fontSize: 12, lineHeight: 1.7 }}>{`# List dead-lettered events
python -m scripts.list_dead_letter_events

# Re-queue a specific event (after investigation)
python -m scripts.requeue_dead_letter --record-id <id>`}</pre>
        </div>
        <div className="alert alert-warn" style={{ marginTop: 12, marginBottom: 0 }}>
          Only re-queue events after confirming the delivery failure was transient
          (network issue, webhook downtime) rather than data corruption.
        </div>
      </div>
    </div>
  )
}

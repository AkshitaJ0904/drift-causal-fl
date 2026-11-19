import { useEffect, useState } from 'react'
import { api, type DashboardResponse } from '../api/client'
import { useApi } from '../hooks/useApi'

interface Props {
  token: string
}

function StatCard({
  label,
  value,
  accent,
  accentColor,
}: {
  label: string
  value: string | number
  accent?: boolean
  accentColor?: string
}) {
  return (
    <div className="stat-card">
      <div className="stat-label">{label}</div>
      <div
        className="stat-value"
        style={accentColor ? { color: accentColor } : accent ? { color: 'var(--accent-cyan)' } : undefined}
      >
        {value}
      </div>
    </div>
  )
}

function StatusRow({
  label,
  value,
  ok,
}: {
  label: string
  value: string | number | null
  ok: boolean | null
}) {
  const dotClass =
    ok === null ? 'dot-muted' : ok ? 'dot-green' : 'dot-red'

  return (
    <div className="status-row">
      <span className={`dot ${dotClass}`} />
      <span className="status-row-label">{label}</span>
      <span className="status-row-value">{value ?? '—'}</span>
    </div>
  )
}

export default function Dashboard({ token }: Props) {
  const { data, loading, error, refresh } = useApi<DashboardResponse>(
    () => api.getDashboard(token),
    [token],
    { pollingIntervalMs: 30_000 },
  )
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null)

  useEffect(() => {
    if (data) setLastUpdated(new Date())
  }, [data])

  if (loading) {
    return (
      <div className="loading-row">
        <span className="spinner" />
        Loading dashboard…
      </div>
    )
  }

  if (error) {
    return (
      <div className="alert alert-error">
        {error}
        <button className="btn" style={{ marginLeft: 'auto' }} onClick={refresh}>
          Retry
        </button>
      </div>
    )
  }

  if (!data) return null

  const { outbox, registries, approvals, worker, config } = data

  const hasDeadLetters = !!(outbox.dead_letter_count && outbox.dead_letter_count > 0)
  const hasPendingApprovals = !!(approvals.pending_count && approvals.pending_count > 0)

  return (
    <div>
      {/* Critical alerts */}
      {outbox.alert && (
        <div className="alert alert-warn">
          <strong>Dead-letter alert:</strong>&nbsp;
          {outbox.dead_letter_count} audit event(s) exceeded max delivery attempts.
          Manual investigation required. Use the Audit Outbox module for details.
        </div>
      )}

      {/* KPI row */}
      <div className="stat-grid">
        <StatCard
          label="Pending Approvals"
          value={approvals.pending_count ?? '?'}
          accent={hasPendingApprovals}
        />
        <StatCard
          label="Outbox Pending"
          value={outbox.pending_count ?? '?'}
          accentColor={outbox.pending_count && outbox.pending_count > 0 ? 'var(--accent-amber)' : undefined}
        />
        <StatCard
          label="Dead-lettered"
          value={outbox.dead_letter_count ?? '?'}
          accentColor={hasDeadLetters ? 'var(--accent-red)' : undefined}
        />
        <StatCard label="Trusted Keys"   value={registries.trusted_key_count ?? '?'} />
        <StatCard label="Model Schemas"  value={registries.model_schema_count ?? '?'} />
      </div>

      {/* Detail section */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
        {/* Security state */}
        <div className="card card-accent">
          <div className="card-header">
            <span className="card-title">Security State</span>
            <span className={hasPendingApprovals ? 'badge badge-yellow' : 'badge badge-green'}>
              {hasPendingApprovals
                ? `${approvals.pending_count} pending`
                : 'queue clear'}
            </span>
          </div>
          <StatusRow
            label="Approval queue depth"
            value={approvals.pending_count ?? 'unavailable'}
            ok={approvals.pending_count === 0 ? true : approvals.pending_count === null ? null : false}
          />
          <StatusRow
            label="Audit outbox pending"
            value={outbox.pending_count ?? 'unavailable'}
            ok={outbox.pending_count === 0 ? true : outbox.pending_count === null ? null : null}
          />
          <StatusRow
            label="Dead-lettered events"
            value={outbox.dead_letter_count ?? 'unavailable'}
            ok={outbox.dead_letter_count === 0 ? true : outbox.dead_letter_count === null ? null : false}
          />
          {approvals.error && (
            <div className="text-muted mt-8" style={{ fontSize: 11 }}>
              Approvals unavailable: {approvals.error}
            </div>
          )}
          {outbox.error && (
            <div className="text-muted mt-8" style={{ fontSize: 11 }}>
              Outbox unavailable: {outbox.error}
            </div>
          )}
        </div>

        {/* Configuration */}
        <div className="card">
          <div className="card-header">
            <span className="card-title">Configuration</span>
            <span className={config.operator_token_configured ? 'badge badge-green' : 'badge badge-red'}>
              token {config.operator_token_configured ? 'set' : 'not set'}
            </span>
          </div>
          <StatusRow
            label="Operator token configured"
            value={config.operator_token_configured ? 'yes' : 'no'}
            ok={config.operator_token_configured}
          />
          <StatusRow
            label="Concurrency cap"
            value={config.concurrency_cap ?? 'unlimited (not set)'}
            ok={config.concurrency_cap !== null}
          />
          <StatusRow
            label="Rate limit (rpm)"
            value={config.rate_limit_rpm ?? 'not configured'}
            ok={config.rate_limit_rpm !== null}
          />
          <StatusRow
            label="Body-read timeout (s)"
            value={config.body_read_timeout_seconds ?? 'not configured'}
            ok={config.body_read_timeout_seconds !== null}
          />
        </div>
      </div>

      {/* Worker & delivery */}
      <div className="card">
        <div className="card-header">
          <span className="card-title">Delivery Worker</span>
          <span className={worker.enabled ? 'badge badge-green' : 'badge badge-muted'}>
            {worker.enabled ? 'running' : 'disabled'}
          </span>
        </div>
        <StatusRow
          label="Background delivery worker"
          value={worker.enabled ? 'enabled' : 'disabled'}
          ok={worker.enabled}
        />
        <StatusRow
          label="Webhook URL"
          value={worker.webhook_configured ? 'configured' : 'not configured'}
          ok={worker.webhook_configured}
        />
      </div>

      {/* Registry summary */}
      {registries.error && (
        <div className="text-muted" style={{ fontSize: 11, marginTop: -8 }}>
          Registry counts unavailable: {registries.error}
        </div>
      )}

      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'flex-end', marginTop: 4, gap: 12 }}>
        {lastUpdated && (
          <span className="text-muted" style={{ fontSize: 11 }}>
            Last updated {lastUpdated.toLocaleTimeString()} · auto-refreshes every 30 s
          </span>
        )}
        <button className="btn" onClick={refresh}>↻ Refresh</button>
      </div>
    </div>
  )
}

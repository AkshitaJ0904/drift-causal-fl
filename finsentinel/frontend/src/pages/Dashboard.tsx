import { useEffect, useState } from 'react'
import { api, type DashboardResponse } from '../api/client'
import { useApi } from '../hooks/useApi'
import Explain from '../components/Explain'
import type { GlossaryKey } from '../glossary'

function SecurityPostureStrip({ token }: { token: string }) {
  const { data } = useApi(() => api.getVaptReport(token), [token])
  if (!data?.available || !data.summary) return null
  const s = data.summary
  const passRate = Math.round((s.pass / s.total) * 100)
  const statusColor = passRate >= 90 ? 'var(--accent-cyan)' : passRate >= 70 ? 'var(--accent-amber)' : 'var(--accent-red)'
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 20,
        padding: '10px 16px',
        background: 'var(--surface)',
        borderRadius: 6,
        marginBottom: 16,
        fontSize: 12,
        flexWrap: 'wrap',
      }}
    >
      <span style={{ fontWeight: 600, color: 'var(--text-muted)' }}>Security Posture</span>
      <span style={{ color: statusColor, fontWeight: 700 }}>{passRate}% pass rate</span>
      <span style={{ color: 'var(--text-muted)' }}>{s.total} tests · {s.pass} pass · {s.fail} fail</span>
      {data.findings && data.findings.length > 0 && (
        <span style={{ color: 'var(--accent-red)' }}>{data.findings.length} open finding{data.findings.length !== 1 ? 's' : ''}</span>
      )}
      <span style={{ color: 'var(--text-muted)', fontSize: 11 }}>Run {data.run ?? '—'}</span>
    </div>
  )
}

interface Props {
  token: string
}

function StatCard({
  label,
  value,
  accent,
  accentColor,
  explain,
}: {
  label: string
  value: string | number
  accent?: boolean
  accentColor?: string
  explain?: GlossaryKey
}) {
  return (
    <div className="stat-card">
      <div className="stat-label" style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
        {label}
        {explain && <Explain term={explain} />}
      </div>
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

const WAZUH_URL = (import.meta.env.VITE_WAZUH_URL as string | undefined) ?? 'https://localhost'

interface WorkflowStepProps {
  step: number
  label: string
  note: string
  badge?: string | number | null
  page?: string
  onNav?: (page: string) => void
}

function WorkflowStep({ step, label, note, badge, page, onNav }: WorkflowStepProps) {
  const content = (
    <div
      onClick={page && onNav ? () => onNav(page) : undefined}
      style={{
        textAlign: 'center',
        padding: '10px 12px',
        background: 'var(--bg-card)',
        border: '1px solid var(--border)',
        borderRadius: 'var(--radius)',
        cursor: page && onNav ? 'pointer' : 'default',
        minWidth: 110,
        transition: 'border-color 0.15s',
      }}
      onMouseEnter={e => { if (page && onNav) (e.currentTarget as HTMLDivElement).style.borderColor = 'var(--accent-cyan)' }}
      onMouseLeave={e => { (e.currentTarget as HTMLDivElement).style.borderColor = 'var(--border)' }}
    >
      <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text-muted)', letterSpacing: '0.08em', marginBottom: 2 }}>STEP {step}</div>
      <div style={{ fontWeight: 600, fontSize: 12.5, color: 'var(--text-primary)', marginBottom: 2 }}>{label}</div>
      {badge != null && (
        <div style={{ fontSize: 18, fontWeight: 700, color: 'var(--accent-cyan)', lineHeight: 1 }}>{badge}</div>
      )}
      <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 2 }}>{note}</div>
    </div>
  )
  return content
}

function WorkflowStrip({ data, onNav }: { data: DashboardResponse; onNav?: (page: string) => void }) {
  const steps: WorkflowStepProps[] = [
    { step: 1, label: 'Client submits', note: 'Signed NPZ update', page: 'trusted-keys', badge: data.registries.trusted_key_count },
    { step: 2, label: 'Gateway checks', note: 'Sig · schema · score', page: 'detection' },
    { step: 3, label: 'Approval queue', note: 'Operator decision', page: 'approvals', badge: data.approvals.pending_count },
    { step: 4, label: 'Aggregation', note: 'FedAvg weighting', page: 'aggregation' },
    { step: 5, label: 'Audit outbox', note: 'Durable event log', page: 'outbox', badge: data.outbox.pending_count },
    { step: 6, label: 'SIEM / Wazuh', note: 'Threat correlation' },
  ]

  return (
    <div style={{ marginBottom: 20 }}>
      <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: '0.07em', color: 'var(--text-muted)', textTransform: 'uppercase', marginBottom: 10 }}>
        How FinSentinel works
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 0, flexWrap: 'wrap' }}>
        {steps.map((s, idx) => (
          <>
            <WorkflowStep key={s.step} {...s} onNav={onNav} />
            {idx < steps.length - 1 && (
              <div key={`arr-${idx}`} style={{ color: 'var(--text-muted)', fontSize: 16, padding: '0 4px', flexShrink: 0 }}>→</div>
            )}
          </>
        ))}
        <a
          href={WAZUH_URL}
          target="_blank"
          rel="noopener noreferrer"
          className="btn"
          style={{ marginLeft: 12, fontSize: 12 }}
        >
          Open Wazuh ↗
        </a>
      </div>
    </div>
  )
}

interface Props { token: string; onNavigate?: (page: string) => void }

export default function Dashboard({ token, onNavigate }: Props) {
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
      {data && <WorkflowStrip data={data} onNav={onNavigate} />}

      <SecurityPostureStrip token={token} />

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
          explain="outbox"
        />
        <StatCard
          label="Dead-lettered"
          value={outbox.dead_letter_count ?? '?'}
          accentColor={hasDeadLetters ? 'var(--accent-red)' : undefined}
          explain="dead_letter"
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
        <a
          href={(import.meta.env.VITE_WAZUH_URL as string | undefined) ?? 'https://localhost'}
          target="_blank"
          rel="noopener noreferrer"
          className="btn"
          style={{ fontSize: 12 }}
        >
          Open Wazuh ↗
        </a>
        <button className="btn" onClick={refresh}>↻ Refresh</button>
      </div>
    </div>
  )
}

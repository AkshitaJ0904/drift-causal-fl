import { useEffect, useState } from 'react'
import { api, type HealthResponse, type HealthAlertsResponse, type HealthMetricsResponse } from '../api/client'
import { useApi } from '../hooks/useApi'
import Explain from '../components/Explain'

interface Props {
  token: string
}

function statusBadge(status: string | undefined) {
  if (!status)                           return <span className="badge badge-muted">unknown</span>
  if (status === 'ok' || status === 'healthy') return <span className="badge badge-green">{status}</span>
  if (status === 'degraded')             return <span className="badge badge-yellow">{status}</span>
  return <span className="badge badge-red">{status}</span>
}

export default function HealthMonitor({ token }: Props) {
  const POLL = { pollingIntervalMs: 30_000 }
  const liveness   = useApi<HealthResponse>(() => api.getHealth(token), [token], POLL)
  const alertsApi  = useApi<HealthAlertsResponse>(() => api.getHealthAlerts(), [], POLL)
  const metricsApi = useApi<HealthMetricsResponse>(() => api.getHealthMetrics(token), [token], POLL)
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null)

  const overall = liveness.data?.status
  const degraded = alertsApi.data?.status === 'degraded'

  const refresh = () => {
    liveness.refresh()
    alertsApi.refresh()
    metricsApi.refresh()
    setLastUpdated(new Date())
  }

  useEffect(() => {
    if (liveness.data || alertsApi.data || metricsApi.data) setLastUpdated(new Date())
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [liveness.data, alertsApi.data, metricsApi.data])

  return (
    <div>
      <div className="section-header">
        <div>
          <div className="section-title">Health Monitor</div>
          <div className="section-desc">
            Live health of the FinSentinel backend. A "degraded" status usually means undelivered audit events in the outbox — check the Audit Outbox page for dead-lettered events.
          </div>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          {lastUpdated && (
            <span className="text-muted" style={{ fontSize: 11 }}>
              Last updated {lastUpdated.toLocaleTimeString()} · auto-refreshes every 30 s
            </span>
          )}
          <button className="btn" onClick={refresh}>↻ Refresh</button>
        </div>
      </div>

      {liveness.error && (
        <div className="alert alert-error mb-16">
          Liveness: {liveness.error.includes('401') || liveness.error.includes('503')
            ? `${liveness.error} — confirm the backend is running.`
            : liveness.error}
        </div>
      )}

      {/* Stat row */}
      <div className="stat-grid">
        <div className="stat-card">
          <div className="stat-label">Service Status</div>
          <div className="stat-value" style={{ fontSize: 16, marginTop: 6 }}>
            {liveness.loading
              ? <span className="spinner" style={{ width: 16, height: 16 }} />
              : statusBadge(overall)}
          </div>
        </div>

        <div className="stat-card">
          <div className="stat-label">Alert State</div>
          <div className="stat-value" style={{ fontSize: 16, marginTop: 6 }}>
            {alertsApi.loading
              ? <span className="spinner" style={{ width: 16, height: 16 }} />
              : alertsApi.error
                ? <span className="badge badge-muted">unavailable</span>
                : statusBadge(alertsApi.data?.status)}
          </div>
        </div>

        {liveness.data?.service && (
          <div className="stat-card">
            <div className="stat-label">Service Name</div>
            <div className="stat-value mono" style={{ fontSize: 13, marginTop: 6 }}>
              {liveness.data.service}
            </div>
          </div>
        )}

        {!metricsApi.loading && metricsApi.data && (
          <>
            <div className="stat-card">
              <div className="stat-label" style={{ display: 'flex', alignItems: 'center', gap: 4 }}>Outbox Pending <Explain term="outbox" /></div>
              <div
                className="stat-value"
                style={metricsApi.data.outbox.pending_count ? { color: 'var(--accent-amber)' } : undefined}
              >
                {metricsApi.data.outbox.pending_count ?? '?'}
              </div>
            </div>
            <div className="stat-card">
              <div className="stat-label" style={{ display: 'flex', alignItems: 'center', gap: 4 }}>Dead-lettered <Explain term="dead_letter" /></div>
              <div
                className="stat-value"
                style={metricsApi.data.outbox.dead_letter_count ? { color: 'var(--accent-red)' } : undefined}
              >
                {metricsApi.data.outbox.dead_letter_count ?? '?'}
              </div>
            </div>
          </>
        )}
      </div>

      {/* All-clear */}
      {!liveness.loading && !alertsApi.loading && !degraded && overall === 'ok' && (
        <div className="alert alert-success mb-16">
          All monitored components are healthy.
        </div>
      )}

      {/* Active alerts */}
      {!alertsApi.loading && degraded && alertsApi.data && alertsApi.data.alerts.length > 0 && (
        <div className="card mb-16">
          <div className="card-header">
            <span className="card-title">Active Alerts</span>
            <span className="badge badge-yellow">{alertsApi.data.alerts.length} alert(s)</span>
          </div>
          {alertsApi.data.alerts.map((alert, i) => (
            <div
              key={i}
              className={`alert ${alert.severity === 'critical' ? 'alert-error' : 'alert-warn'}`}
              style={{ marginBottom: i < alertsApi.data!.alerts.length - 1 ? 8 : 0 }}
            >
              <strong>{alert.type.replace(/_/g, ' ')}</strong>
              {alert.count > 0 && <span className="mono" style={{ marginLeft: 8 }}>×{alert.count}</span>}
              <span style={{ marginLeft: 8 }}>{alert.message}</span>
            </div>
          ))}
        </div>
      )}

      {/* Operator metrics */}
      {!metricsApi.loading && metricsApi.data && (
        <div className="card">
          <div className="card-header">
            <span className="card-title">Resource Limits</span>
          </div>
          <div className="status-row">
            <span className="dot dot-cyan" />
            <span className="status-row-label">Concurrency cap</span>
            <span className="status-row-value mono">
              {metricsApi.data.ingestion.concurrency_cap ?? 'not set'}
              {metricsApi.data.ingestion.concurrency_cap_scope && (
                <span className="badge badge-muted" style={{ marginLeft: 8 }}>
                  {metricsApi.data.ingestion.concurrency_cap_scope}
                </span>
              )}
            </span>
          </div>
          <div className="status-row">
            <span className="dot dot-cyan" />
            <span className="status-row-label">Rate limit (rpm)</span>
            <span className="status-row-value mono">
              {metricsApi.data.rate_limit.requests_per_minute ?? 'not set'}
              {metricsApi.data.rate_limit.scope && (
                <span className="badge badge-muted" style={{ marginLeft: 8 }}>
                  {metricsApi.data.rate_limit.scope}
                </span>
              )}
            </span>
          </div>
        </div>
      )}
      {metricsApi.error && (
        <div className="alert alert-warn mb-16" style={{ fontSize: 12 }}>
          Metrics unavailable: {metricsApi.error}
        </div>
      )}

      {/* Endpoint reference */}
      <div className="card">
        <div className="card-header">
          <span className="card-title">Health Endpoint Reference</span>
        </div>
        <table className="data-table">
          <thead>
            <tr><th>Endpoint</th><th>Auth</th><th>Returns</th></tr>
          </thead>
          <tbody>
            <tr>
              <td className="mono">/api/v1/health</td>
              <td><span className="badge badge-muted">none</span></td>
              <td className="text-muted mono" style={{ fontSize: 12 }}>{`{ status: "ok", service: string }`}</td>
            </tr>
            <tr>
              <td className="mono">/api/v1/health/alerts</td>
              <td><span className="badge badge-muted">none</span></td>
              <td className="text-muted mono" style={{ fontSize: 12 }}>{`{ status: "ok"|"degraded", alerts: [] }`}</td>
            </tr>
            <tr>
              <td className="mono">/api/v1/health/metrics</td>
              <td><span className="badge badge-blue">operator</span></td>
              <td className="text-muted mono" style={{ fontSize: 12 }}>{`{ outbox, ingestion, rate_limit }`}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  )
}

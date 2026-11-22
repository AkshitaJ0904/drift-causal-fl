import { api, type DashboardResponse } from '../api/client'
import { useApi } from '../hooks/useApi'

interface Props {
  token: string
}

export default function ModelSchemas({ token }: Props) {
  const { data, loading, error, refresh } = useApi<DashboardResponse>(
    () => api.getDashboard(token),
    [token],
  )

  const count = data?.registries.model_schema_count

  return (
    <div>
      <div className="section-header">
        <div>
          <div className="section-title">Model Schema Registry</div>
          <div className="section-desc">
            Declares the expected tensor names, shapes, and dtypes for each model version. Updates that do not match are rejected at ingestion (rule 100107) before any ML processing.
          </div>
        </div>
        <button className="btn" onClick={refresh}>↻ Refresh</button>
      </div>

      {error && <div className="alert alert-error mb-16">{error}</div>}

      <div className="stat-grid">
        <div className="stat-card">
          <div className="stat-label">Registered Schemas</div>
          <div className="stat-value" style={{ color: 'var(--accent-teal)' }}>
            {loading
              ? <span className="spinner" style={{ width: 16, height: 16 }} />
              : (count ?? '?')}
          </div>
        </div>
      </div>

      <div className="card">
        <div className="card-header">
          <span className="card-title">Schema Operations</span>
          <span className="badge badge-muted">CLI only</span>
        </div>
        <p className="text-muted" style={{ marginBottom: 16 }}>
          Model schemas define the expected tensor names and shapes for accepted updates.
          An update that does not match a registered schema is rejected at ingestion time.
          Schema registration uses UPSERT semantics — register once, update on architecture change.
        </p>
        <table className="data-table">
          <thead>
            <tr><th>Operation</th><th>How</th><th>Notes</th></tr>
          </thead>
          <tbody>
            <tr>
              <td>Register / update schema</td>
              <td className="mono">scripts/register_model_schema.py</td>
              <td className="text-muted">UPSERT by schema_id. No HTTP endpoint in current build.</td>
            </tr>
            <tr>
              <td>Count (read-only)</td>
              <td className="mono">GET /api/v1/operator/dashboard</td>
              <td className="text-muted">
                Returns <span className="mono">registries.model_schema_count</span>. No schema content returned.
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <div className="alert alert-info">
        Schema content (tensor names and shapes) is not exposed by the dashboard API.
        Use the CLI scripts (<span className="mono">scripts/</span>) to list registered schemas.
      </div>
    </div>
  )
}

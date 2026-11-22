import { api, type DashboardResponse } from '../api/client'
import { useApi } from '../hooks/useApi'

interface Props {
  token: string
}

export default function TrustedKeys({ token }: Props) {
  const { data, loading, error, refresh } = useApi<DashboardResponse>(
    () => api.getDashboard(token),
    [token],
  )

  const count = data?.registries.trusted_key_count

  return (
    <div>
      <div className="section-header">
        <div>
          <div className="section-title">Trusted Key Registry</div>
          <div className="section-desc">
            Ed25519 public keys that the gateway trusts for signing FL model updates. An update signed by an unregistered key is blocked (rule 100113).
          </div>
        </div>
        <button className="btn" onClick={refresh}>↻ Refresh</button>
      </div>

      {error && <div className="alert alert-error mb-16">{error}</div>}

      <div className="stat-grid">
        <div className="stat-card">
          <div className="stat-label">Registered Keys</div>
          <div className="stat-value" style={{ color: 'var(--accent-cyan)' }}>
            {loading
              ? <span className="spinner" style={{ width: 16, height: 16 }} />
              : (count ?? '?')}
          </div>
        </div>
      </div>

      <div className="card">
        <div className="card-header">
          <span className="card-title">Key Operations</span>
          <span className="badge badge-muted">CLI only</span>
        </div>
        <p className="text-muted" style={{ marginBottom: 16 }}>
          Key registration and revocation are performed via the CLI or CI pipeline,
          not through this console. Direct submission of key material through a
          browser is prohibited to enforce separation of concerns and auditability.
        </p>
        <table className="data-table">
          <thead>
            <tr><th>Operation</th><th>How</th><th>Notes</th></tr>
          </thead>
          <tbody>
            <tr>
              <td>Register key</td>
              <td className="mono">scripts/register_trusted_key.py</td>
              <td className="text-muted">DER-encoded Ed25519. No HTTP endpoint in current build.</td>
            </tr>
            <tr>
              <td>Revoke key</td>
              <td className="mono">scripts/revoke_trusted_key.py</td>
              <td className="text-muted">Immediate effect. No HTTP endpoint in current build.</td>
            </tr>
            <tr>
              <td>Count (read-only)</td>
              <td className="mono">GET /api/v1/operator/dashboard</td>
              <td className="text-muted">
                Returns <span className="mono">registries.trusted_key_count</span>. No key material returned.
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <div className="alert alert-info">
        Key material is never returned by the API. The dashboard reports counts only.
        Use the CLI scripts (<span className="mono">scripts/</span>) for key provisioning.
      </div>
    </div>
  )
}

import { api, type DashboardResponse } from '../api/client'
import { useApi } from '../hooks/useApi'
import Explain from '../components/Explain'

interface Props {
  token: string
}

const RULE_BASED_THRESHOLDS = [
  {
    envVar: 'FINSENTINEL_MAX_WEIGHT_L2_NORM',
    description: 'Maximum weight L2 norm',
    unit: 'float ≥ 0',
    note: 'Flag updates with unusually large weight magnitudes.',
    explain: 'l2_norm' as const,
  },
  {
    envVar: 'FINSENTINEL_MAX_UPDATE_L2_NORM',
    description: 'Maximum update L2 norm',
    unit: 'float ≥ 0',
    note: 'Flag updates that change weights by an unusually large amount.',
    explain: 'l2_norm' as const,
  },
  {
    envVar: 'FINSENTINEL_MAX_WEIGHT_ABS_MEAN',
    description: 'Maximum mean absolute weight',
    unit: 'float ≥ 0',
    note: 'Flag updates with an unusually high mean weight magnitude.',
  },
  {
    envVar: 'FINSENTINEL_MAX_WEIGHT_STD',
    description: 'Maximum weight standard deviation',
    unit: 'float ≥ 0',
    note: 'Flag updates with unusually high weight variance.',
  },
  {
    envVar: 'FINSENTINEL_MAX_WEIGHT_ZERO_FRACTION',
    description: 'Maximum fraction of zero weights',
    unit: 'float [0, 1]',
    note: 'Flag suspiciously sparse updates.',
  },
  {
    envVar: 'FINSENTINEL_MIN_WEIGHT_ZERO_FRACTION',
    description: 'Minimum fraction of zero weights',
    unit: 'float [0, 1]',
    note: 'Flag updates that are suspiciously dense.',
  },
]

const ENV_VAR_KEYS: Record<string, keyof NonNullable<NonNullable<DashboardResponse['detection']>['thresholds']>> = {
  'FINSENTINEL_MAX_WEIGHT_L2_NORM':     'max_weight_l2_norm',
  'FINSENTINEL_MAX_UPDATE_L2_NORM':     'max_update_l2_norm',
  'FINSENTINEL_MAX_WEIGHT_ABS_MEAN':    'max_weight_abs_mean',
  'FINSENTINEL_MAX_WEIGHT_STD':         'max_weight_std',
  'FINSENTINEL_MAX_WEIGHT_ZERO_FRACTION': 'max_weight_zero_fraction',
  'FINSENTINEL_MIN_WEIGHT_ZERO_FRACTION': 'min_weight_zero_fraction',
}

export default function DetectionConfig({ token }: Props) {
  const { data, loading, error, refresh } = useApi<DashboardResponse>(
    () => api.getDashboard(token),
    [token],
  )

  const detection = data?.detection
  const thresholds = detection?.thresholds

  return (
    <div>
      <div className="section-header">
        <div>
          <div className="section-title">Detection Configuration</div>
          <div className="section-desc">
            Thresholds and policies that govern how the gateway scores and blocks suspicious FL updates. Layer 1 uses deterministic rule checks; Layer 2 (Isolation Forest) is planned.
          </div>
        </div>
        <button className="btn" onClick={refresh}>↻ Refresh</button>
      </div>

      {error && <div className="alert alert-error mb-16">{error}</div>}
      {detection?.error && (
        <div className="alert alert-warn mb-16">
          Detection config unavailable: {detection.error}
        </div>
      )}

      <div className="alert alert-info mb-16">
        Detection is a supplementary statistical layer. It does not replace
        cryptographic signature verification, replay protection, or schema validation.
        No threshold is calibrated by default — configure thresholds using data from
        your production FL system before enabling rules.
      </div>

      {/* Layer 1: Rule-based */}
      <div className="card">
        <div className="card-header">
          <span className="card-title">Layer 1 — Rule-based Detection</span>
          <span className="badge badge-green">Active (thresholds set via env)</span>
        </div>
        <p className="text-muted" style={{ marginBottom: 16 }}>
          Transparent, explainable rules. Each triggered rule adds 25 points to the
          risk score (capped at 100). Risk ≥ 25 → suspicious. At least one threshold
          must be configured for the rule-based layer to activate.
        </p>
        <table className="data-table">
          <thead>
            <tr>
              <th>Environment Variable</th>
              <th>Description</th>
              <th>Unit</th>
              <th>Configured Value</th>
              <th>Notes</th>
            </tr>
          </thead>
          <tbody>
            {RULE_BASED_THRESHOLDS.map((row) => {
              const key = ENV_VAR_KEYS[row.envVar]
              const configured = thresholds?.[key]
              return (
                <tr key={row.envVar}>
                  <td className="mono" style={{ fontSize: 11 }}>{row.envVar}</td>
                  <td style={{ display: 'flex', alignItems: 'center', gap: 4 }}>{row.description}{'explain' in row && row.explain && <Explain term={row.explain} />}</td>
                  <td className="mono text-muted">{row.unit}</td>
                  <td>
                    {loading
                      ? <span className="spinner" style={{ width: 12, height: 12 }} />
                      : configured != null
                        ? <span className="mono" style={{ color: 'var(--accent-cyan)', fontSize: 12 }}>{configured}</span>
                        : <span className="text-muted" style={{ fontSize: 11 }}>not set</span>}
                  </td>
                  <td className="text-muted">{row.note}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
        <div className="info-box" style={{ marginTop: 16 }}>
          <div className="stat-label" style={{ marginBottom: 6 }}>
            High-risk action — env: <span className="mono">FINSENTINEL_HIGH_RISK_ACTION</span>
            {!loading && detection?.high_risk_action && (
              <span className="badge badge-cyan" style={{ marginLeft: 10 }}>
                active: {detection.high_risk_action}
              </span>
            )}
          </div>
          <div className="text-muted" style={{ fontSize: 12, lineHeight: 1.6 }}>
            <span className="badge badge-yellow mono">quarantined</span>
            <span style={{ marginLeft: 8 }}>
              (default) — place high/critical updates in quarantine for operator review.
            </span>
            <br />
            <span className="badge badge-blue mono" style={{ marginTop: 4, display: 'inline-block' }}>pending_approval</span>
            <span style={{ marginLeft: 8 }}>
              — route high/critical updates to the pending-approval queue instead.
            </span>
          </div>
        </div>
      </div>

      {/* Layer 2: Isolation Forest */}
      <div className="card">
        <div className="card-header">
          <span className="card-title">Layer 2 — Isolation Forest</span>
          <span className="badge badge-muted">Not wired into pipeline</span>
        </div>
        <p className="text-muted" style={{ marginBottom: 16 }}>
          Unsupervised statistical anomaly detector. Must be trained on representative
          clean update vectors before deployment. See{' '}
          <span className="mono">detection/isolation_forest.py</span> for the implementation.
        </p>
        <div className="card" style={{ background: 'var(--bg-elevated)', border: '1px solid var(--border)', margin: 0, marginBottom: 12 }}>
          <div className="card-title" style={{ marginBottom: 10, fontSize: 12, color: 'var(--text-secondary)' }}>
            Deployment Workflow
          </div>
          <ol style={{ paddingLeft: 20, lineHeight: 2, color: 'var(--text-secondary)', fontSize: 12, margin: 0 }}>
            <li>Collect clean update feature vectors from production traffic.</li>
            <li>Instantiate <span className="mono">IsolationForestDetector</span> with an <span className="mono">IsolationForestConfig</span>.</li>
            <li>Call <span className="mono">detector.fit(feature_vectors)</span> with ≥100 clean samples.</li>
            <li>Save the fitted detector: <span className="mono">detector.save("path/to/model.joblib")</span>.</li>
            <li>Set <span className="mono">FINSENTINEL_IF_MODEL_PATH</span> to the saved file path and restart.</li>
            <li>Monitor false-positive rate and re-train as the model distribution shifts.</li>
          </ol>
        </div>
        <div className="alert alert-warn" style={{ marginBottom: 0 }}>
          Only load detector files from trusted, integrity-verified sources.
          Detector files use Python pickle serialization.
        </div>
      </div>
    </div>
  )
}

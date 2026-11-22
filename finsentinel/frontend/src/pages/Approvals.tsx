import { useState, useCallback } from 'react'
import { api, type ApprovalRecord, ApiError } from '../api/client'
import { useApi } from '../hooks/useApi'

interface Props {
  token: string
}

type Action = 'approve' | 'reject' | 'quarantine'

interface PendingAction {
  clientId: string
  updateId: string
  action: Action
  reason: string
}

function statusBadge(status: string) {
  if (status === 'pending_approval') return <span className="badge badge-yellow">pending</span>
  if (status === 'approved')         return <span className="badge badge-green">approved</span>
  if (status === 'rejected')         return <span className="badge badge-red">rejected</span>
  if (status === 'quarantined')      return <span className="badge badge-blue">quarantined</span>
  return <span className="badge badge-muted">{status}</span>
}

function riskBadge(rec: ApprovalRecord) {
  if (rec.risk_score === null) {
    return <span className="text-muted" style={{ fontSize: 12 }}>—</span>
  }
  const sev = (rec.risk_severity ?? '').toLowerCase()
  let cls = 'badge-muted'
  if (sev === 'critical')             cls = 'badge-red'
  else if (sev === 'high' || rec.suspicious) cls = 'badge-yellow'
  else if (sev === 'low' || sev === 'none')  cls = 'badge-green'
  return (
    <span className={`badge ${cls}`}>
      {rec.risk_score} · {rec.risk_severity ?? '?'}
    </span>
  )
}

function actionLabel(action: Action) {
  if (action === 'approve')    return 'Approve'
  if (action === 'reject')     return 'Reject'
  return 'Quarantine'
}

function actionButtonClass(action: Action) {
  if (action === 'approve')    return 'btn btn-primary'
  if (action === 'reject')     return 'btn btn-danger'
  return 'btn btn-warn'
}

function approvalWhatHappened(rec: ApprovalRecord): string {
  const short = rec.update_id.slice(0, 8)
  const reasons = rec.anomaly_reasons?.length ? rec.anomaly_reasons.join('; ') : 'no anomaly detected'
  return `Client ${rec.client_id} submitted model update ${short}… for round ${rec.round_number} of ${rec.model_version}. Risk score: ${rec.risk_score ?? '?'} (${rec.risk_severity ?? 'unscored'}). Anomaly: ${reasons}.`
}

function approvalWhyItMatters(rec: ApprovalRecord): string {
  const sev = (rec.risk_severity ?? '').toLowerCase()
  if (sev === 'critical') return 'Critical risk — the update shows strong statistical anomaly and may be a poisoning attempt. Block it unless you can explain the deviation.'
  if (sev === 'high' || rec.suspicious) return 'High risk or anomaly flag — the update deviates significantly from expected gradients. Review before approving.'
  if (sev === 'medium') return 'Moderate anomaly score. Review the L2 norm and anomaly reasons. Approve only if the deviation is expected (e.g. new data batch).'
  return 'Low risk score — the update passed all threshold checks and shows no anomaly. Routine approval.'
}

function approvalSystemDid(_rec: ApprovalRecord): string {
  return 'Update held in the approval queue. It will not be aggregated into the global model until you approve, reject, or quarantine it here.'
}

function approvalWhatToDo(rec: ApprovalRecord): string {
  const sev = (rec.risk_severity ?? '').toLowerCase()
  if (sev === 'critical') return 'Reject or quarantine immediately. Investigate the client and check correlated events in Wazuh Security Center.'
  if (sev === 'high' || rec.suspicious) return 'Quarantine for further analysis, or reject if the anomaly is unexplained. Check the Security Center for related events.'
  return 'Review the anomaly reasons and risk score. If the update looks legitimate, approve it with a reason. A required reason is recorded in the audit trail.'
}

// ---------------------------------------------------------------------------
// Expandable detail panel for an approval record
// ---------------------------------------------------------------------------
function ApprovalDetailPanel({ rec }: { rec: ApprovalRecord }) {
  const [techOpen, setTechOpen] = useState(false)
  const copyId = useCallback(() => {
    navigator.clipboard.writeText(rec.update_id).catch(() => {})
  }, [rec.update_id])

  return (
    <div style={{ padding: '12px 16px', background: 'var(--bg-hover)', borderTop: '1px solid var(--border)', fontSize: 12.5 }}>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginBottom: 12 }}>
        <div>
          <div style={{ fontWeight: 600, color: 'var(--text-secondary)', marginBottom: 4 }}>What happened</div>
          <div style={{ color: 'var(--text-primary)' }}>{approvalWhatHappened(rec)}</div>
        </div>
        <div>
          <div style={{ fontWeight: 600, color: 'var(--text-secondary)', marginBottom: 4 }}>Why it matters</div>
          <div style={{ color: 'var(--text-primary)' }}>{approvalWhyItMatters(rec)}</div>
        </div>
        <div>
          <div style={{ fontWeight: 600, color: 'var(--text-secondary)', marginBottom: 4 }}>What the system did</div>
          <div style={{ color: 'var(--text-primary)' }}>{approvalSystemDid(rec)}</div>
        </div>
        <div>
          <div style={{ fontWeight: 600, color: 'var(--text-secondary)', marginBottom: 4 }}>What you should do</div>
          <div style={{ color: 'var(--text-primary)' }}>{approvalWhatToDo(rec)}</div>
        </div>
      </div>

      <button
        type="button"
        onClick={() => setTechOpen(o => !o)}
        style={{ fontSize: 11, color: 'var(--text-muted)', background: 'none', border: 'none', cursor: 'pointer', padding: 0, marginBottom: techOpen ? 8 : 0 }}
        aria-expanded={techOpen}
      >
        {techOpen ? '▾' : '▸'} Technical details
      </button>

      {techOpen && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 8, fontSize: 11.5 }}>
          <div>
            <span style={{ color: 'var(--text-muted)' }}>Update ID </span>
            <span style={{ fontFamily: 'monospace' }}>{rec.update_id.slice(0, 8)}…</span>
            <button type="button" onClick={copyId} style={{ marginLeft: 4, fontSize: 10, color: 'var(--accent-cyan)', background: 'none', border: 'none', cursor: 'pointer' }}>copy</button>
          </div>
          <div title={rec.client_id}>
            <span style={{ color: 'var(--text-muted)' }}>Client </span>
            <span style={{ fontFamily: 'monospace' }}>{rec.client_id.length > 20 ? rec.client_id.slice(0, 20) + '…' : rec.client_id}</span>
          </div>
          <div><span style={{ color: 'var(--text-muted)' }}>Model </span><span style={{ fontFamily: 'monospace' }}>{rec.model_version}</span></div>
          <div><span style={{ color: 'var(--text-muted)' }}>Round </span>{rec.round_number}</div>
          {rec.risk_score !== null && <div><span style={{ color: 'var(--text-muted)' }}>Risk score </span>{rec.risk_score} · {rec.risk_severity}</div>}
          {rec.sample_count !== null && <div><span style={{ color: 'var(--text-muted)' }}>Sample count </span>{rec.sample_count}</div>}
          {rec.anomaly_reasons?.length > 0 && (
            <div style={{ gridColumn: '1 / -1' }}>
              <span style={{ color: 'var(--text-muted)' }}>Anomaly reasons </span>
              <span style={{ fontFamily: 'monospace' }}>{rec.anomaly_reasons.join(', ')}</span>
            </div>
          )}
          {rec.payload_sha256 && (
            <div style={{ gridColumn: '1 / -1' }}>
              <span style={{ color: 'var(--text-muted)' }}>SHA-256 </span>
              <span style={{ fontFamily: 'monospace', fontSize: 11 }}>{rec.payload_sha256}</span>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

export default function Approvals({ token }: Props) {
  const { data, loading, error, refresh } = useApi(
    () => api.getPendingApprovals(token),
    [token],
  )

  const [pending, setPending] = useState<PendingAction | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)
  const [actionOk, setActionOk] = useState<string | null>(null)
  const [expanded, setExpanded] = useState<number | null>(null)

  const startAction = (e: React.MouseEvent, rec: ApprovalRecord, action: Action) => {
    e.stopPropagation()
    setActionError(null)
    setActionOk(null)
    setPending({ clientId: rec.client_id, updateId: rec.update_id, action, reason: '' })
  }

  const confirmAction = async () => {
    if (!pending) return
    if (!pending.reason.trim()) {
      setActionError('A reason is required. This decision is recorded in the audit trail.')
      return
    }
    setSubmitting(true)
    setActionError(null)
    try {
      const { clientId, updateId, action, reason } = pending
      if (action === 'approve')      await api.approveUpdate(token, clientId, updateId, reason)
      else if (action === 'reject')  await api.rejectUpdate(token, clientId, updateId, reason)
      else                           await api.quarantineUpdate(token, clientId, updateId, reason)
      const pastLabel: Record<Action, string> = { approve: 'Approved', reject: 'Rejected', quarantine: 'Quarantined' }
      setActionOk(`${pastLabel[action]} update ${updateId}.`)
      setPending(null)
      setExpanded(null)
      refresh()
    } catch (err) {
      const msg = err instanceof ApiError
        ? `HTTP ${err.status}: ${err.message}`
        : (err instanceof Error ? err.message : 'Unknown error')
      setActionError(msg)
    } finally {
      setSubmitting(false)
    }
  }

  const toggleRow = (i: number) => setExpanded(expanded === i ? null : i)

  const records: ApprovalRecord[] = data?.pending ?? []

  return (
    <div>
      {actionOk    && <div className="alert alert-success mb-16">{actionOk}</div>}
      {actionError && !pending && <div className="alert alert-error mb-16">{actionError}</div>}
      {error       && <div className="alert alert-error mb-16">{error}</div>}

      <div className="section-header">
        <div>
          <div className="section-title">Pending Approvals</div>
          <div className="section-desc">
            FL model updates that have been flagged and are waiting for your decision. Each decision is permanently recorded in the audit trail — a mandatory reason is required.
          </div>
        </div>
        <button className="btn" onClick={refresh}>↻ Refresh</button>
      </div>

      {/* Inline confirmation panel */}
      {pending && (
        <div className="action-panel">
          <div className="action-panel-title">
            <span className={`badge ${pending.action === 'approve' ? 'badge-green' : pending.action === 'reject' ? 'badge-red' : 'badge-yellow'}`}>
              {actionLabel(pending.action)}
            </span>
            update&nbsp;
            <span className="mono" style={{ fontSize: 12, color: 'var(--text-primary)' }} title={pending.updateId}>
              {pending.updateId.length > 8 ? pending.updateId.slice(0, 8) + '…' : pending.updateId}
            </span>
          </div>

          <div className="form-group" style={{ marginBottom: 14 }}>
            <label className="form-label" htmlFor="action-reason">
              Decision Reason <span style={{ color: 'var(--text-danger)', fontWeight: 700 }}>*</span>
            </label>
            <textarea
              id="action-reason"
              className="form-input"
              rows={3}
              placeholder="Enter a reason for this decision — required, recorded in the audit trail"
              value={pending.reason}
              onChange={(e) => setPending({ ...pending, reason: e.target.value })}
              style={{ resize: 'vertical', fontSize: 13, fontFamily: 'inherit' }}
            />
          </div>
          {actionError && (
            <div className="alert alert-error" style={{ marginBottom: 12 }}>{actionError}</div>
          )}
          <div className="flex gap-8">
            <button
              className={actionButtonClass(pending.action)}
              disabled={submitting}
              onClick={confirmAction}
            >
              {submitting
                ? <><span className="spinner" style={{ width: 14, height: 14 }} /> Working…</>
                : `Confirm ${actionLabel(pending.action)}`}
            </button>
            <button className="btn" onClick={() => setPending(null)} disabled={submitting}>
              Cancel
            </button>
          </div>
        </div>
      )}

      {/* Records table */}
      {loading ? (
        <div className="loading-row"><span className="spinner" /> Loading approval queue…</div>
      ) : records.length === 0 ? (
        <div className="card" style={{ textAlign: 'center', padding: '40px 20px' }}>
          <div style={{ fontSize: 24, marginBottom: 8, opacity: 0.3 }}>◎</div>
          <div className="text-muted" style={{ fontSize: 13 }}>No pending approvals.</div>
          <div className="text-muted" style={{ fontSize: 11, marginTop: 4 }}>
            Approved updates appear in the Audit Outbox.
          </div>
        </div>
      ) : (
        <div style={{ overflowX: 'auto', border: '1px solid var(--border)', borderRadius: 'var(--radius)' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
            <thead>
              <tr style={{ borderBottom: '1px solid var(--border)', background: 'var(--bg-hover)' }}>
                {['', 'Update ID', 'Client ID', 'Model / Round', 'Risk', 'Status', ''].map((h, i) => (
                  <th key={i} style={{ textAlign: i === 6 ? 'right' : 'left', padding: '7px 8px', color: 'var(--text-muted)', fontWeight: 600, fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.06em' }}>
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {records.map((rec, i) => (
                <>
                  <tr
                    key={`row-${rec.update_id}`}
                    onClick={() => toggleRow(i)}
                    onKeyDown={e => (e.key === 'Enter' || e.key === ' ') && toggleRow(i)}
                    tabIndex={0}
                    style={{
                      borderBottom: expanded === i ? 'none' : '1px solid var(--border)',
                      cursor: 'pointer',
                      background: expanded === i ? 'var(--bg-hover)' : undefined,
                    }}
                    aria-expanded={expanded === i}
                  >
                    <td style={{ padding: '6px 8px', color: 'var(--text-muted)', fontSize: 10 }}>{expanded === i ? '▾' : '▸'}</td>
                    <td className="mono" style={{ padding: '6px 8px', fontSize: 12, maxWidth: 120, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      <span title={rec.update_id}>{rec.update_id}</span>
                    </td>
                    <td className="mono" style={{ padding: '6px 8px', fontSize: 12, maxWidth: 140, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      <span title={rec.client_id}>{rec.client_id}</span>
                    </td>
                    <td style={{ padding: '6px 8px' }}>
                      <div className="mono" style={{ fontSize: 11 }}>{rec.model_version}</div>
                      <div className="text-muted" style={{ fontSize: 11 }}>round {rec.round_number}</div>
                    </td>
                    <td style={{ padding: '6px 8px' }}>{riskBadge(rec)}</td>
                    <td style={{ padding: '6px 8px' }}>{statusBadge(rec.status)}</td>
                    <td style={{ padding: '6px 8px', textAlign: 'right' }}>
                      <div className="flex gap-6" style={{ justifyContent: 'flex-end' }}>
                        <button
                          className="btn btn-primary btn-sm"
                          disabled={pending?.updateId === rec.update_id}
                          onClick={e => startAction(e, rec, 'approve')}
                        >
                          Approve
                        </button>
                        <button
                          className="btn btn-warn btn-sm"
                          disabled={pending?.updateId === rec.update_id}
                          onClick={e => startAction(e, rec, 'quarantine')}
                        >
                          Quarantine
                        </button>
                        <button
                          className="btn btn-danger btn-sm"
                          disabled={pending?.updateId === rec.update_id}
                          onClick={e => startAction(e, rec, 'reject')}
                        >
                          Reject
                        </button>
                      </div>
                    </td>
                  </tr>
                  {expanded === i && (
                    <tr key={`detail-${rec.update_id}`} style={{ borderBottom: '1px solid var(--border)' }}>
                      <td colSpan={7} style={{ padding: 0 }}>
                        <ApprovalDetailPanel rec={rec} />
                      </td>
                    </tr>
                  )}
                </>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {records.length > 0 && (
        <div className="text-muted mt-8" style={{ fontSize: 11 }}>
          {records.length} update(s) pending — click any row for details · each decision requires a reason and is recorded in the audit trail.
        </div>
      )}
    </div>
  )
}

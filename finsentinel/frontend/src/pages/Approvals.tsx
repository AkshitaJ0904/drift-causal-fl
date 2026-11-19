import { useState } from 'react'
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

export default function Approvals({ token }: Props) {
  const { data, loading, error, refresh } = useApi(
    () => api.getPendingApprovals(token),
    [token],
  )

  const [pending, setPending] = useState<PendingAction | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)
  const [actionOk, setActionOk] = useState<string | null>(null)

  const startAction = (rec: ApprovalRecord, action: Action) => {
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

  const records: ApprovalRecord[] = data?.pending ?? []

  return (
    <div>
      {actionOk    && <div className="alert alert-success mb-16">{actionOk}</div>}
      {actionError && <div className="alert alert-error mb-16">{actionError}</div>}
      {error       && <div className="alert alert-error mb-16">{error}</div>}

      <div className="section-header">
        <div>
          <div className="section-title">Pending Approvals</div>
          <div className="section-desc">
            Updates awaiting operator decision — approve, reject, or quarantine with a mandatory reason
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
            <span className="mono" style={{ fontSize: 12, color: 'var(--text-primary)' }}>
              {pending.updateId}
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
        <div className="card" style={{ padding: 0 }}>
          <table className="data-table">
            <thead>
              <tr>
                <th>Update ID</th>
                <th>Client ID</th>
                <th>Model / Round</th>
                <th>Risk</th>
                <th>Status</th>
                <th style={{ textAlign: 'right' }}>Decision</th>
              </tr>
            </thead>
            <tbody>
              {records.map((rec) => (
                <tr key={rec.update_id}>
                  <td className="mono" style={{ maxWidth: 160, overflow: 'hidden', textOverflow: 'ellipsis' }}>
                    {rec.update_id}
                  </td>
                  <td className="mono" style={{ maxWidth: 140, overflow: 'hidden', textOverflow: 'ellipsis' }}>
                    {rec.client_id}
                  </td>
                  <td>
                    <div className="mono" style={{ fontSize: 11 }}>{rec.model_version}</div>
                    <div className="text-muted" style={{ fontSize: 11 }}>round {rec.round_number}</div>
                  </td>
                  <td>{riskBadge(rec)}</td>
                  <td>{statusBadge(rec.status)}</td>
                  <td style={{ textAlign: 'right' }}>
                    <div className="flex gap-6" style={{ justifyContent: 'flex-end' }}>
                      <button
                        className="btn btn-primary btn-sm"
                        disabled={pending?.updateId === rec.update_id}
                        onClick={() => startAction(rec, 'approve')}
                      >
                        Approve
                      </button>
                      <button
                        className="btn btn-warn btn-sm"
                        disabled={pending?.updateId === rec.update_id}
                        onClick={() => startAction(rec, 'quarantine')}
                      >
                        Quarantine
                      </button>
                      <button
                        className="btn btn-danger btn-sm"
                        disabled={pending?.updateId === rec.update_id}
                        onClick={() => startAction(rec, 'reject')}
                      >
                        Reject
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {records.length > 0 && (
        <div className="text-muted mt-8" style={{ fontSize: 11 }}>
          {records.length} update(s) pending — each decision requires a reason and is recorded in the audit trail.
        </div>
      )}
    </div>
  )
}

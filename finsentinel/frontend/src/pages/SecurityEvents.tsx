import { useState, useCallback } from 'react'
import {
  api,
  type SecurityEvent,
  type DetectionRule,
  type VaptFinding,
  type VaptCategoryCount,
} from '../api/client'
import { useApi } from '../hooks/useApi'

interface Props {
  token: string
}

const SEVERITY_COLORS: Record<string, string> = {
  Low:      'var(--sev-low)',
  Medium:   'var(--sev-medium)',
  High:     'var(--sev-high)',
  Critical: 'var(--sev-critical)',
  Unknown:  'var(--text-muted)',
}

const SEVERITY_BG: Record<string, string> = {
  Low:      'rgba(22,163,74,0.08)',
  Medium:   'rgba(217,119,6,0.08)',
  High:     'rgba(220,38,38,0.08)',
  Critical: 'rgba(127,29,29,0.08)',
  Unknown:  'rgba(156,163,175,0.1)',
}

function SeverityBadge({ severity }: { severity: string }) {
  const color = SEVERITY_COLORS[severity] ?? SEVERITY_COLORS.Unknown
  const bg = SEVERITY_BG[severity] ?? SEVERITY_BG.Unknown
  return (
    <span
      style={{
        display: 'inline-block',
        padding: '2px 8px',
        borderRadius: 4,
        fontSize: 11,
        fontWeight: 600,
        color,
        background: bg,
        border: `1px solid ${color}`,
        whiteSpace: 'nowrap',
      }}
    >
      {severity}
    </span>
  )
}

function fmt(ts?: string): string {
  if (!ts) return '—'
  try { return new Date(ts).toLocaleString() } catch { return ts }
}

const WAZUH_URL = (import.meta.env.VITE_WAZUH_URL as string | undefined) ?? 'https://localhost'

type FilterChip = 'all' | 'blocked' | 'decision' | 'normal'

const FILTER_LABELS: Record<FilterChip, string> = {
  all: 'All',
  blocked: 'Attacks blocked',
  decision: 'Needs decision',
  normal: 'Normal',
}

const BLOCKED_TYPES = new Set([
  'security.signature_verification_failed',
  'security.replay_detected',
  'security.payload_integrity_failed',
  'security.unknown_signing_key',
  'security.client_key_mismatch',
  'security.sample_count_limit_missing',
])

const DECISION_TYPES = new Set([
  'security.update_pending_approval',
  'security.update_quarantined',
  'security.anomaly_detected',
  'operator.update_quarantined',
  'operator.quarantine_requested',
])

function getFilterCategory(ev: SecurityEvent): FilterChip {
  if (BLOCKED_TYPES.has(ev.event_type ?? '')) return 'blocked'
  if (DECISION_TYPES.has(ev.event_type ?? '')) return 'decision'
  return 'normal'
}

function whatSystemDid(ev: SecurityEvent): string {
  const t = ev.event_type ?? ''
  if (t.includes('blocked') || t.includes('failed') || t.includes('rejected')) return 'Update blocked — not passed to aggregation.'
  if (t.includes('quarantine')) return 'Update moved to quarantine queue — pending operator review.'
  if (t.includes('pending_approval')) return 'Update registered for operator approval before aggregation.'
  if (t.includes('anomaly_detected')) return 'Statistical anomaly flagged; update held for review.'
  if (t.includes('anomaly_clean')) return 'Anomaly check passed; update continues through the pipeline.'
  if (t.includes('approved')) return 'Operator approved; update cleared for aggregation.'
  if (t.includes('rejected')) return 'Operator rejected; update discarded from pipeline.'
  if (t.includes('registered') || t.includes('clean') || t.includes('authenticated')) return 'Event recorded in audit log; no blocking action taken.'
  return 'Event recorded in audit log.'
}

function whatToDo(ev: SecurityEvent): string {
  const sev = (ev.severity ?? '').toLowerCase()
  const t = ev.event_type ?? ''
  if (t.includes('signature_verification') || t.includes('replay') || t.includes('payload_integrity') || t.includes('client_key_mismatch')) {
    return 'Investigate the client immediately. Revoke their key if compromise is suspected. Check the SIEM for correlated events.'
  }
  if (t.includes('quarantine') || t.includes('pending_approval')) {
    return 'Review the update in the Approvals page. Approve, reject, or leave in quarantine pending further analysis.'
  }
  if (t.includes('anomaly_detected')) {
    return 'Review the anomaly score and L2 norm. If abnormal, quarantine or reject the update.'
  }
  if (sev === 'critical') return 'Immediate investigation required. Check correlated events in Wazuh.'
  if (sev === 'high') return 'Review within the hour. Check for related events from the same client.'
  if (sev === 'medium') return 'Monitor for recurrence. No immediate action required unless pattern continues.'
  return 'No action required — informational event.'
}

// ---------------------------------------------------------------------------
// Expandable row detail panel
// ---------------------------------------------------------------------------
function EventDetailPanel({ ev }: { ev: SecurityEvent }) {
  const [techOpen, setTechOpen] = useState(false)
  const copyId = useCallback(() => {
    if (ev.update_id) navigator.clipboard.writeText(ev.update_id).catch(() => {})
  }, [ev.update_id])

  return (
    <div style={{ padding: '12px 16px', background: 'var(--bg-hover)', borderTop: '1px solid var(--border)', fontSize: 12.5 }}>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginBottom: 12 }}>
        <div>
          <div style={{ fontWeight: 600, color: 'var(--text-secondary)', marginBottom: 4 }}>What happened</div>
          <div style={{ color: 'var(--text-primary)' }}>{ev.plain_english ?? ev.event_type ?? '—'}</div>
        </div>
        <div>
          <div style={{ fontWeight: 600, color: 'var(--text-secondary)', marginBottom: 4 }}>Why it matters</div>
          <div style={{ color: 'var(--text-primary)' }}>
            <SeverityBadge severity={ev.severity ?? 'Unknown'} /> severity event —{' '}
            {(ev.severity ?? '') === 'Critical' ? 'immediate investigation required.' :
             (ev.severity ?? '') === 'High' ? 'review within the hour.' :
             (ev.severity ?? '') === 'Medium' ? 'monitor for recurrence.' : 'informational; no action required.'}
          </div>
        </div>
        <div>
          <div style={{ fontWeight: 600, color: 'var(--text-secondary)', marginBottom: 4 }}>What the system did</div>
          <div style={{ color: 'var(--text-primary)' }}>{whatSystemDid(ev)}</div>
        </div>
        <div>
          <div style={{ fontWeight: 600, color: 'var(--text-secondary)', marginBottom: 4 }}>What you should do</div>
          <div style={{ color: 'var(--text-primary)' }}>{whatToDo(ev)}</div>
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
          {ev.update_id && (
            <div>
              <span style={{ color: 'var(--text-muted)' }}>Update ID </span>
              <span style={{ fontFamily: 'monospace' }}>{ev.update_id.slice(0, 8)}…</span>
              <button type="button" onClick={copyId} style={{ marginLeft: 4, fontSize: 10, color: 'var(--accent-cyan)', background: 'none', border: 'none', cursor: 'pointer' }}>copy</button>
            </div>
          )}
          {ev.client_id && <div><span style={{ color: 'var(--text-muted)' }}>Client </span><span style={{ fontFamily: 'monospace' }}>{ev.client_id}</span></div>}
          {ev.event_type && <div><span style={{ color: 'var(--text-muted)' }}>Event type </span><span style={{ fontFamily: 'monospace' }}>{ev.event_type}</span></div>}
          {ev.rule_id && <div><span style={{ color: 'var(--text-muted)' }}>Rule ID </span><span style={{ fontFamily: 'monospace' }}>{ev.rule_id}</span></div>}
          {ev.timestamp && <div><span style={{ color: 'var(--text-muted)' }}>Timestamp </span>{ev.timestamp}</div>}
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Tab: Live Events
// ---------------------------------------------------------------------------
function LiveEventsTab({ token }: { token: string }) {
  const { data, loading, error, refresh } = useApi(
    () => api.getSecurityEvents(token, 50),
    [token],
    { pollingIntervalMs: 10_000 },
  )
  const events = data?.events ?? []
  const [filter, setFilter] = useState<FilterChip>('all')
  const [search, setSearch] = useState('')
  const [expanded, setExpanded] = useState<number | null>(null)

  const filtered = events.filter((ev: SecurityEvent) => {
    if (filter !== 'all' && getFilterCategory(ev) !== filter) return false
    if (search && !(ev.client_id ?? '').toLowerCase().includes(search.toLowerCase())) return false
    return true
  })

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8, marginBottom: 12, flexWrap: 'wrap' }}>
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
          {(Object.keys(FILTER_LABELS) as FilterChip[]).map(f => (
            <button
              key={f}
              type="button"
              onClick={() => { setFilter(f); setExpanded(null) }}
              style={{
                padding: '4px 12px',
                borderRadius: 20,
                fontSize: 12,
                fontWeight: filter === f ? 600 : 400,
                border: filter === f ? '1px solid var(--accent-cyan)' : '1px solid var(--border)',
                background: filter === f ? 'var(--accent-cyan)' : 'var(--bg-card)',
                color: filter === f ? '#FFF' : 'var(--text-secondary)',
                cursor: 'pointer',
              }}
            >
              {FILTER_LABELS[f]}
            </button>
          ))}
          <input
            type="search"
            placeholder="Search by client…"
            value={search}
            onChange={e => setSearch(e.target.value)}
            style={{
              padding: '4px 10px',
              borderRadius: 20,
              border: '1px solid var(--border)',
              background: 'var(--bg-input)',
              color: 'var(--text-primary)',
              fontSize: 12,
              outline: 'none',
              width: 160,
            }}
          />
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <a href={WAZUH_URL} target="_blank" rel="noopener noreferrer" className="btn" style={{ fontSize: 12 }}>Open in Wazuh ↗</a>
          <button className="btn" onClick={refresh}>↻ Refresh</button>
        </div>
      </div>

      {error && <div className="alert alert-error mb-16">{error}</div>}
      {data?.message && <div className="alert alert-warn mb-16">{data.message}</div>}

      {loading && events.length === 0 && (
        <div style={{ display: 'flex', justifyContent: 'center', padding: 32 }}><span className="spinner" /></div>
      )}

      {!loading && filtered.length === 0 && !error && (
        <div className="alert mb-16" style={{ color: 'var(--text-muted)' }}>No events match the current filter.</div>
      )}

      {filtered.length > 0 && (
        <div style={{ overflowX: 'auto', border: '1px solid var(--border)', borderRadius: 'var(--radius)' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
            <thead>
              <tr style={{ borderBottom: '1px solid var(--border)', background: 'var(--bg-hover)' }}>
                {['', 'Time', 'Severity', 'What happened', 'Client', 'Update ID', 'Rule'].map(h => (
                  <th key={h} style={{ textAlign: 'left', padding: '7px 8px', color: 'var(--text-muted)', fontWeight: 600, fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.06em' }}>
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {filtered.map((ev: SecurityEvent, i: number) => (
                <>
                  <tr
                    key={`row-${i}`}
                    onClick={() => setExpanded(expanded === i ? null : i)}
                    style={{ borderBottom: expanded === i ? 'none' : '1px solid var(--border)', opacity: loading ? 0.6 : 1, cursor: 'pointer', background: expanded === i ? 'var(--bg-hover)' : undefined }}
                    aria-expanded={expanded === i}
                  >
                    <td style={{ padding: '6px 8px', color: 'var(--text-muted)', fontSize: 10 }}>{expanded === i ? '▾' : '▸'}</td>
                    <td style={{ padding: '6px 8px', whiteSpace: 'nowrap', fontFamily: 'monospace', fontSize: 12 }}>{fmt(ev.timestamp)}</td>
                    <td style={{ padding: '6px 8px' }}><SeverityBadge severity={ev.severity ?? 'Unknown'} /></td>
                    <td style={{ padding: '6px 8px', maxWidth: 300 }}>{ev.plain_english ?? ev.event_type ?? '—'}</td>
                    <td style={{ padding: '6px 8px', fontFamily: 'monospace', fontSize: 12 }}>{ev.client_id ?? '—'}</td>
                    <td style={{ padding: '6px 8px', fontFamily: 'monospace', fontSize: 11, color: 'var(--text-muted)' }}>
                      {ev.update_id ? ev.update_id.slice(0, 8) + '…' : '—'}
                    </td>
                    <td style={{ padding: '6px 8px', fontFamily: 'monospace', fontSize: 12, color: 'var(--text-muted)' }}>
                      {ev.rule_id ? `#${ev.rule_id}` : '—'}
                    </td>
                  </tr>
                  {expanded === i && (
                    <tr key={`detail-${i}`} style={{ borderBottom: '1px solid var(--border)' }}>
                      <td colSpan={7} style={{ padding: 0 }}>
                        <EventDetailPanel ev={ev} />
                      </td>
                    </tr>
                  )}
                </>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div style={{ marginTop: 16, fontSize: 12, color: 'var(--text-muted)' }}>
        {filtered.length}/{events.length} events shown · Auto-refreshes every 10 s · Brute-force correlation (rule 100140) and MITRE mapping happen in Wazuh.
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Rule detail panel (Detection Rules tab)
// ---------------------------------------------------------------------------
function RuleDetailPanel({ r }: { r: DetectionRule }) {
  const isBruteForce = r.rule_id === '100140'
  const emittedByBackend = r.match_type !== 'correlation'
  return (
    <div style={{ padding: '12px 16px', background: 'var(--bg-hover)', borderTop: '1px solid var(--border)', fontSize: 12.5 }}>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginBottom: 10 }}>
        <div>
          <div style={{ fontWeight: 600, color: 'var(--text-secondary)', marginBottom: 4 }}>Trigger condition</div>
          <div style={{ color: 'var(--text-primary)' }}>
            {isBruteForce
              ? '5 or more failed operator-auth attempts within 60 seconds (Wazuh-side frequency rule — not emitted by the FinSentinel gateway directly).'
              : `Emitted by the backend when: ${r.plain_english.toLowerCase()}.`}
          </div>
        </div>
        <div>
          <div style={{ fontWeight: 600, color: 'var(--text-secondary)', marginBottom: 4 }}>Why it matters</div>
          <div style={{ color: 'var(--text-primary)' }}>{r.why_it_matters || <span style={{ color: 'var(--text-muted)' }}>—</span>}</div>
        </div>
        <div>
          <div style={{ fontWeight: 600, color: 'var(--text-secondary)', marginBottom: 4 }}>What to do</div>
          <div style={{ color: 'var(--text-primary)' }}>{r.what_to_do || <span style={{ color: 'var(--text-muted)' }}>—</span>}</div>
        </div>
        <div>
          <div style={{ fontWeight: 600, color: 'var(--text-secondary)', marginBottom: 4 }}>Example</div>
          <div style={{ color: 'var(--text-muted)', fontFamily: 'monospace', fontSize: 11.5 }}>{r.example || '—'}</div>
        </div>
      </div>
      <div style={{ display: 'flex', gap: 16, fontSize: 11, color: 'var(--text-muted)', flexWrap: 'wrap' }}>
        <span>Severity: <strong style={{ color: 'var(--text-primary)' }}>{r.severity}</strong> (level {r.level})</span>
        <span>Match: <strong style={{ color: 'var(--text-primary)' }}>{r.match_type}</strong></span>
        <span>Emitted by backend: <strong style={{ color: 'var(--text-primary)' }}>{emittedByBackend ? 'yes' : 'no — Wazuh correlation'}</strong></span>
        <span>MITRE: <strong style={{ color: 'var(--text-primary)' }}>
          {r.rule_id === '100104' || r.rule_id === '100113' || r.rule_id === '100114' ? 'T1565 (Data Manipulation)' :
           r.rule_id === '100105' ? 'T1550.001 (Use Alternate Auth Material)' :
           r.rule_id === '100140' ? 'T1110 (Brute Force)' :
           r.rule_id === '100112' ? 'T1565.002 (Transmitted Data Manipulation)' :
           'See Wazuh for MITRE mapping'}
        </strong></span>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Tab: Detection Rules
// ---------------------------------------------------------------------------
function DetectionRulesTab({ token }: { token: string }) {
  const { data, loading, error } = useApi(
    () => api.getDetectionCatalog(token),
    [token],
  )
  const rules = data?.rules ?? []
  const [expanded, setExpanded] = useState<string | null>(null)

  return (
    <div>
      {error && <div className="alert alert-error mb-16">{error}</div>}

      {loading && (
        <div style={{ display: 'flex', justifyContent: 'center', padding: 32 }}>
          <span className="spinner" />
        </div>
      )}

      {!loading && rules.length === 0 && !error && (
        <div className="alert mb-16" style={{ color: 'var(--text-muted)' }}>No rules found.</div>
      )}

      {rules.length > 0 && (
        <div style={{ overflowX: 'auto', border: '1px solid var(--border)', borderRadius: 'var(--radius)' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
            <thead>
              <tr style={{ borderBottom: '1px solid var(--border)', background: 'var(--bg-hover)' }}>
                {['', 'Rule ID', 'Lvl', 'Severity', 'Description', 'Event type', 'Match'].map(h => (
                  <th key={h} style={{ textAlign: 'left', padding: '6px 8px', color: 'var(--text-muted)', fontWeight: 600, fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.06em' }}>
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rules.map((r: DetectionRule) => (
                <>
                  <tr
                    key={`row-${r.rule_id}`}
                    onClick={() => setExpanded(expanded === r.rule_id ? null : r.rule_id)}
                    onKeyDown={e => (e.key === 'Enter' || e.key === ' ') && setExpanded(expanded === r.rule_id ? null : r.rule_id)}
                    tabIndex={0}
                    style={{ borderBottom: expanded === r.rule_id ? 'none' : '1px solid var(--border)', cursor: 'pointer', background: expanded === r.rule_id ? 'var(--bg-hover)' : undefined }}
                    aria-expanded={expanded === r.rule_id}
                  >
                    <td style={{ padding: '6px 8px', color: 'var(--text-muted)', fontSize: 10 }}>{expanded === r.rule_id ? '▾' : '▸'}</td>
                    <td style={{ padding: '6px 8px', fontFamily: 'monospace', fontSize: 12 }}>{r.rule_id}</td>
                    <td style={{ padding: '6px 8px', fontFamily: 'monospace', fontSize: 12, color: 'var(--text-muted)' }}>{r.level}</td>
                    <td style={{ padding: '6px 8px' }}><SeverityBadge severity={r.severity} /></td>
                    <td style={{ padding: '6px 8px', maxWidth: 280 }}>{r.plain_english}</td>
                    <td style={{ padding: '6px 8px', fontFamily: 'monospace', fontSize: 11, color: 'var(--text-muted)', maxWidth: 220 }}>{r.event_type}</td>
                    <td style={{ padding: '6px 8px', fontSize: 11, color: 'var(--text-muted)' }}>{r.match_type}</td>
                  </tr>
                  {expanded === r.rule_id && (
                    <tr key={`detail-${r.rule_id}`} style={{ borderBottom: '1px solid var(--border)' }}>
                      <td colSpan={7} style={{ padding: 0 }}>
                        <RuleDetailPanel r={r} />
                      </td>
                    </tr>
                  )}
                </>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {data && (
        <div style={{ marginTop: 12, fontSize: 12, color: 'var(--text-muted)' }}>
          {data.total} rules total · click any row to see why it matters and what to do
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Tab: VAPT Report
// ---------------------------------------------------------------------------
function VaptReportTab({ token }: { token: string }) {
  const { data, loading, error } = useApi(
    () => api.getVaptReport(token),
    [token],
  )

  if (loading) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', padding: 32 }}>
        <span className="spinner" />
      </div>
    )
  }

  if (error) {
    return <div className="alert alert-error mb-16">{error}</div>
  }

  if (!data?.available) {
    return (
      <div className="alert alert-warn mb-16">
        {data?.message ?? 'VAPT summary not available. Run scripts/build_vapt_summary.py.'}
      </div>
    )
  }

  const s = data.summary
  const passRate = s ? Math.round((s.pass / s.total) * 100) : 0
  const passColor = passRate >= 90 ? 'var(--accent-cyan)' : passRate >= 70 ? 'var(--accent-amber)' : 'var(--accent-red)'

  return (
    <div>
      {/* Summary strip */}
      <div style={{ display: 'flex', gap: 16, marginBottom: 20, flexWrap: 'wrap' }}>
        {[
          { label: 'Total tests', value: s?.total ?? '—' },
          { label: 'Pass', value: s?.pass ?? '—', color: 'var(--accent-cyan)' },
          { label: 'Fail', value: s?.fail ?? '—', color: s?.fail ? 'var(--accent-red)' : undefined },
          { label: 'Pass rate', value: s ? `${passRate}%` : '—', color: passColor },
        ].map(({ label, value, color }) => (
          <div key={label} style={{ padding: '10px 16px', background: 'var(--surface)', borderRadius: 6, minWidth: 100 }}>
            <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 4 }}>{label}</div>
            <div style={{ fontSize: 20, fontWeight: 700, color: color ?? 'var(--text)' }}>{String(value)}</div>
          </div>
        ))}
        <div style={{ padding: '10px 16px', background: 'var(--surface)', borderRadius: 6, minWidth: 140 }}>
          <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 4 }}>Run ID</div>
          <div style={{ fontSize: 13, fontFamily: 'monospace', color: 'var(--text)' }}>{data.run ?? '—'}</div>
        </div>
      </div>

      {/* Category breakdown */}
      {data.categories && data.categories.length > 0 && (
        <div style={{ marginBottom: 20 }}>
          <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 8 }}>Category breakdown</div>
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
              <thead>
                <tr style={{ borderBottom: '1px solid var(--border)' }}>
                  {['Category', 'Total', 'Pass', 'Fail'].map(h => (
                    <th key={h} style={{ textAlign: 'left', padding: '6px 8px', color: 'var(--text-muted)', fontWeight: 500, fontSize: 11 }}>
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {(data.categories as VaptCategoryCount[]).map(c => (
                  <tr key={c.category} style={{ borderBottom: '1px solid var(--border)' }}>
                    <td style={{ padding: '6px 8px', fontFamily: 'monospace', fontSize: 12 }}>{c.category}</td>
                    <td style={{ padding: '6px 8px' }}>{c.total}</td>
                    <td style={{ padding: '6px 8px', color: 'var(--accent-cyan)' }}>{c.pass}</td>
                    <td style={{ padding: '6px 8px', color: c.fail ? 'var(--accent-red)' : 'var(--text-muted)' }}>{c.fail}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Findings */}
      {data.findings && data.findings.length > 0 && (
        <div>
          <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 8 }}>
            Open findings ({data.findings.length})
          </div>
          {(data.findings as VaptFinding[]).map(f => (
            <div
              key={f.id}
              style={{ padding: '12px 14px', background: 'var(--surface)', borderRadius: 6, marginBottom: 8, borderLeft: '3px solid var(--accent-red)' }}
            >
              <div style={{ display: 'flex', gap: 10, alignItems: 'center', marginBottom: 4 }}>
                <span style={{ fontFamily: 'monospace', fontSize: 12, color: 'var(--text-muted)' }}>{f.id}</span>
                <SeverityBadge severity={f.severity} />
                <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>{f.owasp}</span>
              </div>
              <div style={{ fontWeight: 600, marginBottom: 4 }}>{f.title}</div>
              {f.actual && (
                <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>Actual: {f.actual}</div>
              )}
            </div>
          ))}
        </div>
      )}

      {data.findings && data.findings.length === 0 && (
        <div className="alert mb-16" style={{ color: 'var(--accent-cyan)' }}>
          No open findings — all tests passed.
        </div>
      )}

      <div style={{ marginTop: 16, fontSize: 12, color: 'var(--text-muted)' }}>
        Generated {data.generated_at ? fmt(data.generated_at) : '—'} · Run against {data.target ?? '—'}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Security Center — 3 tabs
// ---------------------------------------------------------------------------
type Tab = 'live' | 'rules' | 'vapt'

export default function SecurityEvents({ token }: Props) {
  const [tab, setTab] = useState<Tab>('live')

  const tabStyle = (active: boolean): React.CSSProperties => ({
    padding: '8px 16px 7px',
    fontSize: 13,
    fontWeight: active ? 600 : 400,
    color: active ? 'var(--text)' : 'var(--text-muted)',
    borderBottom: active ? '2px solid var(--accent-cyan)' : '2px solid transparent',
    cursor: 'pointer',
    background: 'none',
    border: 'none',
  })

  return (
    <div>
      <div className="section-header">
        <div>
          <div className="section-title">Security Center</div>
          <div className="section-desc">
            Every security event the gateway fires, the rules that produced it, and the latest VAPT findings — all in one place.
          </div>
        </div>
      </div>

      {/* Tab bar */}
      <div style={{ display: 'flex', gap: 0, borderBottom: '1px solid var(--border)', marginBottom: 20 }}>
        <button style={tabStyle(tab === 'live')} onClick={() => setTab('live')}>Live Events</button>
        <button style={tabStyle(tab === 'rules')} onClick={() => setTab('rules')}>Detection Rules</button>
        <button style={tabStyle(tab === 'vapt')} onClick={() => setTab('vapt')}>VAPT Report</button>
      </div>

      {tab === 'live'  && <LiveEventsTab token={token} />}
      {tab === 'rules' && <DetectionRulesTab token={token} />}
      {tab === 'vapt'  && <VaptReportTab token={token} />}
    </div>
  )
}

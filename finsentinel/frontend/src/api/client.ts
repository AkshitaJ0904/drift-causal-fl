/**
 * FinSentinel operator API client.
 *
 * All requests require the operator bearer token.  The token is stored only in
 * memory (never in localStorage or a cookie) and must be provided at login time.
 *
 * Base URL: /api/v1  (proxied to the backend by Vite in dev mode)
 */

const BASE = '/api/v1'

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

// Called when any authenticated request receives 401 — allows App.tsx to
// trigger automatic logout so the user is returned to the login screen
// rather than seeing unrecoverable error messages on every page.
let _onUnauthenticated: (() => void) | null = null
export function setUnauthenticatedHandler(fn: () => void): void {
  _onUnauthenticated = fn
}
export function clearUnauthenticatedHandler(): void {
  _onUnauthenticated = null
}

async function request<T>(
  method: string,
  path: string,
  token: string,
  body?: unknown,
): Promise<T> {
  const headers: Record<string, string> = {
    Authorization: `Bearer ${token}`,
    'Content-Type': 'application/json',
  }

  const res = await fetch(`${BASE}${path}`, {
    method,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  })

  if (!res.ok) {
    if (res.status === 401) {
      _onUnauthenticated?.()
    }
    let detail = `HTTP ${res.status}`
    try {
      const json = await res.json()
      if (typeof json.detail === 'string') detail = json.detail
    } catch {
      // keep the status code message
    }
    throw new ApiError(res.status, detail)
  }

  return res.json() as Promise<T>
}

// ---------------------------------------------------------------------------
// Types matching backend response shapes
// ---------------------------------------------------------------------------

export interface DashboardOutbox {
  pending_count: number | null
  dead_letter_count: number | null
  error: string | null
  alert: boolean
}

export interface DashboardRegistries {
  trusted_key_count: number | null
  model_schema_count: number | null
  error: string | null
}

export interface DashboardApprovals {
  pending_count: number | null
  error: string | null
}

export interface DashboardWorker {
  enabled: boolean
  webhook_configured: boolean
}

export interface DashboardConfig {
  concurrency_cap: number | null
  rate_limit_rpm: number | null
  body_read_timeout_seconds: number | null
  operator_token_configured: boolean
}

export interface DetectionThresholds {
  max_weight_l2_norm: number | null
  max_update_l2_norm: number | null
  max_weight_abs_mean: number | null
  max_weight_std: number | null
  max_weight_zero_fraction: number | null
  min_weight_zero_fraction: number | null
}

export interface DashboardDetection {
  thresholds: DetectionThresholds | null
  error: string | null
  high_risk_action: string
}

export interface DashboardResponse {
  outbox: DashboardOutbox
  registries: DashboardRegistries
  approvals: DashboardApprovals
  worker: DashboardWorker
  config: DashboardConfig
  detection?: DashboardDetection
}

export interface SecurityEvent {
  timestamp?: string
  event_type?: string
  client_id?: string
  update_id?: string
  service?: string
  event_id?: number | null
  reason?: string
  rule_id?: string | null
  level?: number | null
  severity?: string
  plain_english?: string
}

export interface SecurityEventsResponse {
  events: SecurityEvent[]
  total: number
  message: string
}

export interface DetectionRule {
  event_type: string
  rule_id: string
  level: number
  severity: string
  plain_english: string
  match_type: string
  why_it_matters?: string
  what_to_do?: string
  example?: string
}

export interface DetectionCatalogResponse {
  rules: DetectionRule[]
  total: number
}

export interface VaptFinding {
  id: string
  title: string
  severity: string
  owasp: string
  description: string
  actual?: string
}

export interface VaptCategoryCount {
  category: string
  total: number
  pass: number
  fail: number
}

export interface VaptSummary {
  total: number
  pass: number
  fail: number
}

export interface VaptReportResponse {
  available: boolean
  message?: string
  run?: string
  timestamp?: string
  target?: string
  summary?: VaptSummary
  categories?: VaptCategoryCount[]
  findings?: VaptFinding[]
  generated_at?: string
}

export interface ApprovalRecord {
  update_id: string
  client_id: string
  model_version: string
  round_number: number
  sample_count: number | null
  payload_sha256: string | null
  status: string
  risk_score: number | null
  risk_severity: string | null
  suspicious: boolean | null
  anomaly_reasons: string[]
  audit_status: string | null
  reason: string
}

export interface ApprovalListResponse {
  pending: ApprovalRecord[]
}

export interface HealthResponse {
  status: string
  service?: string
  version?: string
}

export interface HealthAlertItem {
  type: string
  severity: 'warning' | 'critical'
  count: number
  message: string
}

export interface HealthAlertsResponse {
  status: 'ok' | 'degraded'
  alerts: HealthAlertItem[]
}

export interface HealthMetricsOutbox {
  pending_count: number | null
  dead_letter_count: number | null
  error: string | null
}

export interface HealthMetricsIngestion {
  concurrency_cap: number | null
  concurrency_cap_scope: string | null
}

export interface HealthMetricsRateLimit {
  requests_per_minute: number | null
  scope: string | null
  note: string
}

export interface HealthMetricsResponse {
  outbox: HealthMetricsOutbox
  ingestion: HealthMetricsIngestion
  rate_limit: HealthMetricsRateLimit
}

// ---------------------------------------------------------------------------
// API functions
// ---------------------------------------------------------------------------

export const api = {
  getDashboard: (token: string) =>
    request<DashboardResponse>('GET', '/operator/dashboard', token),

  getHealth: (token: string) =>
    request<HealthResponse>('GET', '/health', token),

  getPendingApprovals: (token: string) =>
    request<ApprovalListResponse>('GET', '/updates/pending', token),

  approveUpdate: (token: string, clientId: string, updateId: string, reason: string) =>
    request<ApprovalRecord>('POST', `/updates/${clientId}/${updateId}/approve`, token, { reason }),

  rejectUpdate: (token: string, clientId: string, updateId: string, reason: string) =>
    request<ApprovalRecord>('POST', `/updates/${clientId}/${updateId}/reject`, token, { reason }),

  quarantineUpdate: (token: string, clientId: string, updateId: string, reason: string) =>
    request<ApprovalRecord>('POST', `/updates/${clientId}/${updateId}/quarantine`, token, { reason }),

  getHealthAlerts: () =>
    fetch(`${BASE}/health/alerts`).then(async (res) => {
      if (!res.ok) throw new ApiError(res.status, `HTTP ${res.status}`)
      return res.json() as Promise<HealthAlertsResponse>
    }),

  getHealthMetrics: (token: string) =>
    request<HealthMetricsResponse>('GET', '/health/metrics', token),

  getSecurityEvents: (token: string, limit = 50) =>
    request<SecurityEventsResponse>('GET', `/security-events?limit=${limit}`, token),

  getDetectionCatalog: (token: string) =>
    request<DetectionCatalogResponse>('GET', '/security-events/catalog', token),

  getVaptReport: (token: string) =>
    request<VaptReportResponse>('GET', '/vapt-report', token),
}

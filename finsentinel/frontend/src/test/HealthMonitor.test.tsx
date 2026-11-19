import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import HealthMonitor from '../pages/HealthMonitor'
import { useApi } from '../hooks/useApi'
import type {
  HealthResponse,
  HealthAlertsResponse,
  HealthMetricsResponse,
} from '../api/client'

vi.mock('../hooks/useApi')
const mockedUseApi = vi.mocked(useApi)

const livenessOk: HealthResponse = { status: 'ok', service: 'finsentinel' }
const alertsOk: HealthAlertsResponse = { status: 'ok', alerts: [] }
const metricsOk: HealthMetricsResponse = {
  outbox: { pending_count: 0, dead_letter_count: 0, error: null },
  ingestion: { concurrency_cap: 8, concurrency_cap_scope: 'global' },
  rate_limit: { requests_per_minute: 60, scope: 'global', note: '' },
}

type ApiResult = { data: unknown; loading: boolean; error: string | null; refresh: () => void }

function makeResult<T>(data: T, overrides: Partial<ApiResult> = {}): ApiResult {
  return { data, loading: false, error: null, refresh: vi.fn(), ...overrides }
}

// RTL v16 wraps in React 18 StrictMode, which invokes the component function
// twice per mount. With 3 useApi calls per render, we need the mock to cycle
// through the same values so the second (strict-mode) render doesn't get undefined.
function setupHealthMocks(
  liveness: ApiResult = makeResult(livenessOk),
  alerts: ApiResult = makeResult(alertsOk),
  metrics: ApiResult = makeResult(metricsOk),
) {
  const cycle = [liveness, alerts, metrics]
  let i = 0
  mockedUseApi.mockImplementation(() => cycle[i++ % 3] as ReturnType<typeof useApi>)
}

describe('HealthMonitor', () => {
  beforeEach(() => vi.clearAllMocks())

  it('renders section title', () => {
    setupHealthMocks()
    render(<HealthMonitor token="test-token" />)
    expect(screen.getByText('Health Monitor')).toBeInTheDocument()
  })

  it('shows service status badge as ok', () => {
    setupHealthMocks()
    render(<HealthMonitor token="test-token" />)
    // "ok" appears as the liveness badge; getAllByText handles multiple matches
    expect(screen.getAllByText('ok').length).toBeGreaterThanOrEqual(1)
  })

  it('shows service name from liveness data', () => {
    setupHealthMocks()
    render(<HealthMonitor token="test-token" />)
    expect(screen.getByText('finsentinel')).toBeInTheDocument()
  })

  it('shows all-clear message when healthy', () => {
    setupHealthMocks()
    render(<HealthMonitor token="test-token" />)
    expect(
      screen.getByText('All monitored components are healthy.'),
    ).toBeInTheDocument()
  })

  it('shows liveness error alert', () => {
    setupHealthMocks(makeResult<HealthResponse | null>(null, { error: 'HTTP 503' }))
    render(<HealthMonitor token="test-token" />)
    expect(screen.getByText(/Liveness: HTTP 503/)).toBeInTheDocument()
  })

  it('shows degraded alert state when alerts API reports degraded', () => {
    const degradedAlerts: HealthAlertsResponse = {
      status: 'degraded',
      alerts: [
        { type: 'dead_letter_overflow', severity: 'critical', count: 3, message: 'Dead letter queue full' },
      ],
    }
    setupHealthMocks(
      makeResult(livenessOk),
      makeResult(degradedAlerts),
    )
    render(<HealthMonitor token="test-token" />)
    expect(screen.getByText('degraded')).toBeInTheDocument()
    expect(screen.getByText(/Dead letter queue full/)).toBeInTheDocument()
  })

  it('shows concurrency cap from metrics', () => {
    setupHealthMocks()
    render(<HealthMonitor token="test-token" />)
    expect(screen.getByText('8')).toBeInTheDocument()
    // "global" appears for both concurrency_cap_scope and rate_limit scope
    expect(screen.getAllByText('global').length).toBeGreaterThanOrEqual(1)
  })

  it('shows rate limit from metrics', () => {
    setupHealthMocks()
    render(<HealthMonitor token="test-token" />)
    expect(screen.getByText('60')).toBeInTheDocument()
  })

  it('shows metrics unavailable warning when metrics error', () => {
    setupHealthMocks(
      makeResult(livenessOk),
      makeResult(alertsOk),
      makeResult<HealthMetricsResponse | null>(null, { error: 'HTTP 403' }),
    )
    render(<HealthMonitor token="test-token" />)
    expect(screen.getByText(/Metrics unavailable/)).toBeInTheDocument()
  })

  it('shows health endpoint reference table', () => {
    setupHealthMocks()
    render(<HealthMonitor token="test-token" />)
    expect(screen.getByText('/api/v1/health')).toBeInTheDocument()
    expect(screen.getByText('/api/v1/health/alerts')).toBeInTheDocument()
    expect(screen.getByText('/api/v1/health/metrics')).toBeInTheDocument()
  })

  it('refresh button is present and clickable', async () => {
    setupHealthMocks()
    render(<HealthMonitor token="test-token" />)
    const btn = screen.getByRole('button', { name: /Refresh/ })
    expect(btn).toBeInTheDocument()
    await userEvent.click(btn)
  })

  it('shows alert badge count when alerts present', () => {
    const degradedAlerts: HealthAlertsResponse = {
      status: 'degraded',
      alerts: [
        { type: 'dead_letter_overflow', severity: 'critical', count: 2, message: 'DL overflow' },
        { type: 'worker_down', severity: 'warning', count: 1, message: 'Worker down' },
      ],
    }
    setupHealthMocks(
      makeResult(livenessOk),
      makeResult(degradedAlerts),
    )
    render(<HealthMonitor token="test-token" />)
    expect(screen.getByText('2 alert(s)')).toBeInTheDocument()
  })
})

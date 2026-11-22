import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import DetectionConfig from '../pages/DetectionConfig'
import { useApi } from '../hooks/useApi'
import type { DashboardResponse } from '../api/client'

vi.mock('../hooks/useApi')
const mockedUseApi = vi.mocked(useApi)

const baseDashboard: DashboardResponse = {
  outbox: { pending_count: 0, dead_letter_count: 0, error: null, alert: false },
  registries: { trusted_key_count: 1, model_schema_count: 1, error: null },
  approvals: { pending_count: 0, error: null },
  worker: { enabled: true, webhook_configured: true },
  config: {
    concurrency_cap: null,
    rate_limit_rpm: null,
    body_read_timeout_seconds: null,
    operator_token_configured: true,
  },
  detection: {
    thresholds: {
      max_weight_l2_norm: 10.5,
      max_update_l2_norm: 5.0,
      max_weight_abs_mean: null,
      max_weight_std: null,
      max_weight_zero_fraction: null,
      min_weight_zero_fraction: null,
    },
    error: null,
    high_risk_action: 'quarantined',
  },
}

function makeUseApi(overrides: Partial<ReturnType<typeof useApi>> = {}) {
  return { data: null, loading: false, error: null, refresh: vi.fn(), ...overrides }
}

describe('DetectionConfig', () => {
  beforeEach(() => vi.clearAllMocks())

  it('renders section title', () => {
    mockedUseApi.mockReturnValue(makeUseApi({ data: baseDashboard }))
    render(<DetectionConfig token="test-token" />)
    expect(screen.getByText('Detection Configuration')).toBeInTheDocument()
  })

  it('shows configured threshold values', () => {
    mockedUseApi.mockReturnValue(makeUseApi({ data: baseDashboard }))
    render(<DetectionConfig token="test-token" />)
    expect(screen.getByText('10.5')).toBeInTheDocument()
    expect(screen.getByText('5')).toBeInTheDocument()
  })

  it('shows "not set" for unconfigured thresholds', () => {
    mockedUseApi.mockReturnValue(makeUseApi({ data: baseDashboard }))
    render(<DetectionConfig token="test-token" />)
    const notSetElements = screen.getAllByText('not set')
    expect(notSetElements.length).toBeGreaterThan(0)
  })

  it('shows all 6 threshold environment variable names', () => {
    mockedUseApi.mockReturnValue(makeUseApi({ data: baseDashboard }))
    render(<DetectionConfig token="test-token" />)
    expect(screen.getByText('FINSENTINEL_MAX_WEIGHT_L2_NORM')).toBeInTheDocument()
    expect(screen.getByText('FINSENTINEL_MAX_UPDATE_L2_NORM')).toBeInTheDocument()
    expect(screen.getByText('FINSENTINEL_MAX_WEIGHT_STD')).toBeInTheDocument()
    expect(screen.getByText('FINSENTINEL_MIN_WEIGHT_ZERO_FRACTION')).toBeInTheDocument()
  })

  it('shows high_risk_action badge when configured', () => {
    mockedUseApi.mockReturnValue(makeUseApi({ data: baseDashboard }))
    render(<DetectionConfig token="test-token" />)
    expect(screen.getByText('active: quarantined')).toBeInTheDocument()
  })

  it('shows loading spinners when loading', () => {
    mockedUseApi.mockReturnValue(makeUseApi({ loading: true }))
    render(<DetectionConfig token="test-token" />)
    // Threshold values should not be visible
    expect(screen.queryByText('10.5')).not.toBeInTheDocument()
  })

  it('shows detection error warning when detection.error is set', () => {
    const data: DashboardResponse = {
      ...baseDashboard,
      detection: {
        thresholds: null,
        error: 'Detection module unavailable',
        high_risk_action: 'quarantined',
      },
    }
    mockedUseApi.mockReturnValue(makeUseApi({ data }))
    render(<DetectionConfig token="test-token" />)
    expect(screen.getByText(/Detection config unavailable/)).toBeInTheDocument()
  })

  it('shows API error alert on fetch failure', () => {
    mockedUseApi.mockReturnValue(makeUseApi({ error: 'HTTP 500' }))
    render(<DetectionConfig token="test-token" />)
    expect(screen.getByText('HTTP 500')).toBeInTheDocument()
  })

  it('shows isolation forest section', () => {
    mockedUseApi.mockReturnValue(makeUseApi({ data: baseDashboard }))
    render(<DetectionConfig token="test-token" />)
    expect(screen.getAllByText(/Isolation Forest/).length).toBeGreaterThan(0)
  })

  it('shows supplementary detection disclaimer', () => {
    mockedUseApi.mockReturnValue(makeUseApi({ data: baseDashboard }))
    render(<DetectionConfig token="test-token" />)
    expect(
      screen.getByText(/Detection is a supplementary statistical layer/),
    ).toBeInTheDocument()
  })

  it('shows refresh button', () => {
    mockedUseApi.mockReturnValue(makeUseApi({ data: baseDashboard }))
    render(<DetectionConfig token="test-token" />)
    expect(screen.getByRole('button', { name: /Refresh/ })).toBeInTheDocument()
  })
})

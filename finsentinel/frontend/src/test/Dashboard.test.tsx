import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import Dashboard from '../pages/Dashboard'
import { useApi } from '../hooks/useApi'
import type { DashboardResponse } from '../api/client'

vi.mock('../hooks/useApi')
const mockedUseApi = vi.mocked(useApi)

const baseDashboard: DashboardResponse = {
  outbox: { pending_count: 0, dead_letter_count: 0, error: null, alert: false },
  registries: { trusted_key_count: 3, model_schema_count: 2, error: null },
  approvals: { pending_count: 0, error: null },
  worker: { enabled: true, webhook_configured: true },
  config: {
    concurrency_cap: 10,
    rate_limit_rpm: 100,
    body_read_timeout_seconds: 30,
    operator_token_configured: true,
  },
}

function makeUseApi(overrides: Partial<ReturnType<typeof useApi>> = {}) {
  return {
    data: null,
    loading: false,
    error: null,
    refresh: vi.fn(),
    ...overrides,
  }
}

describe('Dashboard', () => {
  beforeEach(() => vi.clearAllMocks())

  it('shows loading spinner while loading', () => {
    mockedUseApi.mockReturnValue(makeUseApi({ loading: true }))
    render(<Dashboard token="test-token" />)
    expect(screen.getByText('Loading dashboard…')).toBeInTheDocument()
  })

  it('shows error with retry button on API failure', () => {
    const refresh = vi.fn()
    mockedUseApi.mockReturnValue(makeUseApi({ error: 'HTTP 500', refresh }))
    render(<Dashboard token="test-token" />)
    expect(screen.getByText('HTTP 500')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument()
  })

  it('renders KPI cards with dashboard data', () => {
    mockedUseApi.mockReturnValue(makeUseApi({ data: baseDashboard }))
    render(<Dashboard token="test-token" />)
    expect(screen.getByText('Pending Approvals')).toBeInTheDocument()
    expect(screen.getByText('Trusted Keys')).toBeInTheDocument()
    expect(screen.getByText('Model Schemas')).toBeInTheDocument()
  })

  it('shows pending approval count from data', () => {
    const data: DashboardResponse = {
      ...baseDashboard,
      approvals: { pending_count: 5, error: null },
    }
    mockedUseApi.mockReturnValue(makeUseApi({ data }))
    render(<Dashboard token="test-token" />)
    expect(screen.getAllByText('5').length).toBeGreaterThan(0)
  })

  it('shows dead-letter alert banner when outbox.alert is true', () => {
    const data: DashboardResponse = {
      ...baseDashboard,
      outbox: { pending_count: 0, dead_letter_count: 2, error: null, alert: true },
    }
    mockedUseApi.mockReturnValue(makeUseApi({ data }))
    render(<Dashboard token="test-token" />)
    expect(screen.getByText(/Dead-letter alert/)).toBeInTheDocument()
  })

  it('shows worker enabled status', () => {
    mockedUseApi.mockReturnValue(makeUseApi({ data: baseDashboard }))
    render(<Dashboard token="test-token" />)
    expect(screen.getByText('running')).toBeInTheDocument()
  })

  it('shows worker disabled when worker.enabled is false', () => {
    const data: DashboardResponse = {
      ...baseDashboard,
      worker: { enabled: false, webhook_configured: false },
    }
    mockedUseApi.mockReturnValue(makeUseApi({ data }))
    render(<Dashboard token="test-token" />)
    // "disabled" appears in badge and status row; verify at least one instance
    expect(screen.getAllByText('disabled').length).toBeGreaterThanOrEqual(1)
  })

  it('shows operator token configured badge', () => {
    mockedUseApi.mockReturnValue(makeUseApi({ data: baseDashboard }))
    render(<Dashboard token="test-token" />)
    expect(screen.getByText('token set')).toBeInTheDocument()
  })

  it('shows refresh button', () => {
    mockedUseApi.mockReturnValue(makeUseApi({ data: baseDashboard }))
    render(<Dashboard token="test-token" />)
    expect(screen.getByRole('button', { name: /Refresh/ })).toBeInTheDocument()
  })
})

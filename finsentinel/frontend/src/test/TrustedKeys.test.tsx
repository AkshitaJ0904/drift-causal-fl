import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import TrustedKeys from '../pages/TrustedKeys'
import { useApi } from '../hooks/useApi'
import type { DashboardResponse } from '../api/client'

vi.mock('../hooks/useApi')
const mockedUseApi = vi.mocked(useApi)

const baseDashboard: DashboardResponse = {
  outbox: { pending_count: 0, dead_letter_count: 0, error: null, alert: false },
  registries: { trusted_key_count: 4, model_schema_count: 2, error: null },
  approvals: { pending_count: 0, error: null },
  worker: { enabled: true, webhook_configured: true },
  config: {
    concurrency_cap: null,
    rate_limit_rpm: null,
    body_read_timeout_seconds: null,
    operator_token_configured: true,
  },
}

function makeUseApi(overrides: Partial<ReturnType<typeof useApi>> = {}) {
  return { data: null, loading: false, error: null, refresh: vi.fn(), ...overrides }
}

describe('TrustedKeys', () => {
  beforeEach(() => vi.clearAllMocks())

  it('shows loading spinner while loading (count not visible)', () => {
    mockedUseApi.mockReturnValue(makeUseApi({ loading: true }))
    render(<TrustedKeys token="test-token" />)
    // Section title still renders, but the count is replaced by a spinner
    expect(screen.getByText('Trusted Key Registry')).toBeInTheDocument()
    expect(screen.queryByText('4')).not.toBeInTheDocument()
  })

  it('renders section title', () => {
    mockedUseApi.mockReturnValue(makeUseApi({ data: baseDashboard }))
    render(<TrustedKeys token="test-token" />)
    expect(screen.getByText('Trusted Key Registry')).toBeInTheDocument()
  })

  it('shows registered key count from dashboard data', () => {
    mockedUseApi.mockReturnValue(makeUseApi({ data: baseDashboard }))
    render(<TrustedKeys token="test-token" />)
    expect(screen.getByText('4')).toBeInTheDocument()
  })

  it('shows ? when count is null', () => {
    const data: DashboardResponse = {
      ...baseDashboard,
      registries: { ...baseDashboard.registries, trusted_key_count: null },
    }
    mockedUseApi.mockReturnValue(makeUseApi({ data }))
    render(<TrustedKeys token="test-token" />)
    expect(screen.getByText('?')).toBeInTheDocument()
  })

  it('shows CLI-only badge', () => {
    mockedUseApi.mockReturnValue(makeUseApi({ data: baseDashboard }))
    render(<TrustedKeys token="test-token" />)
    expect(screen.getByText('CLI only')).toBeInTheDocument()
  })

  it('shows register and revoke operations in table', () => {
    mockedUseApi.mockReturnValue(makeUseApi({ data: baseDashboard }))
    render(<TrustedKeys token="test-token" />)
    expect(screen.getByText('Register key')).toBeInTheDocument()
    expect(screen.getByText('Revoke key')).toBeInTheDocument()
  })

  it('shows error alert on API failure', () => {
    mockedUseApi.mockReturnValue(makeUseApi({ error: 'HTTP 500' }))
    render(<TrustedKeys token="test-token" />)
    expect(screen.getByText('HTTP 500')).toBeInTheDocument()
  })

  it('shows refresh button', () => {
    mockedUseApi.mockReturnValue(makeUseApi({ data: baseDashboard }))
    render(<TrustedKeys token="test-token" />)
    expect(screen.getByRole('button', { name: /Refresh/ })).toBeInTheDocument()
  })
})

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import ModelSchemas from '../pages/ModelSchemas'
import { useApi } from '../hooks/useApi'
import type { DashboardResponse } from '../api/client'

vi.mock('../hooks/useApi')
const mockedUseApi = vi.mocked(useApi)

const baseDashboard: DashboardResponse = {
  outbox: { pending_count: 0, dead_letter_count: 0, error: null, alert: false },
  registries: { trusted_key_count: 3, model_schema_count: 7, error: null },
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

describe('ModelSchemas', () => {
  beforeEach(() => vi.clearAllMocks())

  it('renders section title', () => {
    mockedUseApi.mockReturnValue(makeUseApi({ data: baseDashboard }))
    render(<ModelSchemas token="test-token" />)
    expect(screen.getByText('Model Schema Registry')).toBeInTheDocument()
  })

  it('shows registered schema count from dashboard data', () => {
    mockedUseApi.mockReturnValue(makeUseApi({ data: baseDashboard }))
    render(<ModelSchemas token="test-token" />)
    expect(screen.getByText('7')).toBeInTheDocument()
  })

  it('shows ? when count is null', () => {
    const data: DashboardResponse = {
      ...baseDashboard,
      registries: { ...baseDashboard.registries, model_schema_count: null },
    }
    mockedUseApi.mockReturnValue(makeUseApi({ data }))
    render(<ModelSchemas token="test-token" />)
    expect(screen.getByText('?')).toBeInTheDocument()
  })

  it('shows loading state (no count visible)', () => {
    mockedUseApi.mockReturnValue(makeUseApi({ loading: true }))
    render(<ModelSchemas token="test-token" />)
    expect(screen.queryByText('7')).not.toBeInTheDocument()
  })

  it('shows CLI-only badge', () => {
    mockedUseApi.mockReturnValue(makeUseApi({ data: baseDashboard }))
    render(<ModelSchemas token="test-token" />)
    expect(screen.getByText('CLI only')).toBeInTheDocument()
  })

  it('shows register/update schema operation in table', () => {
    mockedUseApi.mockReturnValue(makeUseApi({ data: baseDashboard }))
    render(<ModelSchemas token="test-token" />)
    expect(screen.getByText('Register / update schema')).toBeInTheDocument()
  })

  it('shows error alert on API failure', () => {
    mockedUseApi.mockReturnValue(makeUseApi({ error: 'HTTP 503' }))
    render(<ModelSchemas token="test-token" />)
    expect(screen.getByText('HTTP 503')).toBeInTheDocument()
  })

  it('shows refresh button', () => {
    mockedUseApi.mockReturnValue(makeUseApi({ data: baseDashboard }))
    render(<ModelSchemas token="test-token" />)
    expect(screen.getByRole('button', { name: /Refresh/ })).toBeInTheDocument()
  })
})

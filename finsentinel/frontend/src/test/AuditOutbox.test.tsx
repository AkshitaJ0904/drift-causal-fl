import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import AuditOutbox from '../pages/AuditOutbox'
import { useApi } from '../hooks/useApi'
import type { DashboardResponse } from '../api/client'

vi.mock('../hooks/useApi')
const mockedUseApi = vi.mocked(useApi)

const baseDashboard: DashboardResponse = {
  outbox: { pending_count: 3, dead_letter_count: 0, error: null, alert: false },
  registries: { trusted_key_count: 1, model_schema_count: 1, error: null },
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

describe('AuditOutbox', () => {
  beforeEach(() => vi.clearAllMocks())

  it('renders section title', () => {
    mockedUseApi.mockReturnValue(makeUseApi({ data: baseDashboard }))
    render(<AuditOutbox token="test-token" />)
    expect(screen.getByText('Audit Outbox')).toBeInTheDocument()
  })

  it('shows pending event count', () => {
    mockedUseApi.mockReturnValue(makeUseApi({ data: baseDashboard }))
    render(<AuditOutbox token="test-token" />)
    expect(screen.getByText('3')).toBeInTheDocument()
  })

  it('shows dead-letter count', () => {
    mockedUseApi.mockReturnValue(makeUseApi({ data: baseDashboard }))
    render(<AuditOutbox token="test-token" />)
    expect(screen.getAllByText('0').length).toBeGreaterThan(0)
  })

  it('shows dead-letter alert banner when outbox.alert is true', () => {
    const data: DashboardResponse = {
      ...baseDashboard,
      outbox: { pending_count: 0, dead_letter_count: 2, error: null, alert: true },
    }
    mockedUseApi.mockReturnValue(makeUseApi({ data }))
    render(<AuditOutbox token="test-token" />)
    expect(screen.getByText(/Dead-letter alert/)).toBeInTheDocument()
  })

  it('does not show dead-letter alert when outbox.alert is false', () => {
    mockedUseApi.mockReturnValue(makeUseApi({ data: baseDashboard }))
    render(<AuditOutbox token="test-token" />)
    expect(screen.queryByText(/Dead-letter alert/)).not.toBeInTheDocument()
  })

  it('shows worker enabled status', () => {
    mockedUseApi.mockReturnValue(makeUseApi({ data: baseDashboard }))
    render(<AuditOutbox token="test-token" />)
    expect(screen.getByText('running')).toBeInTheDocument()
    expect(screen.getByText('enabled')).toBeInTheDocument()
  })

  it('shows worker disabled status', () => {
    const data: DashboardResponse = {
      ...baseDashboard,
      worker: { enabled: false, webhook_configured: false },
    }
    mockedUseApi.mockReturnValue(makeUseApi({ data }))
    render(<AuditOutbox token="test-token" />)
    expect(screen.getByText('disabled', { selector: '.badge' })).toBeInTheDocument()
  })

  it('shows webhook configured status', () => {
    mockedUseApi.mockReturnValue(makeUseApi({ data: baseDashboard }))
    render(<AuditOutbox token="test-token" />)
    expect(screen.getByText('configured')).toBeInTheDocument()
  })

  it('shows dead-letter recovery CLI commands', () => {
    mockedUseApi.mockReturnValue(makeUseApi({ data: baseDashboard }))
    render(<AuditOutbox token="test-token" />)
    expect(screen.getByText(/list_dead_letter_events/)).toBeInTheDocument()
    expect(screen.getByText(/requeue_dead_letter/)).toBeInTheDocument()
  })

  it('shows error alert on API failure', () => {
    mockedUseApi.mockReturnValue(makeUseApi({ error: 'HTTP 500' }))
    render(<AuditOutbox token="test-token" />)
    expect(screen.getByText('HTTP 500')).toBeInTheDocument()
  })

  it('shows refresh button', () => {
    mockedUseApi.mockReturnValue(makeUseApi({ data: baseDashboard }))
    render(<AuditOutbox token="test-token" />)
    expect(screen.getByRole('button', { name: /Refresh/ })).toBeInTheDocument()
  })
})

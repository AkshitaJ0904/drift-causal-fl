import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import SecurityEvents from '../pages/SecurityEvents'
import { useApi } from '../hooks/useApi'
import type { SecurityEventsResponse, DetectionCatalogResponse, VaptReportResponse } from '../api/client'

vi.mock('../hooks/useApi')
const mockedUseApi = vi.mocked(useApi)

function makeUseApi(overrides: Partial<ReturnType<typeof useApi>> = {}) {
  return { data: null, loading: false, error: null, refresh: vi.fn(), ...overrides }
}

const baseEventsResponse: SecurityEventsResponse = {
  events: [
    {
      timestamp: '2026-11-21T12:47:59',
      event_type: 'security.signature_verification_failed',
      client_id: 'bank-mumbai-54d76d',
      update_id: 'abc123',
      rule_id: '100104',
      level: 12,
      severity: 'High',
      plain_english: 'Forged update blocked — invalid signature',
    },
    {
      timestamp: '2026-11-21T12:00:00',
      event_type: 'key.registered',
      client_id: 'bank-delhi-54d76d',
      rule_id: '100131',
      level: 3,
      severity: 'Low',
      plain_english: 'Trusted client signing key registered',
    },
  ],
  total: 2,
  message: '',
}

const baseCatalogResponse: DetectionCatalogResponse = {
  rules: [
    { event_type: 'key.registered', rule_id: '100131', level: 3, severity: 'Low', plain_english: 'Trusted client signing key registered', match_type: 'exact' },
    { event_type: '(wazuh-correlation)', rule_id: '100140', level: 12, severity: 'High', plain_english: 'Brute-force operator-auth detected', match_type: 'correlation' },
  ],
  total: 2,
}

const baseVaptResponse: VaptReportResponse = {
  available: true,
  run: '900be0',
  timestamp: '2026-11-21T17:43:43Z',
  target: 'http://127.0.0.1:8001',
  summary: { total: 70, pass: 66, fail: 4 },
  categories: [{ category: 'C1', total: 6, pass: 6, fail: 0 }],
  findings: [{ id: 'C2-01', title: 'No rate limit', severity: 'Medium', owasp: 'API4:2023', description: 'test', actual: '100 reqs no 429' }],
  generated_at: '2026-11-21T18:00:00Z',
}

describe('SecurityCenter — tab rendering', () => {
  beforeEach(() => vi.clearAllMocks())

  it('renders Security Center title', () => {
    mockedUseApi.mockReturnValue(makeUseApi({ data: baseEventsResponse }))
    render(<SecurityEvents token="test-token" />)
    expect(screen.getByText('Security Center')).toBeInTheDocument()
  })

  it('renders three tab buttons', () => {
    mockedUseApi.mockReturnValue(makeUseApi({ data: baseEventsResponse }))
    render(<SecurityEvents token="test-token" />)
    expect(screen.getByRole('button', { name: 'Live Events' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Detection Rules' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'VAPT Report' })).toBeInTheDocument()
  })

  it('Live Events tab shows event rows', () => {
    mockedUseApi.mockReturnValue(makeUseApi({ data: baseEventsResponse }))
    render(<SecurityEvents token="test-token" />)
    expect(screen.getByText(/Forged update blocked/)).toBeInTheDocument()
    expect(screen.getByText(/bank-mumbai-54d76d/)).toBeInTheDocument()
  })

  it('Live Events tab shows severity badges', () => {
    mockedUseApi.mockReturnValue(makeUseApi({ data: baseEventsResponse }))
    render(<SecurityEvents token="test-token" />)
    expect(screen.getByText('High')).toBeInTheDocument()
    expect(screen.getByText('Low')).toBeInTheDocument()
  })

  it('Live Events tab shows empty state when no events', () => {
    const empty: SecurityEventsResponse = { events: [], total: 0, message: '' }
    mockedUseApi.mockReturnValue(makeUseApi({ data: empty }))
    render(<SecurityEvents token="test-token" />)
    expect(screen.getByText(/No events match the current filter/)).toBeInTheDocument()
  })

  it('Live Events tab shows message when present', () => {
    const withMsg: SecurityEventsResponse = { events: [], total: 0, message: 'FINSENTINEL_SIEM_LOG is not configured.' }
    mockedUseApi.mockReturnValue(makeUseApi({ data: withMsg }))
    render(<SecurityEvents token="test-token" />)
    expect(screen.getByText(/FINSENTINEL_SIEM_LOG/)).toBeInTheDocument()
  })

  it('Live Events tab shows error on API failure', () => {
    mockedUseApi.mockReturnValue(makeUseApi({ error: 'API error 401: Unauthorized' }))
    render(<SecurityEvents token="test-token" />)
    expect(screen.getByText(/API error 401/)).toBeInTheDocument()
  })

  it('Live Events tab shows Open in Wazuh link', () => {
    mockedUseApi.mockReturnValue(makeUseApi({ data: baseEventsResponse }))
    render(<SecurityEvents token="test-token" />)
    const links = screen.getAllByRole('link', { name: /Wazuh/i })
    expect(links.length).toBeGreaterThan(0)
  })

  it('Detection Rules tab renders rule rows on click', () => {
    mockedUseApi
      .mockReturnValueOnce(makeUseApi({ data: baseEventsResponse }))  // Live Events
      .mockReturnValue(makeUseApi({ data: baseCatalogResponse }))      // Catalog
    render(<SecurityEvents token="test-token" />)
    fireEvent.click(screen.getByRole('button', { name: 'Detection Rules' }))
    expect(screen.getByText('100131')).toBeInTheDocument()
    expect(screen.getByText('100140')).toBeInTheDocument()
    expect(screen.getByText('correlation')).toBeInTheDocument()
  })

  it('Detection Rules tab shows empty state when no rules', () => {
    mockedUseApi
      .mockReturnValueOnce(makeUseApi({ data: baseEventsResponse }))
      .mockReturnValue(makeUseApi({ data: { rules: [], total: 0 } }))
    render(<SecurityEvents token="test-token" />)
    fireEvent.click(screen.getByRole('button', { name: 'Detection Rules' }))
    expect(screen.getByText(/No rules found/)).toBeInTheDocument()
  })

  it('VAPT Report tab renders summary on click', () => {
    mockedUseApi
      .mockReturnValueOnce(makeUseApi({ data: baseEventsResponse }))
      .mockReturnValue(makeUseApi({ data: baseVaptResponse }))
    render(<SecurityEvents token="test-token" />)
    fireEvent.click(screen.getByRole('button', { name: 'VAPT Report' }))
    expect(screen.getByText('70')).toBeInTheDocument()
    expect(screen.getByText('66')).toBeInTheDocument()
    expect(screen.getByText('900be0')).toBeInTheDocument()
  })

  it('VAPT Report tab shows findings', () => {
    mockedUseApi
      .mockReturnValueOnce(makeUseApi({ data: baseEventsResponse }))
      .mockReturnValue(makeUseApi({ data: baseVaptResponse }))
    render(<SecurityEvents token="test-token" />)
    fireEvent.click(screen.getByRole('button', { name: 'VAPT Report' }))
    expect(screen.getByText('No rate limit')).toBeInTheDocument()
    expect(screen.getByText('C2-01')).toBeInTheDocument()
  })

  it('VAPT Report tab shows unavailable message when not built', () => {
    mockedUseApi
      .mockReturnValueOnce(makeUseApi({ data: baseEventsResponse }))
      .mockReturnValue(makeUseApi({ data: { available: false, message: 'VAPT summary not built yet.' } }))
    render(<SecurityEvents token="test-token" />)
    fireEvent.click(screen.getByRole('button', { name: 'VAPT Report' }))
    expect(screen.getByText(/VAPT summary not built yet/)).toBeInTheDocument()
  })
})

describe('SecurityCenter — expandable rows', () => {
  beforeEach(() => vi.clearAllMocks())

  it('row expands on click and shows detail panel sections', () => {
    mockedUseApi.mockReturnValue(makeUseApi({ data: baseEventsResponse }))
    render(<SecurityEvents token="test-token" />)
    const rows = document.querySelectorAll('tbody tr')
    expect(rows.length).toBeGreaterThan(0)
    fireEvent.click(rows[0])
    // "Why it matters", "What the system did", "What you should do" are panel-only text
    expect(screen.getByText(/Why it matters/)).toBeInTheDocument()
    expect(screen.getByText(/What the system did/)).toBeInTheDocument()
    expect(screen.getByText(/What you should do/)).toBeInTheDocument()
  })

  it('row collapses when clicked again', () => {
    mockedUseApi.mockReturnValue(makeUseApi({ data: baseEventsResponse }))
    render(<SecurityEvents token="test-token" />)
    const rows = document.querySelectorAll('tbody tr')
    fireEvent.click(rows[0])
    expect(screen.getByText(/Why it matters/)).toBeInTheDocument()
    fireEvent.click(rows[0])
    expect(screen.queryByText(/Why it matters/)).not.toBeInTheDocument()
  })

  it('expanded row has aria-expanded=true', () => {
    mockedUseApi.mockReturnValue(makeUseApi({ data: baseEventsResponse }))
    render(<SecurityEvents token="test-token" />)
    const rows = document.querySelectorAll('tbody tr')
    fireEvent.click(rows[0])
    expect(rows[0].getAttribute('aria-expanded')).toBe('true')
  })
})

describe('SecurityCenter — filter chips', () => {
  beforeEach(() => vi.clearAllMocks())

  it('renders All, Attacks blocked, Needs decision, Normal filter chips', () => {
    mockedUseApi.mockReturnValue(makeUseApi({ data: baseEventsResponse }))
    render(<SecurityEvents token="test-token" />)
    expect(screen.getByRole('button', { name: 'All' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Attacks blocked' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Needs decision' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Normal' })).toBeInTheDocument()
  })

  it('filter chip changes visible events', () => {
    mockedUseApi.mockReturnValue(makeUseApi({ data: baseEventsResponse }))
    render(<SecurityEvents token="test-token" />)
    fireEvent.click(screen.getByRole('button', { name: 'Attacks blocked' }))
    // signature_verification_failed is in BLOCKED_TYPES — should still show
    expect(screen.getByText(/Forged update blocked/)).toBeInTheDocument()
  })

  it('search input filters by client', () => {
    mockedUseApi.mockReturnValue(makeUseApi({ data: baseEventsResponse }))
    render(<SecurityEvents token="test-token" />)
    const searchInput = screen.getByPlaceholderText(/Search by client/i)
    fireEvent.change(searchInput, { target: { value: 'bank-delhi' } })
    expect(screen.queryByText(/Forged update blocked/)).not.toBeInTheDocument()
  })
})

describe('SecurityEvents XSS output escaping', () => {
  beforeEach(() => vi.clearAllMocks())

  it('renders img-tag XSS payload in client_id as escaped text, not a DOM element', () => {
    const xssPayload = '<img src=x onerror=alert(1)>'
    const xssResponse: SecurityEventsResponse = {
      events: [
        {
          timestamp: '2026-11-21T12:00:00',
          event_type: 'key.registered',
          client_id: xssPayload,
          rule_id: '100131',
          level: 3,
          severity: 'Low',
          plain_english: 'Trusted client signing key registered',
        },
      ],
      total: 1,
      message: '',
    }
    mockedUseApi.mockReturnValue(makeUseApi({ data: xssResponse }))
    const { container } = render(<SecurityEvents token="test-token" />)
    // React JSX auto-escaping: payload visible as literal text
    expect(screen.getByText(xssPayload)).toBeInTheDocument()
    // No img element injected into the DOM
    expect(container.querySelectorAll('img')).toHaveLength(0)
  })

  it('renders script-tag XSS payload in plain_english as escaped text, not a DOM element', () => {
    const xssPayload = '<script>alert("xss")</script>'
    const xssResponse: SecurityEventsResponse = {
      events: [
        {
          timestamp: '2026-11-21T12:00:00',
          event_type: 'key.registered',
          client_id: 'bank-safe-01',
          rule_id: '100131',
          level: 3,
          severity: 'Low',
          plain_english: xssPayload,
        },
      ],
      total: 1,
      message: '',
    }
    mockedUseApi.mockReturnValue(makeUseApi({ data: xssResponse }))
    const { container } = render(<SecurityEvents token="test-token" />)
    expect(screen.getByText(xssPayload)).toBeInTheDocument()
    // No script element injected into the DOM
    expect(container.querySelectorAll('script')).toHaveLength(0)
  })
})

describe('DetectionRules — expandable rows', () => {
  beforeEach(() => vi.clearAllMocks())

  const baseCatalogResponse = {
    rules: [
      {
        event_type: 'security.signature_verification_failed',
        rule_id: '100104',
        level: 12,
        severity: 'High',
        plain_english: 'Forged update blocked — invalid signature',
        match_type: 'exact',
        why_it_matters: 'The signature did not match the registered key.',
        what_to_do: 'Revoke the client key immediately.',
        example: 'Invalid signature on update from bank-node-03.',
      },
    ],
    total: 1,
  }

  it('clicking a rule row expands it and shows why_it_matters', () => {
    // Return catalog response for all useApi calls so every tab gets usable data
    mockedUseApi.mockReturnValue(makeUseApi({ data: baseCatalogResponse }))
    render(<SecurityEvents token="test-token" />)
    fireEvent.click(screen.getByRole('button', { name: 'Detection Rules' }))
    const rows = document.querySelectorAll('tbody tr')
    expect(rows.length).toBeGreaterThan(0)
    fireEvent.click(rows[0])
    expect(screen.getByText(/The signature did not match/)).toBeInTheDocument()
    expect(screen.getByText(/Revoke the client key/)).toBeInTheDocument()
  })
})

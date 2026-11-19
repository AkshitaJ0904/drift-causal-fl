import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import Approvals from '../pages/Approvals'
import { useApi } from '../hooks/useApi'
import { api, ApiError } from '../api/client'
import type { ApprovalRecord } from '../api/client'

vi.mock('../hooks/useApi')
vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>()
  return {
    ...actual,
    api: {
      approveUpdate: vi.fn(),
      rejectUpdate: vi.fn(),
      quarantineUpdate: vi.fn(),
      getPendingApprovals: vi.fn(),
    },
  }
})

const mockedUseApi = vi.mocked(useApi)

const sampleRecord: ApprovalRecord = {
  update_id: 'upd-001',
  client_id: 'client-abc',
  model_version: '1.0.0',
  round_number: 1,
  sample_count: 100,
  payload_sha256: null,
  status: 'pending_approval',
  risk_score: 25,
  risk_severity: 'high',
  suspicious: true,
  anomaly_reasons: [],
  audit_status: null,
  reason: '',
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

describe('Approvals', () => {
  beforeEach(() => vi.clearAllMocks())

  it('shows loading spinner', () => {
    mockedUseApi.mockReturnValue(makeUseApi({ loading: true }))
    render(<Approvals token="test-token" />)
    expect(screen.getByText('Loading approval queue…')).toBeInTheDocument()
  })

  it('shows empty state when no pending approvals', () => {
    mockedUseApi.mockReturnValue(makeUseApi({ data: { pending: [] } }))
    render(<Approvals token="test-token" />)
    expect(screen.getByText('No pending approvals.')).toBeInTheDocument()
  })

  it('renders approval records table', () => {
    mockedUseApi.mockReturnValue(makeUseApi({ data: { pending: [sampleRecord] } }))
    render(<Approvals token="test-token" />)
    expect(screen.getByText('upd-001')).toBeInTheDocument()
    expect(screen.getByText('client-abc')).toBeInTheDocument()
  })

  it('shows pending badge on record', () => {
    mockedUseApi.mockReturnValue(makeUseApi({ data: { pending: [sampleRecord] } }))
    render(<Approvals token="test-token" />)
    expect(screen.getByText('pending')).toBeInTheDocument()
  })

  it('opens confirmation panel on approve click', async () => {
    mockedUseApi.mockReturnValue(makeUseApi({ data: { pending: [sampleRecord] } }))
    render(<Approvals token="test-token" />)
    await userEvent.click(screen.getByRole('button', { name: 'Approve' }))
    expect(screen.getByText(/Confirm Approve/)).toBeInTheDocument()
    expect(screen.getByLabelText(/Decision Reason/)).toBeInTheDocument()
  })

  it('shows error when reason is empty on confirm', async () => {
    mockedUseApi.mockReturnValue(makeUseApi({ data: { pending: [sampleRecord] } }))
    render(<Approvals token="test-token" />)
    await userEvent.click(screen.getByRole('button', { name: 'Approve' }))
    await userEvent.click(screen.getByRole('button', { name: 'Confirm Approve' }))
    // actionError renders in both top bar and confirmation panel
    expect(
      screen.getAllByText('A reason is required. This decision is recorded in the audit trail.').length,
    ).toBeGreaterThanOrEqual(1)
    expect(vi.mocked(api.approveUpdate)).not.toHaveBeenCalled()
  })

  it('submits approve with reason and shows success', async () => {
    const refresh = vi.fn()
    mockedUseApi.mockReturnValue(makeUseApi({ data: { pending: [sampleRecord] }, refresh }))
    vi.mocked(api.approveUpdate).mockResolvedValueOnce({ ...sampleRecord, status: 'approved' })
    render(<Approvals token="test-token" />)
    await userEvent.click(screen.getByRole('button', { name: 'Approve' }))
    await userEvent.type(screen.getByLabelText(/Decision Reason/), 'Looks good')
    await userEvent.click(screen.getByRole('button', { name: 'Confirm Approve' }))
    await waitFor(() =>
      expect(screen.getByText(/Approved update upd-001/)).toBeInTheDocument(),
    )
    expect(refresh).toHaveBeenCalled()
  })

  it('opens quarantine confirmation panel', async () => {
    mockedUseApi.mockReturnValue(makeUseApi({ data: { pending: [sampleRecord] } }))
    render(<Approvals token="test-token" />)
    await userEvent.click(screen.getByRole('button', { name: 'Quarantine' }))
    expect(screen.getByText(/Confirm Quarantine/)).toBeInTheDocument()
  })

  it('opens reject confirmation panel', async () => {
    mockedUseApi.mockReturnValue(makeUseApi({ data: { pending: [sampleRecord] } }))
    render(<Approvals token="test-token" />)
    await userEvent.click(screen.getByRole('button', { name: 'Reject' }))
    expect(screen.getByText(/Confirm Reject/)).toBeInTheDocument()
  })

  it('cancel button clears confirmation panel', async () => {
    mockedUseApi.mockReturnValue(makeUseApi({ data: { pending: [sampleRecord] } }))
    render(<Approvals token="test-token" />)
    await userEvent.click(screen.getByRole('button', { name: 'Approve' }))
    await userEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(screen.queryByText(/Confirm Approve/)).not.toBeInTheDocument()
  })

  it('shows API error in confirmation panel on failure', async () => {
    mockedUseApi.mockReturnValue(makeUseApi({ data: { pending: [sampleRecord] } }))
    vi.mocked(api.approveUpdate).mockRejectedValueOnce(new ApiError(422, 'Validation failed'))
    render(<Approvals token="test-token" />)
    await userEvent.click(screen.getByRole('button', { name: 'Approve' }))
    await userEvent.type(screen.getByLabelText(/Decision Reason/), 'some reason')
    await userEvent.click(screen.getByRole('button', { name: 'Confirm Approve' }))
    // actionError is shown in both the top-level alert and the confirmation panel
    await waitFor(() =>
      expect(
        screen.getAllByText('HTTP 422: Validation failed').length,
      ).toBeGreaterThanOrEqual(1),
    )
  })

  it('submits quarantine with reason and shows success', async () => {
    const refresh = vi.fn()
    mockedUseApi.mockReturnValue(makeUseApi({ data: { pending: [sampleRecord] }, refresh }))
    vi.mocked(api.quarantineUpdate).mockResolvedValueOnce({ ...sampleRecord, status: 'quarantined' })
    render(<Approvals token="test-token" />)
    await userEvent.click(screen.getByRole('button', { name: 'Quarantine' }))
    await userEvent.type(screen.getByLabelText(/Decision Reason/), 'Suspected model poisoning')
    await userEvent.click(screen.getByRole('button', { name: 'Confirm Quarantine' }))
    await waitFor(() =>
      expect(screen.getByText(/Quarantined update upd-001/)).toBeInTheDocument(),
    )
    expect(refresh).toHaveBeenCalled()
  })

  it('submits reject with reason and shows success', async () => {
    const refresh = vi.fn()
    mockedUseApi.mockReturnValue(makeUseApi({ data: { pending: [sampleRecord] }, refresh }))
    vi.mocked(api.rejectUpdate).mockResolvedValueOnce({ ...sampleRecord, status: 'rejected' })
    render(<Approvals token="test-token" />)
    await userEvent.click(screen.getByRole('button', { name: 'Reject' }))
    await userEvent.type(screen.getByLabelText(/Decision Reason/), 'Invalid payload structure')
    await userEvent.click(screen.getByRole('button', { name: 'Confirm Reject' }))
    await waitFor(() =>
      expect(screen.getByText(/Rejected update upd-001/)).toBeInTheDocument(),
    )
    expect(refresh).toHaveBeenCalled()
  })

  it('refresh button invokes the refresh function', async () => {
    const refresh = vi.fn()
    mockedUseApi.mockReturnValue(makeUseApi({ data: { pending: [sampleRecord] }, refresh }))
    render(<Approvals token="test-token" />)
    await userEvent.click(screen.getByRole('button', { name: '↻ Refresh' }))
    expect(refresh).toHaveBeenCalled()
  })
})

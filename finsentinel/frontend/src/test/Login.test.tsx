import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import Login from '../pages/Login'
import { api, ApiError } from '../api/client'

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>()
  return {
    ...actual,
    api: {
      getDashboard: vi.fn(),
    },
  }
})

const mockGetDashboard = vi.mocked(api.getDashboard)

const VALID_TOKEN = 'a'.repeat(32)

describe('Login', () => {
  const onLogin = vi.fn()

  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders the login form', () => {
    render(<Login onLogin={onLogin} />)
    expect(screen.getByLabelText('Operator Token')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Authenticate' })).toBeInTheDocument()
  })

  it('shows error when token is empty', async () => {
    render(<Login onLogin={onLogin} />)
    await userEvent.click(screen.getByRole('button', { name: 'Authenticate' }))
    expect(screen.getByText('Enter the operator bearer token.')).toBeInTheDocument()
    expect(mockGetDashboard).not.toHaveBeenCalled()
  })

  it('shows error when token is shorter than 32 chars', async () => {
    render(<Login onLogin={onLogin} />)
    await userEvent.type(screen.getByLabelText('Operator Token'), 'short')
    await userEvent.click(screen.getByRole('button', { name: 'Authenticate' }))
    expect(
      screen.getByText('Token is too short — FinSentinel requires a minimum 32-character token.'),
    ).toBeInTheDocument()
    expect(mockGetDashboard).not.toHaveBeenCalled()
  })

  it('calls onLogin on success', async () => {
    mockGetDashboard.mockResolvedValueOnce({
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
    })
    render(<Login onLogin={onLogin} />)
    await userEvent.type(screen.getByLabelText('Operator Token'), VALID_TOKEN)
    await userEvent.click(screen.getByRole('button', { name: 'Authenticate' }))
    await waitFor(() => expect(onLogin).toHaveBeenCalledWith(VALID_TOKEN))
  })

  it('shows "Invalid operator token." on 401', async () => {
    mockGetDashboard.mockRejectedValueOnce(new ApiError(401, 'Unauthorized'))
    render(<Login onLogin={onLogin} />)
    await userEvent.type(screen.getByLabelText('Operator Token'), VALID_TOKEN)
    await userEvent.click(screen.getByRole('button', { name: 'Authenticate' }))
    await waitFor(() =>
      expect(screen.getByText('Invalid operator token.')).toBeInTheDocument(),
    )
    expect(onLogin).not.toHaveBeenCalled()
  })

  it('shows 503 configuration message on 503', async () => {
    mockGetDashboard.mockRejectedValueOnce(new ApiError(503, 'Service Unavailable'))
    render(<Login onLogin={onLogin} />)
    await userEvent.type(screen.getByLabelText('Operator Token'), VALID_TOKEN)
    await userEvent.click(screen.getByRole('button', { name: 'Authenticate' }))
    await waitFor(() =>
      expect(
        screen.getByText(
          'Operator authentication is not configured on this server. Set FINSENTINEL_OPERATOR_TOKEN and restart.',
        ),
      ).toBeInTheDocument(),
    )
  })

  it('shows generic HTTP error on other API errors', async () => {
    mockGetDashboard.mockRejectedValueOnce(new ApiError(500, 'Internal Server Error'))
    render(<Login onLogin={onLogin} />)
    await userEvent.type(screen.getByLabelText('Operator Token'), VALID_TOKEN)
    await userEvent.click(screen.getByRole('button', { name: 'Authenticate' }))
    await waitFor(() =>
      expect(
        screen.getByText('Authentication failed (HTTP 500): Internal Server Error'),
      ).toBeInTheDocument(),
    )
  })

  it('shows backend unreachable message on network error', async () => {
    mockGetDashboard.mockRejectedValueOnce(new Error('fetch failed'))
    render(<Login onLogin={onLogin} />)
    await userEvent.type(screen.getByLabelText('Operator Token'), VALID_TOKEN)
    await userEvent.click(screen.getByRole('button', { name: 'Authenticate' }))
    await waitFor(() =>
      expect(
        screen.getByText(
          'Could not reach the backend. Confirm the server is running and the proxy is configured.',
        ),
      ).toBeInTheDocument(),
    )
  })

  it('disables button while verifying', async () => {
    let resolve!: () => void
    mockGetDashboard.mockImplementationOnce(
      () => new Promise<never>((res) => { resolve = res as unknown as () => void }),
    )
    render(<Login onLogin={onLogin} />)
    await userEvent.type(screen.getByLabelText('Operator Token'), VALID_TOKEN)
    await userEvent.click(screen.getByRole('button', { name: 'Authenticate' }))
    expect(screen.getByRole('button', { name: /Verifying/ })).toBeDisabled()
    resolve()
  })

  it('token is kept in memory note is visible', () => {
    render(<Login onLogin={onLogin} />)
    expect(
      screen.getByText('Token is kept in memory only — cleared on page reload.'),
    ).toBeInTheDocument()
  })
})

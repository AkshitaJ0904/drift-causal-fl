import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render } from '@testing-library/react'
import App from '../App'
import { useAuth } from '../hooks/useAuth'
import { setUnauthenticatedHandler, clearUnauthenticatedHandler } from '../api/client'

vi.mock('../hooks/useAuth')
vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>()
  return {
    ...actual,
    setUnauthenticatedHandler: vi.fn(),
    clearUnauthenticatedHandler: vi.fn(),
  }
})

// Stub every page and layout to avoid their own api/hook calls under test.
vi.mock('../pages/Dashboard', () => ({ default: () => null }))
vi.mock('../pages/Approvals', () => ({ default: () => null }))
vi.mock('../pages/TrustedKeys', () => ({ default: () => null }))
vi.mock('../pages/ModelSchemas', () => ({ default: () => null }))
vi.mock('../pages/AuditOutbox', () => ({ default: () => null }))
vi.mock('../pages/Aggregation', () => ({ default: () => null }))
vi.mock('../pages/DetectionConfig', () => ({ default: () => null }))
vi.mock('../pages/HealthMonitor', () => ({ default: () => null }))
vi.mock('../components/Layout', () => ({ default: () => null }))
vi.mock('../pages/Login', () => ({ default: () => null }))

const mockedUseAuth = vi.mocked(useAuth)
const mockedSetHandler = vi.mocked(setUnauthenticatedHandler)
const mockedClearHandler = vi.mocked(clearUnauthenticatedHandler)

describe('App — 401 auto-logout chain', () => {
  beforeEach(() => vi.clearAllMocks())

  it('registers auth.logout as the unauthenticated handler when a token is present', () => {
    const mockLogout = vi.fn()
    mockedUseAuth.mockReturnValue({ token: 'mock-operator-token', login: vi.fn(), logout: mockLogout })
    render(<App />)
    expect(mockedSetHandler).toHaveBeenCalledWith(mockLogout)
  })

  it('clears the unauthenticated handler when no token is present', () => {
    mockedUseAuth.mockReturnValue({ token: null, login: vi.fn(), logout: vi.fn() })
    render(<App />)
    expect(mockedClearHandler).toHaveBeenCalled()
  })

  it('the registered handler is auth.logout — invoking it triggers logout', () => {
    const mockLogout = vi.fn()
    mockedUseAuth.mockReturnValue({ token: 'mock-operator-token', login: vi.fn(), logout: mockLogout })
    render(<App />)
    // StrictMode may call the effect more than once; use the first registered call.
    const registeredHandler = mockedSetHandler.mock.calls[0][0]
    registeredHandler()
    expect(mockLogout).toHaveBeenCalled()
  })
})

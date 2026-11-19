/**
 * Authentication state hook.
 *
 * Token is kept only in React state (never persisted to storage) so it is
 * cleared on page reload and not accessible to other tabs or scripts.
 */

import { useState } from 'react'

export interface AuthState {
  token: string | null
  login: (token: string) => void
  logout: () => void
}

export function useAuth(): AuthState {
  const [token, setToken] = useState<string | null>(null)

  const login = (t: string) => setToken(t.trim())
  const logout = () => setToken(null)

  return { token, login, logout }
}

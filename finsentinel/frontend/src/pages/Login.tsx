import { type FormEvent, useState } from 'react'
import { api, ApiError } from '../api/client'

interface Props {
  onLogin: (token: string) => void
}

export default function Login({ onLogin }: Props) {
  const [token, setToken] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [verifying, setVerifying] = useState(false)

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()
    const t = token.trim()
    if (!t) {
      setError('Enter the operator bearer token.')
      return
    }
    if (t.length < 32) {
      setError('Token is too short — FinSentinel requires a minimum 32-character token.')
      return
    }
    setError(null)
    setVerifying(true)
    try {
      await api.getDashboard(t)
      onLogin(t)
      // component unmounts on success — no need to reset verifying
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.status === 401) {
          setError('Invalid operator token.')
        } else if (err.status === 503) {
          setError('Operator authentication is not configured on this server. Set FINSENTINEL_OPERATOR_TOKEN and restart.')
        } else {
          setError(`Authentication failed (HTTP ${err.status}): ${err.message}`)
        }
      } else {
        setError('Could not reach the backend. Confirm the server is running and the proxy is configured.')
      }
      setVerifying(false)
    }
  }

  return (
    <div className="login-screen">
      <div className="login-box">
        <div className="login-logo-wrap">
          <div className="login-logo-mark">FS</div>
          <div>
            <div className="login-logo">Fin<span>Sentinel</span></div>
            <div className="login-tagline">FL Security &amp; Trust Intelligence</div>
          </div>
        </div>

        <div className="login-divider" />

        {error && (
          <div className="alert alert-error" style={{ marginBottom: 16 }}>
            {error}
          </div>
        )}

        <form onSubmit={handleSubmit}>
          <div className="form-group">
            <label className="form-label" htmlFor="token">Operator Token</label>
            <input
              id="token"
              type="password"
              className="form-input"
              placeholder="Bearer token (min 32 chars)"
              value={token}
              onChange={(e) => setToken(e.target.value)}
              autoComplete="current-password"
              autoFocus
            />
            <div style={{ marginTop: 6, fontSize: 11, color: 'var(--text-muted)', lineHeight: 1.5 }}>
              Token is read from{' '}
              <code style={{ fontFamily: 'monospace', background: 'var(--bg-hover)', padding: '1px 4px', borderRadius: 3 }}>
                %USERPROFILE%\.finsentinel\dev_token.txt
              </code>
            </div>
          </div>

          <button
            type="submit"
            className="btn btn-primary"
            disabled={verifying}
            style={{ width: '100%', marginTop: 4, padding: '10px 14px', justifyContent: 'center', fontSize: 13 }}
          >
            {verifying
              ? <><span className="spinner" style={{ width: 14, height: 14 }} /> Verifying…</>
              : 'Authenticate'}
          </button>
        </form>

        <div className="text-muted mt-16" style={{ fontSize: 11, textAlign: 'center', lineHeight: 1.5 }}>
          Token is kept in memory only — cleared on page reload.
        </div>
      </div>
    </div>
  )
}

/**
 * Generic data-fetching hook with loading/error states.
 */

import { useCallback, useEffect, useState } from 'react'
import { ApiError } from '../api/client'

export interface UseApiResult<T> {
  data: T | null
  loading: boolean
  error: string | null
  refresh: () => void
}

export interface UseApiOptions {
  /** Polling interval in ms. When set, the hook re-fetches automatically. */
  pollingIntervalMs?: number
}

export function useApi<T>(
  fetchFn: () => Promise<T>,
  deps: unknown[] = [],
  options: UseApiOptions = {},
): UseApiResult<T> {
  const [data, setData] = useState<T | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [tick, setTick] = useState(0)

  const refresh = useCallback(() => setTick((t) => t + 1), [])

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)

    fetchFn()
      .then((result) => {
        if (!cancelled) {
          setData(result)
          setLoading(false)
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          const msg =
            err instanceof ApiError
              ? `API error ${err.status}: ${err.message}`
              : err instanceof Error
                ? err.message
                : 'Unknown error'
          setError(msg)
          setLoading(false)
        }
      })

    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tick, ...deps])

  // Auto-polling: re-fetch on the given interval when the tab is visible.
  useEffect(() => {
    const { pollingIntervalMs } = options
    if (!pollingIntervalMs) return
    const id = setInterval(() => {
      if (!document.hidden) setTick((t) => t + 1)
    }, pollingIntervalMs)
    return () => clearInterval(id)
    // pollingIntervalMs is intentionally not in deps — treat as stable config
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return { data, loading, error, refresh }
}

import { useCallback, useEffect, useState } from 'react'

import { ApiError } from '../../lib/api'

export interface AsyncState<T> {
  data: T | null
  loading: boolean
  /** HTTP status when the failure was an ApiError, else null. */
  errorStatus: number | null
  error: string | null
  reload: () => void
}

type Result<T> = Omit<AsyncState<T>, 'reload'>

/** Minimal fetch hook: reruns when `key` changes or `reload()` is called,
 * and ignores stale responses. */
export function useAsync<T>(load: () => Promise<T>, key: string | number): AsyncState<T> {
  const [attempt, setAttempt] = useState(0)
  const [state, setState] = useState<Result<T>>({
    data: null,
    loading: true,
    errorStatus: null,
    error: null,
  })

  useEffect(() => {
    let cancelled = false
    setState({ data: null, loading: true, errorStatus: null, error: null })
    load()
      .then((data) => {
        if (!cancelled) setState({ data, loading: false, errorStatus: null, error: null })
      })
      .catch((err: unknown) => {
        if (cancelled) return
        const status = err instanceof ApiError ? err.status : null
        const message = err instanceof Error ? err.message : 'Something went wrong.'
        setState({ data: null, loading: false, errorStatus: status, error: message })
      })
    return () => {
      cancelled = true
    }
    // `load` is recreated each render; `key` and `attempt` are the real inputs.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, attempt])

  const reload = useCallback(() => setAttempt((n) => n + 1), [])
  return { ...state, reload }
}

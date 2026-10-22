import { useCallback, useEffect, useState } from 'react'

import { ApiError } from '../../lib/api'

export interface QueryState<T> {
  data: T | null
  /** True during the very first load only. */
  loading: boolean
  /** True while refetching with the old data still on screen. */
  refreshing: boolean
  error: string | null
  errorStatus: number | null
  reload: () => void
}

/** Like a fetch-on-key hook, but a new search/page/sort keeps the previous
 * rows on screen (dimmed) instead of blanking the table. */
export function useQuery<T>(load: () => Promise<T>, key: string): QueryState<T> {
  const [attempt, setAttempt] = useState(0)
  const [state, setState] = useState<Omit<QueryState<T>, 'reload'>>({
    data: null,
    loading: true,
    refreshing: false,
    error: null,
    errorStatus: null,
  })

  useEffect(() => {
    let cancelled = false
    setState((s) => ({ ...s, refreshing: s.data !== null, loading: s.data === null, error: null }))
    load()
      .then((data) => {
        if (!cancelled)
          setState({ data, loading: false, refreshing: false, error: null, errorStatus: null })
      })
      .catch((err: unknown) => {
        if (cancelled) return
        setState({
          data: null,
          loading: false,
          refreshing: false,
          error: err instanceof Error ? err.message : 'Something went wrong.',
          errorStatus: err instanceof ApiError ? err.status : null,
        })
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

/** A value that follows `value` after `ms` of quiet — for search boxes. */
export function useDebounced<T>(value: T, ms = 300): T {
  const [settled, setSettled] = useState(value)
  useEffect(() => {
    const id = setTimeout(() => setSettled(value), ms)
    return () => clearTimeout(id)
  }, [value, ms])
  return settled
}

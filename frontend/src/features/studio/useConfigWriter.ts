import { useCallback, useEffect, useRef } from 'react'

/** Saves an activity's whole `config` one edit at a time without losing any.
 *
 * Every field sends the full config, built from what the page currently
 * shows. Edit a second field before the first save has come back and that
 * copy is stale — the second save would quietly undo the first. So edits are
 * applied to a working copy that already includes everything still in
 * flight, and the saves are sent in order. */
export function useConfigWriter<T extends Record<string, unknown>>(
  config: T,
  persist: (next: T) => Promise<void>,
) {
  const working = useRef(config)
  const shown = useRef(config)
  const send = useRef(persist)
  const tail = useRef<Promise<void>>(Promise.resolve())
  const inFlight = useRef(0)

  useEffect(() => {
    shown.current = config
    send.current = persist
    // Adopt the server's copy once nothing of ours is still on its way.
    if (inFlight.current === 0) working.current = config
  }, [config, persist])

  return useCallback((change: (current: T) => T): Promise<void> => {
    const next = change(working.current)
    working.current = next
    inFlight.current += 1
    const job = tail.current.then(() => send.current(next))
    tail.current = job
      .catch(() => {})
      .then(() => {
        inFlight.current -= 1
        // A failure leaves nothing newer to trust than what the page shows.
        if (inFlight.current === 0) working.current = shown.current
      })
    return job
  }, [])
}

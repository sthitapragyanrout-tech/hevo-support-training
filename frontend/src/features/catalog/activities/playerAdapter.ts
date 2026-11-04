/** What the tracker needs to know about a player, whichever kind it is — a
 * plain `<video>` or an embedded YouTube one. */
export interface PlayerAdapter {
  /** Seconds into the video. */
  position(): number
  /** Playback speed. */
  rate(): number
  playing(): boolean
  /** Total length in seconds, once known. */
  duration(): number | null
}

export function videoElementAdapter(el: HTMLVideoElement): PlayerAdapter {
  return {
    position: () => el.currentTime,
    rate: () => el.playbackRate,
    // Not paused, not finished, and actually has data to show.
    playing: () => !el.paused && !el.ended && el.readyState >= 3,
    duration: () => (Number.isFinite(el.duration) && el.duration > 0 ? el.duration : null),
  }
}

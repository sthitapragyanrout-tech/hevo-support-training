"""The arithmetic of verified watching — pure functions, no database, no clock.

What the browser sends is a *claim* about which stretches of a video were
played. What the server may *believe* is bounded by something the browser can't
fake: how much real time has passed on the server's own clock. This module
holds the parts of that rule that are just numbers:

  * `clean_ranges`  — accept a claim only if it is well-formed
  * `subtract`      — what in a claim is new (not already credited)
  * `refill`        — how much credit real elapsed time has earned (a bucket)
  * `trim_to_budget`— keep only as much new coverage as the bucket allows

Together they give the guarantee the tests assert for *every* input sequence:

    credited seconds  ≤  INITIAL_BUDGET + (real seconds between first and last
                         heartbeat) × (credited playback speed) × TOLERANCE

and credited ranges are always a subset of what was claimed, inside the video.
So scrubbing, forged requests, replays and parallel tabs earn nothing extra;
finishing a video costs roughly its length in real time (at least about
(threshold × length − INITIAL_BUDGET) ÷ (speed × TOLERANCE) seconds).

Honest limit: this deters bypassing, it cannot prove a person was watching. A
muted tab left playing earns credit like anyone else's.
"""

from __future__ import annotations

import math
from typing import Any

Interval = tuple[float, float]

MAX_RANGES = 20  # per heartbeat; the browser merges before sending
MAX_RANGE_SECONDS = 300.0
BUCKET_CAPACITY = 90.0  # seconds of video a quiet client can save up
# A small starting allowance only: the player announces playback with an empty
# heartbeat the moment it starts, so the server's clock runs from then. (A bigger
# allowance would let a short video be finished almost at once — found in
# browser testing with a 30 s clip.)
INITIAL_BUDGET = 5.0
TOLERANCE = 1.1  # network jitter and timer drift
RATE_SLACK = 0.05
EDGE_SLACK = 0.5  # a final position a hair past the reported end
MIN_CREDIT = 1e-6  # seconds; anything smaller is rounding, not watching


class BadClaim(ValueError):
    """The claim isn't something an honest player would send."""


def _number(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise BadClaim("not a number")
    number = float(value)
    if not math.isfinite(number):
        raise BadClaim("not finite")
    return number


def number(value: Any, *, low: float, high: float) -> float:
    """A finite number within [low, high], or `BadClaim`."""
    n = _number(value)
    if n < low or n > high:
        raise BadClaim("out of range")
    return n


def clean_ranges(raw: Any, duration: float) -> list[Interval]:
    """Validate a claimed list of `[start, end]` stretches. They must be in order
    and not overlap (the browser merges before sending); each lies inside the
    video. Anything else is refused outright — never "fixed up"."""
    if not isinstance(raw, list) or len(raw) > MAX_RANGES:
        raise BadClaim("bad list")
    cleaned: list[Interval] = []
    previous_end = 0.0
    for item in raw:
        if not isinstance(item, (list, tuple)) or len(item) != 2:
            raise BadClaim("bad range")
        start, end = _number(item[0]), _number(item[1])
        if start < 0 or end <= start or end > duration + EDGE_SLACK:
            raise BadClaim("range outside the video")
        if end - start > MAX_RANGE_SECONDS or start < previous_end:
            raise BadClaim("range too long or out of order")
        end = min(end, duration)
        if end <= start:
            raise BadClaim("empty after clamping")
        cleaned.append((start, end))
        previous_end = end
    return cleaned


def measure(ranges: list[Interval]) -> float:
    return sum(end - start for start, end in ranges)


def merge(ranges: list[Interval]) -> list[Interval]:
    """Union of intervals, sorted, touching ones joined."""
    out: list[Interval] = []
    for start, end in sorted(ranges):
        if out and start <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], end))
        else:
            out.append((start, end))
    return out


def subtract(claimed: list[Interval], credited: list[Interval]) -> list[Interval]:
    """The parts of `claimed` that `credited` doesn't already cover, in order."""
    result: list[Interval] = []
    for start, end in claimed:
        cursor = start
        for c_start, c_end in credited:
            if c_end <= cursor:
                continue
            if c_start >= end:
                break
            if c_start > cursor:
                result.append((cursor, c_start))
            cursor = max(cursor, c_end)
            if cursor >= end:
                break
        if cursor < end:
            result.append((cursor, end))
    return result


def refill(level: float, elapsed: float, rate: float) -> float:
    """The bucket after `elapsed` real seconds at credited speed `rate`."""
    earned = max(elapsed, 0.0) * rate * TOLERANCE
    return min(BUCKET_CAPACITY, max(level, 0.0) + earned)


def trim_to_budget(new: list[Interval], budget: float) -> tuple[list[Interval], float]:
    """Keep the first `budget` seconds of `new` (in order). Returns the kept
    intervals and how many seconds were refused."""
    kept: list[Interval] = []
    left = max(budget, 0.0)
    refused = 0.0
    for start, end in new:
        length = end - start
        if left <= MIN_CREDIT:  # a sliver is no credit, and must not become a zero-length range
            refused += length
        elif length <= left:
            kept.append((start, end))
            left -= length
        else:
            kept.append((start, start + left))
            refused += length - left
            left = 0.0
    return kept, refused


def as_lists(ranges: list[Interval]) -> list[list[float]]:
    return [[round(s, 3), round(e, 3)] for s, e in ranges]


def from_lists(raw: Any) -> list[Interval]:
    """Ranges as stored (JSON), back to tuples; tolerant of nothing odd."""
    return [(float(s), float(e)) for s, e in (raw or [])]

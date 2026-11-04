"""HTTP byte ranges, so a browser can seek in a video without downloading it all.

Follows RFC 9110 §14: a single `bytes=` range is honoured (206); a malformed or
multi-range header is ignored and the whole file is sent (200); a range that
starts past the end is refused (416).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_RANGE = re.compile(r"^bytes=(\d{0,18})-(\d{0,18})$")


@dataclass(frozen=True)
class ByteRange:
    start: int
    end: int  # inclusive

    @property
    def length(self) -> int:
        return self.end - self.start + 1


class Unsatisfiable(Exception):
    """The range lies wholly outside the file."""


def parse(header: str | None, size: int) -> ByteRange | None:
    """The one range to serve, or None for "the whole file".
    Raises `Unsatisfiable` when the request can't be met."""
    if not header:
        return None
    match = _RANGE.match(header.strip())
    if not match:
        return None  # not a single simple range: ignore it
    first, last = match.groups()
    if first == "" and last == "":
        return None
    if size <= 0:
        raise Unsatisfiable()
    if first == "":  # the final N bytes
        suffix = int(last)
        if suffix == 0:
            raise Unsatisfiable()
        return ByteRange(max(size - suffix, 0), size - 1)
    start = int(first)
    if start >= size:
        raise Unsatisfiable()
    end = size - 1 if last == "" else min(int(last), size - 1)
    if end < start:
        return None  # "bytes=5-2" is invalid syntax: ignore
    return ByteRange(start, end)

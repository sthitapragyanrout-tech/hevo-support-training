"""Small, pure text helpers: finding documentation links, scrubbing personal data
from sample tickets, and spotting replies that need extra care."""

from __future__ import annotations

import re
from collections.abc import Iterable
from difflib import SequenceMatcher
from urllib.parse import urlparse

_URL = re.compile(r"https?://[^\s<>\"'\])]+", re.IGNORECASE)
_TRAILING = ".,;:!?)"


def extract_urls(text: str) -> list[str]:
    return [m.group(0).rstrip(_TRAILING) for m in _URL.finditer(text or "")]


def host_of(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower()
    except ValueError:
        return ""


def classify_links(texts: Iterable[str], docs_hosts: tuple[str, ...]) -> str:
    """ "docs" if any link is on an allowed documentation host, else "other" if
    there is any link at all, else "none". Hosts are matched exactly, so
    `docs.hevodata.com.evil.io` and `evil.io/docs.hevodata.com` don't count."""
    seen_other = False
    for text in texts:
        for url in extract_urls(text):
            if host_of(url) in docs_hosts:
                return "docs"
            seen_other = True
    return "other" if seen_other else "none"


def has_docs_link(text: str, docs_hosts: tuple[str, ...]) -> bool:
    return classify_links([text], docs_hosts) == "docs"


# --------------------------------------------------------------- sanitising

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_PHONE = re.compile(r"(?<!\w)\+?\d[\d\s().-]{8,}\d(?!\w)")
_IPV4 = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b")
_TOKEN = re.compile(r"\b(?=[A-Za-z0-9_-]*\d)(?=[A-Za-z0-9_-]*[A-Za-z])[A-Za-z0-9_-]{20,}\b")
_QUERY = re.compile(r"(https?://[^\s?#]+)\?[^\s]*")


def scrub_pii(text: str) -> str:
    """Remove the obvious personal data from a sample ticket before it is shown to
    a model or stored: emails, phone numbers, IP addresses, long id/token-like
    strings and URL query strings."""
    out = _EMAIL.sub("[email]", text or "")
    out = _QUERY.sub(r"\1", out)
    out = _IPV4.sub("[ip]", out)  # before phones: an IP is also a run of digits
    out = _PHONE.sub("[phone]", out)
    out = _TOKEN.sub("[id]", out)
    return out


def neutralise(text: str) -> str:
    """Make untrusted text safe to place between our own delimiter tags."""
    return (text or "").replace("<", "&lt;").replace(">", "&gt;")


_INJECTION = re.compile(
    r"(ignore|disregard|forget)\b.{0,40}\b(previous|above|prior|all|earlier)\b.{0,40}"
    r"\b(instruction|prompt|rule|guideline)s?"
    r"|\b(system|developer)\s+(prompt|message|instruction)"
    r"|\b(give|award|assign|rate|score)\b.{0,30}\b(me|this|it)?\b.{0,20}\b(5\s*/\s*5|full marks|perfect score|top score|maximum)\b"
    r"|\bas an? (ai|evaluator|grader|judge)\b"
    r"|\bevaluator\b.{0,30}\b(must|should)\b",
    re.IGNORECASE | re.DOTALL,
)


def looks_like_injection(text: str) -> bool:
    return bool(_INJECTION.search(text or ""))


def similarity(a: str, b: str) -> float:
    a, b = " ".join(a.lower().split())[:2000], " ".join(b.lower().split())[:2000]
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


MIN_WORDS = 3
MIN_CHARS = 15
WALL_CHARS = 3500


def sanity_flags(intern_text: str, customer_text: str) -> list[str]:
    """Deterministic checks on one reply, independent of any model."""
    text = (intern_text or "").strip()
    flags: list[str] = []
    if len(text) < MIN_CHARS or len(text.split()) < MIN_WORDS:
        flags.append("too_short")
    elif customer_text and (
        similarity(text, customer_text) >= 0.85
        or (len(customer_text.strip()) > 40 and customer_text.strip().lower() in text.lower())
    ):
        flags.append("copy_of_customer")
    if len(text) > WALL_CHARS:
        flags.append("wall_of_text")
    if looks_like_injection(text):
        flags.append("injection_suspected")
    return flags

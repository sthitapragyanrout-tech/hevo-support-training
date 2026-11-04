"""Reading past customer queries from Zendesk — read-only, and only genuine customers.

Nothing here ever writes to Zendesk: the transport has a `get` and nothing else. The
original bot took the first public comment of any closed ticket without checking who
wrote it — including the practice tickets it had itself created through the API. So a
ticket is used only if it *proves* it is a customer's own message (`judge_ticket`), and
anything unknown is rejected.

Credentials come from the environment only and never appear in an error message.
"""

from __future__ import annotations

import base64
import json
import math
import random
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

SUBDOMAIN = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
SEARCH_PAGE_SIZE = 100
SEARCH_MAX_PAGES = 10  # Zendesk's search API returns at most 1,000 results
MAX_BODY = 500  # the most of a customer's message we ever consider

# Tickets that were not typed by a customer: created through the API, by a rule or the
# system, or imported.
NON_CUSTOMER_CHANNELS = frozenset({"api", "system", "rule", "import", "import_mail"})
_QUOTED_REPLY = re.compile(
    r"(?im)^(on .{5,80} wrote:|-{2,}\s*original message\s*-{2,}|from:\s.+|sent from my .+)$"
)


class ZendeskError(Exception):
    """Something went wrong talking to Zendesk. The message is safe to show."""


class ZendeskNotConfigured(ZendeskError):
    pass


@dataclass(frozen=True)
class ZendeskConfig:
    subdomain: str
    email: str
    token: str
    form_names: tuple[str, ...] = ("Query", "Query_Old")
    exclude_requester_ids: frozenset[int] = frozenset()
    exclude_group_ids: frozenset[int] = frozenset()
    exclude_tags: frozenset[str] = frozenset()
    staff_domains: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if not SUBDOMAIN.match(self.subdomain):
            raise ZendeskNotConfigured("The Zendesk subdomain isn’t valid.")
        if not self.email or not self.token:
            raise ZendeskNotConfigured("Zendesk credentials aren’t set.")

    @property
    def base(self) -> str:
        return f"https://{self.subdomain}.zendesk.com/api/v2"

    @classmethod
    def from_settings(cls) -> ZendeskConfig:
        from django.conf import settings

        return cls(
            subdomain=settings.ZENDESK_SUBDOMAIN,
            email=settings.ZENDESK_EMAIL,
            token=settings.ZENDESK_API_TOKEN,
            form_names=tuple(settings.ZENDESK_FORM_NAMES),
            exclude_requester_ids=frozenset(settings.ZENDESK_EXCLUDE_REQUESTER_IDS),
            exclude_group_ids=frozenset(settings.ZENDESK_EXCLUDE_GROUP_IDS),
            exclude_tags=frozenset(t.lower() for t in settings.ZENDESK_EXCLUDE_TAGS),
            staff_domains=frozenset(d.lower() for d in settings.ZENDESK_STAFF_DOMAINS),
        )


def configured() -> bool:
    from django.conf import settings

    return bool(
        settings.ZENDESK_SUBDOMAIN and settings.ZENDESK_EMAIL and settings.ZENDESK_API_TOKEN
    )


# --------------------------------------------------------------- transport


@dataclass(frozen=True)
class Response:
    status: int
    headers: dict[str, str]
    body: bytes


class Transport(Protocol):
    """All the reader may do: GET. There is deliberately no other method to call."""

    def get(self, url: str, headers: dict[str, str], timeout: float) -> Response: ...


class UrllibTransport:
    def get(self, url: str, headers: dict[str, str], timeout: float) -> Response:
        request = urllib.request.Request(url, headers=headers, method="GET")  # noqa: S310
        try:
            with urllib.request.urlopen(request, timeout=timeout) as reply:  # noqa: S310
                return Response(
                    reply.status, {k.lower(): v for k, v in reply.headers.items()}, reply.read()
                )
        except urllib.error.HTTPError as exc:
            return Response(
                exc.code, {k.lower(): v for k, v in exc.headers.items()}, exc.read() or b""
            )
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise ZendeskError("Couldn’t reach Zendesk.") from exc


# ------------------------------------------------------------ the judgment


@dataclass(frozen=True)
class Verdict:
    ticket_id: int
    accepted: bool
    reason: str  # "ok" when accepted, otherwise why not
    subject: str = ""
    message: str = ""  # only for accepted tickets, and only held in memory


def _int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def first_part(body: str) -> str:
    """The customer's own words: drop a quoted earlier thread and cut to length."""
    match = _QUOTED_REPLY.search(body)
    if match:
        body = body[: match.start()]
    return " ".join(body.split())[:MAX_BODY]


def judge_ticket(
    ticket: dict[str, Any],
    comments: list[dict[str, Any]],
    users: list[dict[str, Any]],
    config: ZendeskConfig,
) -> Verdict:
    """Is this ticket's opening message genuinely a customer's own? Fails closed: every
    field it relies on must be present and say so."""
    tid = _int(ticket.get("id")) or 0

    def no(reason: str) -> Verdict:
        return Verdict(tid, False, reason)

    requester, submitter = _int(ticket.get("requester_id")), _int(ticket.get("submitter_id"))
    if not tid or requester is None or submitter is None:
        return no("missing_fields")
    if requester in config.exclude_requester_ids:
        return no("excluded_requester")
    group = _int(ticket.get("group_id"))
    if group is not None and group in config.exclude_group_ids:
        return no("excluded_group")
    if config.exclude_tags & {str(t).lower() for t in ticket.get("tags") or []}:
        return no("excluded_tag")
    channel = ((ticket.get("via") or {}).get("channel") or "").lower()
    if not channel:
        return no("missing_fields")
    if channel in NON_CUSTOMER_CHANNELS:
        return no("not_typed_by_customer")
    if submitter != requester:
        return no("submitted_for_customer")  # an agent opened it on their behalf

    if not comments:
        return no("no_comments")
    first = comments[0]  # Zendesk returns oldest first
    if first.get("public") is not True:
        return no("first_comment_not_public")
    if _int(first.get("author_id")) != requester:
        return no("author_not_requester")
    author = next((u for u in users if _int(u.get("id")) == requester), None)
    if author is None:
        return no("unknown_author")
    if author.get("role") != "end-user":
        return no("requester_not_end_user")
    if channel == "email" and config.staff_domains:
        address = str(
            (((first.get("via") or {}).get("source") or {}).get("from") or {}).get("address") or ""
        )
        if address.rsplit("@", 1)[-1].lower() in config.staff_domains:
            return no("staff_email")

    body = first_part(str(first.get("plain_body") or first.get("body") or ""))
    if not body:
        return no("empty_message")
    return Verdict(tid, True, "ok", subject=str(ticket.get("subject") or "")[:300], message=body)


# ------------------------------------------------------------------ reader


class ZendeskReader:
    def __init__(
        self,
        config: ZendeskConfig,
        transport: Transport | None = None,
        *,
        sleep: Callable[[float], None] = time.sleep,
        rng: random.Random | None = None,
        attempts: int = 4,
        timeout: float = 20.0,
    ) -> None:
        self.config = config
        self.transport = transport or UrllibTransport()
        self.sleep, self.rng, self.attempts, self.timeout = (
            sleep,
            rng or random.Random(),
            attempts,
            timeout,
        )
        auth = base64.b64encode(f"{config.email}/token:{config.token}".encode()).decode()
        self._headers = {"Authorization": f"Basic {auth}", "Accept": "application/json"}

    # -- plumbing
    def _get(self, path: str, **params: Any) -> dict[str, Any]:
        query = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
        url = f"{self.config.base}{path}" + (f"?{query}" if query else "")
        for attempt in range(1, self.attempts + 1):
            reply = self.transport.get(url, self._headers, self.timeout)
            if reply.status == 429 or reply.status >= 500:
                if attempt == self.attempts:
                    raise ZendeskError("Zendesk is busy or unavailable. Try again later.")
                try:
                    wait = float(reply.headers.get("retry-after", ""))
                except ValueError:
                    wait = 2.0 * attempt
                self.sleep(min(max(wait, 0.5), 30.0))
                continue
            if reply.status in (401, 403):
                raise ZendeskError(
                    "Zendesk refused the credentials (check the token and its permissions)."
                )
            if reply.status != 200:
                raise ZendeskError(f"Zendesk answered {reply.status}.")
            try:
                data = json.loads(reply.body.decode("utf-8"))
            except ValueError as exc:
                raise ZendeskError("Zendesk sent something unreadable.") from exc
            if not isinstance(data, dict):
                raise ZendeskError("Zendesk sent something unexpected.")
            return data
        raise ZendeskError("Zendesk is busy or unavailable. Try again later.")  # pragma: no cover

    # -- what we read
    def form_ids(self) -> set[int]:
        forms = self._get("/ticket_forms.json").get("ticket_forms") or []
        names = {n.lower() for n in self.config.form_names}
        return {
            f["id"]
            for f in forms
            if isinstance(f, dict) and str(f.get("name", "")).lower() in names
        }

    def _closed_tickets(self, want: int, form_ids: set[int]) -> list[dict[str, Any]]:
        """A random spread of closed tickets from the allowed forms."""
        query = {"query": "type:ticket status:closed", "per_page": SEARCH_PAGE_SIZE}
        first = self._get("/search.json", page=1, **query)
        count = first.get("count")
        total = count if isinstance(count, int) and not isinstance(count, bool) else 0
        pages = max(1, min(SEARCH_MAX_PAGES, math.ceil(total / SEARCH_PAGE_SIZE)))
        order = self.rng.sample(range(1, pages + 1), pages)
        found: dict[int, dict[str, Any]] = {}
        for page in order:
            data = first if page == 1 else self._get("/search.json", page=page, **query)
            for t in data.get("results") or []:
                if isinstance(t, dict) and isinstance(t.get("id"), int):
                    if not form_ids or t.get("ticket_form_id") in form_ids:
                        found[t["id"]] = t
            if len(found) >= want:
                break
        tickets = list(found.values())
        self.rng.shuffle(tickets)
        return tickets

    def judge_next(self, ticket: dict[str, Any]) -> Verdict:
        data = self._get(
            f"/tickets/{ticket['id']}/comments.json", include="users", sort_order="asc"
        )
        return judge_ticket(
            ticket, data.get("comments") or [], data.get("users") or [], self.config
        )

    def sample(self, count: int, *, exclude_ids: set[int] | None = None) -> list[Verdict]:
        """Up to `count` accepted tickets plus a verdict for every ticket examined.
        Examines at most `count * 6` tickets, so a stretch of rejects can't run away."""
        skip = exclude_ids or set()
        budget = max(count * 6, count)
        verdicts: list[Verdict] = []
        accepted = 0
        for ticket in self._closed_tickets(budget, self.form_ids()):
            if accepted >= count or len(verdicts) >= budget:
                break
            if ticket["id"] in skip:
                continue
            verdict = self.judge_next(ticket)
            verdicts.append(verdict)
            accepted += verdict.accepted
        return verdicts


@dataclass
class AuditSummary:
    examined: int = 0
    accepted: int = 0
    reasons: Counter = field(default_factory=Counter)
    accepted_ids: list[int] = field(default_factory=list)
    rejected_ids: dict[str, list[int]] = field(default_factory=dict)

    @classmethod
    def of(cls, verdicts: list[Verdict]) -> AuditSummary:
        out = cls(examined=len(verdicts))
        for v in verdicts:
            if v.accepted:
                out.accepted += 1
                out.accepted_ids.append(v.ticket_id)
            else:
                out.reasons[v.reason] += 1
                out.rejected_ids.setdefault(v.reason, []).append(v.ticket_id)
        return out

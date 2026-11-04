"""The Zendesk reader: read-only, and it only trusts a customer's own words.

No network: a fake transport answers from canned Zendesk-shaped data and records every
request. Nothing here proves how a real Zendesk behaves — that needs credentials and the
data-protection sign-off, and is reported as not run.
"""

import base64
import json
import random

import pytest

from apps.bot_sim import zendesk
from apps.bot_sim.zendesk import (
    AuditSummary,
    Response,
    ZendeskConfig,
    ZendeskError,
    ZendeskNotConfigured,
    ZendeskReader,
    first_part,
    judge_ticket,
)

CUSTOMER, AGENT, BOT = 1001, 2002, 3003
CFG = ZendeskConfig(
    subdomain="acme",
    email="ops@acme.io",
    token="SECRET-TOKEN-123",
    exclude_requester_ids=frozenset({BOT}),
    exclude_group_ids=frozenset({77}),
    exclude_tags=frozenset({"simbot"}),
    staff_domains=frozenset({"hevodata.com"}),
)
USERS = [
    {"id": CUSTOMER, "role": "end-user"},
    {"id": AGENT, "role": "agent"},
    {"id": BOT, "role": "admin"},
]


def ticket(**over):
    base = {
        "id": 1, "subject": "Connecting MySQL", "requester_id": CUSTOMER, "submitter_id": CUSTOMER,
        "ticket_form_id": 5, "group_id": 10, "tags": [], "via": {"channel": "web"},
    }  # fmt: skip
    return {**base, **over}


def comment(**over):
    base = {"id": 9, "author_id": CUSTOMER, "public": True, "plain_body": "How do I connect MySQL?"}
    return {**base, **over}


def judge(t=None, comments=None, users=None, cfg=CFG):
    return judge_ticket(
        t or ticket(),
        [comment()] if comments is None else comments,
        USERS if users is None else users,
        cfg,
    )


class TestOnlyACustomersOwnWords:
    def test_a_genuine_customer_ticket_is_accepted(self):
        v = judge()
        assert v.accepted and v.reason == "ok" and v.message == "How do I connect MySQL?"
        assert v.subject == "Connecting MySQL"

    @pytest.mark.parametrize(
        ("name", "t", "comments", "reason"),
        [
            (
                "created through the API (the old bot's own tickets)",
                ticket(via={"channel": "api"}),
                None,
                "not_typed_by_customer",
            ),
            ("created by a rule", ticket(via={"channel": "rule"}), None, "not_typed_by_customer"),
            (
                "created by the system",
                ticket(via={"channel": "system"}),
                None,
                "not_typed_by_customer",
            ),
            (
                "opened by an agent for the customer",
                ticket(submitter_id=AGENT),
                None,
                "submitted_for_customer",
            ),
            (
                "requester is the old bot",
                ticket(requester_id=BOT, submitter_id=BOT),
                [comment(author_id=BOT)],
                "excluded_requester",
            ),
            ("in the old bot's group", ticket(group_id=77), None, "excluded_group"),
            ("tagged by the old bot", ticket(tags=["Billing", "SimBot"]), None, "excluded_tag"),
            (
                "first comment is an agent's",
                ticket(),
                [comment(author_id=AGENT)],
                "author_not_requester",
            ),
            (
                "first comment is an internal note",
                ticket(),
                [comment(public=False)],
                "first_comment_not_public",
            ),
            (
                "public flag missing",
                ticket(),
                [{"id": 9, "author_id": CUSTOMER, "plain_body": "hi"}],
                "first_comment_not_public",
            ),
            ("no comments at all", ticket(), [], "no_comments"),
            ("empty message", ticket(), [comment(plain_body="   ")], "empty_message"),
            ("requester missing", ticket(requester_id=None), None, "missing_fields"),
            ("submitter missing", ticket(submitter_id=None), None, "missing_fields"),
            ("via missing", ticket(via=None), None, "missing_fields"),
            ("id missing", ticket(id=None), None, "missing_fields"),
        ],
    )
    def test_everything_else_is_rejected_with_a_named_reason(self, name, t, comments, reason):
        v = judge(t, comments)
        assert not v.accepted and v.reason == reason, name
        assert v.message == ""  # no text is carried for a rejected ticket

    def test_the_requester_must_be_a_known_end_user(self):
        assert judge(users=[]).reason == "unknown_author"
        staff = [{"id": CUSTOMER, "role": "agent"}]
        assert judge(users=staff).reason == "requester_not_end_user"
        assert judge(users=[{"id": CUSTOMER}]).reason == "requester_not_end_user"

    def test_an_email_from_a_staff_address_is_rejected(self):
        via = {"channel": "email", "source": {"from": {"address": "Sam@HevoData.com"}}}
        v = judge(ticket(via={"channel": "email"}), [comment(via=via)])
        assert v.reason == "staff_email"
        ok = {"channel": "email", "source": {"from": {"address": "pat@customer.org"}}}
        assert judge(ticket(via={"channel": "email"}), [comment(via=ok)]).accepted

    def test_only_the_first_comment_counts(self):
        v = judge(comments=[comment(), comment(author_id=AGENT, plain_body="Try this")])
        assert v.accepted and "Try this" not in v.message

    def test_a_boolean_is_not_an_id(self):
        assert judge(ticket(requester_id=True, submitter_id=True)).reason == "missing_fields"


class TestTheMessageText:
    def test_a_quoted_earlier_thread_is_cut(self):
        body = "How do I connect MySQL?\n\nOn Mon, 5 Jan 2026 at 10:00, Sam wrote:\n> Try X"
        assert first_part(body) == "How do I connect MySQL?"

    def test_it_is_capped_and_whitespace_collapsed(self):
        assert len(first_part("word " * 400)) <= zendesk.MAX_BODY
        assert first_part("a\n\n  b\tc") == "a b c"


# ------------------------------------------------------------------ the reader


class FakeZendesk:
    """Answers GETs from canned data and remembers what it was asked."""

    def __init__(self, tickets, comments=None, forms=None, pages=1, scripted=None):
        self.tickets, self.comments = tickets, comments or {}
        self.forms = (
            forms if forms is not None else [{"id": 5, "name": "Query"}, {"id": 6, "name": "Other"}]
        )
        self.pages, self.scripted = pages, list(scripted or [])
        self.urls: list[str] = []
        self.headers_seen: list[dict] = []

    def get(self, url, headers, timeout):
        self.urls.append(url)
        self.headers_seen.append(headers)
        if self.scripted:
            return self.scripted.pop(0)
        if "/ticket_forms.json" in url:
            return ok({"ticket_forms": self.forms})
        if "/search.json" in url:
            page = int(url.split("page=")[1].split("&")[0])
            chunk = self.tickets[(page - 1) * 100 : page * 100]
            return ok({"results": chunk, "count": len(self.tickets)})
        if "/comments.json" in url:
            tid = int(url.split("/tickets/")[1].split("/")[0])
            return ok({"comments": self.comments.get(tid, [comment()]), "users": USERS})
        return Response(404, {}, b"{}")


def ok(data):
    return Response(200, {}, json.dumps(data).encode())


def reader(fake, **kw):
    return ZendeskReader(
        CFG, fake, sleep=kw.pop("sleep", lambda s: None), rng=random.Random(1), **kw
    )


class TestSampling:
    def test_it_reads_only_and_only_from_the_account(self):
        fake = FakeZendesk([ticket(id=i) for i in range(1, 6)])
        reader(fake).sample(3)
        assert fake.urls and all(
            u.startswith("https://acme.zendesk.com/api/v2/") for u in fake.urls
        )
        # structurally read-only: the transport offers nothing but `get`
        assert [m for m in dir(zendesk.Transport) if not m.startswith("_")] == ["get"]
        assert [m for m in dir(zendesk.UrllibTransport) if not m.startswith("_")] == ["get"]

    def test_it_authenticates_with_the_token_the_zendesk_way(self):
        fake = FakeZendesk([ticket(id=1)])
        reader(fake).sample(1)
        expected = base64.b64encode(b"ops@acme.io/token:SECRET-TOKEN-123").decode()
        assert fake.headers_seen[0]["Authorization"] == f"Basic {expected}"
        assert all("SECRET-TOKEN-123" not in u for u in fake.urls)  # never in a URL

    def test_only_the_query_forms_are_used(self):
        fake = FakeZendesk([ticket(id=1, ticket_form_id=5), ticket(id=2, ticket_form_id=6)])
        verdicts = reader(fake).sample(5)
        assert [v.ticket_id for v in verdicts] == [1]

    def test_it_stops_at_the_wanted_number_and_returns_every_verdict_it_made(self):
        tickets = [ticket(id=i) for i in range(1, 30)]
        comments = {
            i: [comment(author_id=AGENT)] for i in range(1, 6)
        }  # the first five are agents'
        verdicts = reader(FakeZendesk(tickets, comments)).sample(3)
        assert sum(v.accepted for v in verdicts) == 3
        assert all(
            not v.accepted and v.reason == "author_not_requester"
            for v in verdicts
            if not v.accepted
        )
        assert len(verdicts) <= 3 * 6

    def test_a_run_of_rejects_cannot_run_away(self):
        tickets = [ticket(id=i, via={"channel": "api"}) for i in range(1, 200)]
        verdicts = reader(FakeZendesk(tickets)).sample(2)
        assert len(verdicts) == 12 and not any(v.accepted for v in verdicts)

    def test_already_imported_tickets_are_skipped_without_being_read(self):
        fake = FakeZendesk([ticket(id=1), ticket(id=2)])
        verdicts = reader(fake).sample(5, exclude_ids={1})
        assert [v.ticket_id for v in verdicts] == [2]
        assert not any("/tickets/1/comments" in u for u in fake.urls)

    def test_it_looks_across_pages(self):
        fake = FakeZendesk([ticket(id=i) for i in range(1, 251)], pages=3)
        reader(fake).sample(2)
        assert any("page=2" in u or "page=3" in u or "page=1" in u for u in fake.urls)

    def test_the_audit_counts_reasons_and_keeps_ids_not_text(self):
        tickets = [ticket(id=1), ticket(id=2, via={"channel": "api"}), ticket(id=3, group_id=77)]
        summary = AuditSummary.of(reader(FakeZendesk(tickets)).sample(5))
        assert summary.examined == 3 and summary.accepted == 1
        assert dict(summary.reasons) == {"not_typed_by_customer": 1, "excluded_group": 1}
        assert summary.rejected_ids["excluded_group"] == [3]
        assert "How do I" not in repr(summary)


class TestTalkingToZendesk:
    def test_a_429_is_waited_out_using_retry_after(self):
        slept = []
        busy = Response(429, {"retry-after": "7"}, b"")
        fake = FakeZendesk(
            [], forms=[], scripted=[busy, ok({"ticket_forms": [{"id": 5, "name": "Query"}]})]
        )
        assert reader(fake, sleep=slept.append).form_ids() == {5}
        assert slept == [7.0]

    def test_waits_are_capped_and_given_up_on(self):
        slept = []
        busy = Response(429, {"retry-after": "9999"}, b"")
        fake = FakeZendesk([], scripted=[busy] * 4)
        with pytest.raises(ZendeskError, match="busy"):
            reader(fake, sleep=slept.append).form_ids()
        assert slept and max(slept) == 30.0 and len(fake.urls) == 4

    def test_a_server_error_is_retried_then_reported(self):
        fake = FakeZendesk([], scripted=[Response(503, {}, b"")] * 4)
        with pytest.raises(ZendeskError):
            reader(fake).form_ids()

    @pytest.mark.parametrize("status", [401, 403])
    def test_refused_credentials_are_named_without_the_token(self, status):
        fake = FakeZendesk([], scripted=[Response(status, {}, b"token SECRET-TOKEN-123 invalid")])
        with pytest.raises(ZendeskError) as caught:
            reader(fake).form_ids()
        assert "credentials" in str(caught.value) and "SECRET-TOKEN-123" not in str(caught.value)

    def test_garbage_is_an_error_not_a_crash(self):
        for body in (b"<html>", b"[1,2]"):
            fake = FakeZendesk([], scripted=[Response(200, {}, body)])
            with pytest.raises(ZendeskError):
                reader(fake).form_ids()

    def test_other_statuses_say_what_they_were(self):
        fake = FakeZendesk([], scripted=[Response(404, {}, b"")])
        with pytest.raises(ZendeskError, match="404"):
            reader(fake).form_ids()


class TestConfig:
    @pytest.mark.parametrize(
        "subdomain", ["", "evil.com/x", "a.b", "Acme", "-x", "x" * 70, "acme.zendesk.com", "a b"]
    )
    def test_a_subdomain_that_could_point_elsewhere_is_refused(self, subdomain):
        with pytest.raises(ZendeskNotConfigured):
            ZendeskConfig(subdomain=subdomain, email="a@b.c", token="t")

    def test_credentials_are_required(self):
        with pytest.raises(ZendeskNotConfigured):
            ZendeskConfig(subdomain="acme", email="", token="t")
        with pytest.raises(ZendeskNotConfigured):
            ZendeskConfig(subdomain="acme", email="a@b.c", token="")

    def test_it_reads_the_django_settings(self, settings):
        settings.ZENDESK_SUBDOMAIN, settings.ZENDESK_EMAIL, settings.ZENDESK_API_TOKEN = (
            "acme",
            "a@b.c",
            "t",
        )
        settings.ZENDESK_EXCLUDE_TAGS = ["SimBot"]
        settings.ZENDESK_EXCLUDE_REQUESTER_IDS = [5]
        cfg = ZendeskConfig.from_settings()
        assert cfg.exclude_tags == {"simbot"} and cfg.exclude_requester_ids == {5}
        assert zendesk.configured() is True
        settings.ZENDESK_API_TOKEN = ""
        assert zendesk.configured() is False

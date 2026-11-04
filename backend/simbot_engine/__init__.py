"""The practice-ticket engine: a customer persona, an AI "customer" that replies in
character, and a scorer for the intern's replies.

**This package never imports Django, Celery or any database code.** It talks to
the outside world through exactly one interface (`llm.LLMClient`) and works on
plain dataclasses, so it can run inside the platform's worker today and behind a
standalone service tomorrow: wrap it in HTTP, move the adapters. (A test enforces
the "no Django" rule.)

Ported from the standalone Zendesk-driven practice bot with the same personas,
topics, customer prompt, five scored dimensions, deterministic turnaround score
and weights. Not ported: Zendesk, polling threads, CSV output, the CLI.
"""

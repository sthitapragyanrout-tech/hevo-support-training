"""A tiny in-memory adapter that drives the engine end to end with no Django, no
database and no queue. It is both a test helper and the proof that the engine can
live behind a different adapter (a standalone service) than the platform's."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from simbot_engine import outcome
from simbot_engine.config import EngineConfig
from simbot_engine.customer import CustomerStep, customer_reply
from simbot_engine.evaluator import score_turn
from simbot_engine.llm import LLMClient
from simbot_engine.narrative import write_narrative
from simbot_engine.scenario import Scenario
from simbot_engine.session import CUSTOMER, INTERN, Turn, should_close, tat_seconds

T0 = datetime(2026, 1, 5, 9, 0, tzinfo=UTC)

SCENARIO = Scenario(
    topic="source_setup",
    persona_type="non-technical",
    issue_summary="How do I set up a MySQL source?",
    opening_message="Hello, how do I connect my MySQL database to Hevo?",
    personality_notes="Polite, unsure about jargon, wants simple steps.",
    doc_hints=("mysql", "source", "prerequisites"),
)


class Runner:
    def __init__(
        self,
        llm: LLMClient,
        config: EngineConfig | None = None,
        scenario: Scenario = SCENARIO,
        started_at: datetime = T0,
    ):
        self.llm = llm
        self.config = config or EngineConfig()
        self.scenario = scenario
        self.clock = started_at
        self.turns: list[Turn] = [Turn(1, CUSTOMER, scenario.opening_message, started_at)]
        self.closed = False

    def reply(self, text: str, *, after: float = 120) -> CustomerStep:
        """The intern replies `after` seconds after the customer's last message."""
        at = self.turns[-1].at + timedelta(seconds=after)
        tat = tat_seconds(self.turns, at)
        intern = Turn(len(self.turns) + 1, INTERN, text, at)
        intern.scores = score_turn(self.llm, self.config, self.scenario, self.turns, text, tat)
        self.turns.append(intern)
        step = customer_reply(self.llm, self.config, self.scenario, self.turns)
        self.turns.append(
            Turn(
                len(self.turns) + 1, CUSTOMER, step.message, at + timedelta(seconds=3), step.action
            )
        )
        self.closed = should_close(step.action, self.turns, self.config)
        return step

    def finish(self, threshold: float = 0.7, narrative: bool = True) -> dict:
        story = (
            write_narrative(self.llm, self.config, self.scenario, self.turns) if narrative else None
        )
        return outcome.build(
            self.turns,
            config=self.config,
            scenario=self.scenario,
            pass_threshold=threshold,
            narrative=story,
        )

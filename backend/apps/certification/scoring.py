"""The course score behind a certificate — an interim rule until the scoring questions in
`docs/scoring-open-questions.md` are settled. Everything that changes the result is data on the
course's `CertificatePolicy` (threshold, weights); this is the one function to replace.

Every scored item becomes a fraction 0–1:
  quiz              its best score
  practice ticket   the average of the learner's scored tickets (out of 5, so /5)
  mentor-rated      the latest rated revision's score (out of 5, so /5); waived work is left out
Each kind is averaged over its items that have a result, then the kinds are combined as a
weighted average using the policy's weights. A kind with weight 0 is ignored; a kind the course
doesn't have drops out and the others share its weight. Readings and videos have no score: they
count through lesson completion.
"""

from __future__ import annotations

from typing import Any

KINDS = ("quiz", "practice", "rated")


def _values(course: dict[str, Any]) -> dict[str, tuple[int, list[float]]]:
    """{kind: (items of that kind in the course, [scores 0–1 of the items with a result])}."""
    quizzes = course.get("quizzes", [])
    practice = course.get("practice", [])
    rated = [r for r in course.get("rated", []) if r.get("status") != "waived"]
    return {
        "quiz": (len(quizzes), [q["best"] for q in quizzes if q.get("best") is not None]),
        "practice": (
            len(practice),
            [t["average"] / 5 for t in practice if t.get("average") is not None],
        ),
        "rated": (
            len(rated),
            [r["last_score"] / 5 for r in rated if r.get("last_score") is not None],
        ),
    }


def course_score(course: dict[str, Any], weights: dict[str, int]) -> dict[str, Any]:
    """`course` is the internal per-course summary (with mentor scores). Returns
    {"score": 0–1 or None, "parts": {kind: {average, scored, items, weight}},
     "missing": [kinds with weight whose items have no result yet]}."""
    parts: dict[str, dict[str, Any]] = {}
    missing: list[str] = []
    total = weighted = 0.0
    for kind, (items, scores) in _values(course).items():
        weight = max(int(weights.get(kind, 0) or 0), 0)
        average = round(sum(scores) / len(scores), 4) if scores else None
        parts[kind] = {"average": average, "scored": len(scores), "items": items, "weight": weight}
        if not items or weight == 0:
            continue
        if average is None:
            missing.append(kind)
            continue
        total += weight
        weighted += weight * average
    score = round(weighted / total, 4) if total else None
    return {"score": score, "parts": parts, "missing": missing}


def has_scored_work(course: dict[str, Any], weights: dict[str, int]) -> bool:
    return any(items and weights.get(kind, 0) for kind, (items, _) in _values(course).items())

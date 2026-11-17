"""J-3 (D-1222): the tasks the journey review says belong on a phone (``docs/reviews/2026-11-17-journey-and-simplicity.md``,
section E, "Which tasks belong on a phone"), and which of them ``tests/e2e/phone_walk.js`` does on a phone.

One row per row of the review's table, in its order and words. ``walk`` names the walk's task; a row the walk does not
do says why in ``other`` (another card, or not for a phone). ``taps_before`` is the review's count on master."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

REVIEW = Path(__file__).resolve().parents[2] / "docs" / "reviews" / "2026-11-17-journey-and-simplicity.md"
LANGS = ("en", "zh-TW", "ja")
VISIT = (
    "not walked: saving a visit changes the seeded record and has no undo; its form is the entry form the SAE task "
    "walks, with the same guard"
)


@dataclass(frozen=True)
class Task:
    task: str  # the review's words
    role: str
    taps_before: str  # the review's count, at 390 px on master
    walk: str = ""  # the walk's task (phone_walk.js), or empty
    other: str = ""  # why the walk does not do it


TASKS: tuple[Task, ...] = (
    Task("Open the morning list from the mail", "PI", "1 + sign-in", walk="mail_list"),
    Task("Read a candidate's evidence", "PI", "1", walk="evidence"),
    Task("Mark Approach / Need info", "PI", "2", walk="mark"),
    Task("Mark Not suitable", "PI", "4", walk="not_suitable"),
    Task("Acknowledge an SAE", "PI", "2", other="not this card: R34 (SAE acknowledgement in two steps)"),
    Task("The task list", "Coordinator", "0", walk="tasks"),
    Task("Record a contact outcome", "Coordinator", "2", walk="outcome"),
    Task("Mark a visit done", "Coordinator", "4", other=VISIT),
    Task("Report an SAE", "Coordinator", "3 + the fields", walk="sae_form"),
    Task("Look up a participant", "Both", "type the number", walk="lookup"),
    Task("Sign pre-filled EDC values", "Coordinator", "many", other="not this card: R38 (EDC review as cards, lane E)"),
    Task("Approve criteria", "PI", "–", other="not for a phone (the review: read there, approve at a desk)"),
)


def walked() -> list[str]:
    return [t.walk for t in TASKS if t.walk]


def review_rows(text: str | None = None) -> list[tuple[str, str]]:
    """(task, role) of each row of the review's table "Which tasks belong on a phone"."""
    text = REVIEW.read_text(encoding="utf-8") if text is None else text
    part = text.split("### Which tasks belong on a phone", 1)[1].split("\n\n", 2)[1]
    rows = [r.strip().strip("|").split("|") for r in part.splitlines() if r.startswith("|")][2:]
    return [(c[0].strip(), c[1].strip()) for c in rows]

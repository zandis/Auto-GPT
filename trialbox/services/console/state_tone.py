"""One state badge, one table of tones (9k-4, D-1380; plan 9 rev 2 band 9k, review 09 DS-4).

A badge in a console page is ``<span class="pill" data-tone="ok">The state's word</span>``. The tone is one of five
(``ok``, ``warn``, ``bad``, ``info``, ``neutral``) and comes from this table alone, keyed by the family of the state
and the state itself, where the family names whose state it is. The word is the meaning; the colour only repeats it.
A state this table does not know is ``neutral`` (never an error on a page); ``tests/unit/test_state_tone_9k4.py``
holds that every state the code can produce has a row here, so a new state cannot appear without a tone.

The person's states are those of ``console.person_state`` (J-2, D-1221); the other families keep the colours the
60 old classes (``ps-``, ``ref-``, ``tier-`` ...) gave them, value for value.
"""

from __future__ import annotations

TONES = ("ok", "warn", "bad", "info", "neutral")

# family -> {state: tone}
STATE_TONES: dict[str, dict[str, str]] = {
    # a person's one state (console.person_state.STATES, "unknown" for a state not in the list)
    "person": {
        "listed": "neutral",
        "need_info": "warn",
        "set_aside": "bad",
        "to_contact": "warn",
        "contacted": "warn",
        "not_approached": "bad",
        "declined": "bad",
        "screen_fail": "bad",
        "consented": "ok",
        "enrolled": "ok",
        "on_study": "ok",
        "completed": "ok",
        "withdrawn": "bad",
        "unknown": "neutral",
    },
    # the life-cycle step of a participant (lifecycle_pages.STATES)
    "life": {
        "candidate": "neutral",
        "approached": "neutral",
        "consented": "ok",
        "enrolled": "ok",
        "on_study": "ok",
        "completed": "ok",
        "withdrawn": "bad",
        "screen_fail": "bad",
    },
    # a planned visit
    "visit": {
        "done": "ok",
        "open": "warn",
        "due": "neutral",
        "overdue": "bad",
        "missed": "bad",
        "stopped": "neutral",
        "unplanned": "neutral",
    },
    # a referral to a doctor (teamstore.STATES)
    "referral": {"asked": "warn", "discuss": "warn", "agreed": "ok", "declined": "bad"},
    # a candidate's tier
    "tier": {"high": "ok", "review": "warn", "excluded": "bad"},
    # a study's or a site's reading (green, amber, red as go, conditional, nogo)
    "reading": {"go": "ok", "conditional": "warn", "nogo": "bad"},
    # a criterion's verdict
    "verdict": {"pass": "ok", "fail": "bad", "unknown": "warn", "pending_human": "info"},
    # a coordinator's mark on a candidate
    "mark": {"approach": "ok", "need_info": "warn", "not_suitable": "bad", "not_now": "bad"},
    # a candidate's status on the weekly list
    "status": {"new": "warn"},
    # a site's patient
    "site_patient": {"ready": "ok", "needs": "warn", "not_eligible": "bad"},
    # a job
    "job": {
        "done": "ok",
        "failed": "bad",
        "cancelled": "bad",
        "awaiting_approval": "warn",
        "running": "info",
        "received": "info",
        "parsing": "info",
        "compiling": "info",
        "reporting": "info",
    },
}


def tone(family: str, state: object) -> str:
    """The tone of a state: one of :data:`TONES`; ``neutral`` for a family or a state the table does not know."""
    return STATE_TONES.get(family, {}).get(str(state), "neutral")

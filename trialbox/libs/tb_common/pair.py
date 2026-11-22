"""The two-model rule, in one place (TB-PLAN-03 step 3, D-118).

Both screening paths (the v1 ``NoteJudge`` that NAV, MICROBATCH and CASE run, and the v4 cascade that SCREEN runs,
through ``OrchestratorJudge``) and the cascade's own ``AgreementJudge`` (offline tools) decide a note answer with
:func:`combine`. Before D-118 each carried its own copy, so the path SCREEN ran was not the one the tests covered
(Fable review 2026-11-08, finding 4).

The rule:

1. the judge's answer stands alone when no verifier is configured (the note-block policy then never lets it exclude,
   ``effective_note_block``);
2. an undecided judge answer (``unknown``) is not put to the verifier;
3. a verifier that did not answer, whose quote is not in the notes, or that gives another verdict turns the answer
   into ``unknown`` with the matching :class:`~tb_common.reasons.Reason`, never an exclusion;
4. when both agree the answer is as sure as the less sure model (``min`` of the confidences);
5. a decided answer below :data:`~tb_common.reasons.MIN_CONFIDENCE` is not used: ``unknown`` / ``low_confidence``;
6. two answers from one model are one answer (D-276): when the two votes share a served model name or a gateway
   build (``served``), the judge did not really answer (a gateway that let another build stand in, two names of one
   model): ``unknown`` / ``model_down``, counted as a failure, never an exclusion (review LLM-002).
   :func:`same_model` asks the same of the two configured clients before a run.
7. an exclusion's "present" from the notes stands only on a quote that states its condition (D-985): a negated,
   relative's, rule-out, suspected, drug or value quote goes to review on every path (:func:`inferred_exclusion`).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from tb_common.reasons import MIN_CONFIDENCE, Reason

DECIDED = ("pass", "fail")


@dataclass(frozen=True)
class Vote:
    """One model's answer after its quote was checked: ``reason`` is a :class:`Reason` code (``quote_not_found``
    when the quote did not verify, ``model_down`` when the model did not answer)."""

    verdict: str  # pass | fail | unknown
    confidence: float
    reason: str | None = None
    # who gave this answer (:func:`served_keys`): the served model name and, through the gateway, the build
    served: tuple[str, ...] = ()


@dataclass(frozen=True)
class Decision:
    verdict: str
    confidence: float
    reason: str | None
    disagreement: bool = False  # the verifier did not confirm a decided judge answer
    failure: bool = False  # the verifier did not answer
    same_model: bool = False  # the verifier's answer came from the judge's model (D-276)


def needs_verifier(first: Vote) -> bool:
    return first.verdict in DECIDED


def floor(v: Vote, minimum: float = MIN_CONFIDENCE) -> Decision:
    if v.verdict in DECIDED and v.confidence < minimum:
        return Decision("unknown", 0.0, Reason.LOW_CONFIDENCE.value)
    return Decision(v.verdict, v.confidence, v.reason)


def combine(first: Vote, second: Vote | None, minimum: float = MIN_CONFIDENCE) -> Decision:
    """The pair's answer (see the module docstring). ``second`` is ``None`` when there is no verifier or the judge
    did not decide."""
    if second is None or not needs_verifier(first):
        return floor(first, minimum)
    if second.reason == Reason.MODEL_DOWN.value:
        return Decision("unknown", 0.0, Reason.MODEL_DOWN.value, failure=True)
    if set(first.served) & set(second.served):  # one model asked twice is not a second opinion (D-276)
        return Decision("unknown", 0.0, Reason.MODEL_DOWN.value, failure=True, same_model=True)
    if second.reason == Reason.QUOTE_NOT_FOUND.value:
        return Decision("unknown", 0.0, Reason.VERIFIER_QUOTE_MISSING.value, disagreement=True)
    if second.verdict != first.verdict:
        return Decision("unknown", 0.0, Reason.DISAGREE.value, disagreement=True)
    return floor(Vote(first.verdict, min(first.confidence, second.confidence), first.reason), minimum)


# ------------------------------------------------------------------------------------------------ D-985
#: the reason of a note exclusion whose "present" is the models' inference, the cascade's wording (D-985)
INFERRED_REASON = "inferred: the quote does not state the condition; review"


def inferred_exclusion(kind: str, condition_present: bool, quote: str | None, criterion: str) -> bool:
    """D-985 (R22-16): a note exclusion answered "condition present" on a ``quote`` that does not state the
    ``criterion``'s condition (a negated, family-history, rule-out, suspected, drug or value quote): the models'
    inference, a person looks, never an exclusion. False for an inclusion, an absent condition, or a criterion that
    is itself a value, a drug or a procedure. ``criterion`` is the criterion's text, never its note question.

    The rule reads :func:`matching.inferred.inferred`, imported here when called: a library does not import the
    services at module level."""
    if kind != "exclusion" or not condition_present:
        return False
    from matching.inferred import inferred

    return inferred(str(quote or ""), str(criterion or ""))


# ------------------------------------------------------------------------------------------------ model identity
def served_key(name: object) -> str:
    """A served model name for comparison: case folded, outer and repeated spaces dropped. Nothing else is rewritten:
    ``local/x`` and ``x`` stay two names, because one server may serve both as different models."""
    return " ".join(str(name or "").split()).casefold()


def served_keys(name: object = "", build: object = "") -> tuple[str, ...]:
    """Who gave an answer, for :class:`Vote`: the model name the server answered under and, through the gateway, the
    build (its weights digest). Two votes that share a key came from one model: the same served name (two registry
    builds of one model), or the same weights under two names. Empty when neither is known."""
    n, b = served_key(name), served_key(build)
    return tuple(k for k in (f"name:{n}" if n else "", f"build:{b}" if b else "") if k)


def _route(client: Any) -> tuple[str, str, str]:
    """(kind, address, name) a client was configured with: through the gateway its URL and the alias it asks for,
    else the endpoint's URL and the model name it sends."""
    gw = getattr(client, "gateway", None)
    if gw is not None:
        url = str(getattr(gw, "base_url", "") or "").rstrip("/").casefold()
        return "gateway", url, served_key(getattr(gw, "model", ""))
    url = str(getattr(client, "base_url", "") or "").rstrip("/").casefold()
    return "direct", url, served_key(getattr(client, "model", ""))


def gateway_default_alias(env: str | None = None) -> str:
    """The build alias the gateway gives a judge call that names none: the stub in DEV and TEST, the judge build
    (``j-workhorse``) elsewhere (``models/routing.yaml``: the first build of the judge's route)."""
    from tb_common.config import environment_name

    e = env if env is not None else environment_name(os.environ)
    return "trialbox-stub" if str(e).upper() in ("DEV", "TEST") else "j-workhorse"


def served_root(client: Any) -> str | None:
    """Which weights a direct client's model is served from, as its endpoint says (vLLM's ``/models``: ``root`` is
    the weights path, the same for every ``--served-model-name`` of one server, on any URL that reaches it). None
    when it cannot be told: no ``/models``, an error or a time-out, the name not listed, or no ``root``. A client
    that knows it (``served_root`` attribute: a pinned client, a test double) says so itself."""
    known = getattr(client, "served_root", None)
    if isinstance(known, str):
        return served_key(known) or None
    name = served_key(getattr(client, "model", ""))
    try:
        resp = client.http.get(f"{str(client.base_url).rstrip('/')}/models", timeout=10.0)
        if resp.status_code >= 400:
            return None
        for m in resp.json().get("data") or []:
            if served_key(m.get("id")) == name:
                return served_key(m.get("root")) or None
    except Exception:  # an endpoint without /models, a network error, a time-out: not known
        return None
    return None


def same_model(judge: Any, verifier: Any) -> str | None:
    """Why the verifier is not a second model, or None when the box can tell before a run that it is (D-276,
    reviews S-2, F-02, F-03). The answers themselves are compared again by :func:`combine`.

    Fails closed: "cannot tell" counts as one model. One model: one client object; the same gateway asked for the
    same alias (a judge that names none gets :func:`gateway_default_alias`); a direct client with no name; two direct
    clients asking for one model name (whatever their URLs); two direct models served from the same weights, on any
    URLs (:func:`served_root`); a direct model whose weights its endpoint does not tell; one client through the
    gateway and the other straight to an endpoint (their identities cannot be compared)."""
    if verifier is judge:
        return "the verifier is the judge's own client"
    (jk, ju, jn), (vk, vu, vn) = _route(judge), _route(verifier)
    if jk == vk == "gateway":
        jn, vn = jn or served_key(gateway_default_alias()), vn or served_key(gateway_default_alias())
        if ju == vu and jn == vn:
            return f"both ask the same gateway for {jn}"
        return None
    if jk != vk:
        return "one model is reached through the gateway and the other directly, so they cannot be told apart"
    if not jn or not vn:
        return "a model has no name"
    if jn == vn:
        return f"both are the model {jn}"
    jr, vr = served_root(judge), served_root(verifier)
    if jr is None or vr is None:
        which = jn if jr is None else vn
        return (
            f"the endpoint of {which} does not say which weights it serves (/models), so the pair cannot be told apart"
        )
    if jr == vr:
        return f"{jn} and {vn} are served from the same weights ({jr})"
    return None


__all__ = [
    "DECIDED",
    "INFERRED_REASON",
    "Decision",
    "Vote",
    "combine",
    "floor",
    "gateway_default_alias",
    "inferred_exclusion",
    "needs_verifier",
    "same_model",
    "served_key",
    "served_keys",
    "served_root",
]

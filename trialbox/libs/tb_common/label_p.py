"""Lane G (HOLISTIC-2 §5.2, FINAL-SPEC §5.2, G2): the judge's P(met) from its label tokens.

The judge answers in a schema with a ``verdict`` of ``pass``, ``fail`` or ``unknown``. With ``logprobs`` asked for
(G1, through the gateway) the server returns, for each token it wrote, that token's log-probability and its
``top_logprobs`` alternatives. :func:`slots` finds the token where each ``verdict`` value begins, in output order (one
slot per criterion of a ``judge_chart`` answer, one for a ``judge`` answer), and sums the probability of every
alternative that spells the start of a label. The pinned server returns raw log-probabilities (vLLM
``logprobs_mode = raw_logprobs``, its default: before the grammar mask, which does not renormalise), so the three
labels are renormalised here over themselves.

:func:`p_met` applies one temperature to the three labels and reads ``pass`` plus a share ``u`` of ``unknown``.
With no fit, ``u`` is one half (an abstention says nothing either way). Both are fitted together on public or licensed
labelled rows (:func:`fit`: the share of abstentions the labels count as "met" is the content-free prior of
``unknown``; on a set whose gold reads an unmentioned fact as not met, ``u`` goes to 0), and the :func:`record` (the
set's sha, the rows, T, u, the ECE before and after, the prompt and the pin) goes into the bundle; a pin change
invalidates it. P never decides: the three-valued verdict stays the record (D-1069), and P only orders and labels.
"""

from __future__ import annotations

import bisect
import hashlib
import json
import math
import re
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

LABELS = ("pass", "fail", "unknown")
_SLOT = re.compile(r'"verdict"\s*:\s*"')
_EPS = 1e-9


def slots(tokens: Sequence[Mapping[str, Any]]) -> list[dict[str, float] | None]:
    """Per ``verdict`` value in the answer, in order: label -> probability over the three labels, or None when no
    alternative at that token spells a label. ``tokens``: ``choices[0].logprobs.content`` of an OpenAI-shaped reply."""
    text, offs = "", []
    for t in tokens:
        offs.append(len(text))
        text += str(t.get("token", ""))
    out: list[dict[str, float] | None] = []
    for m in _SLOT.finditer(text):
        if m.end() >= len(text):
            break
        k = bisect.bisect_right(offs, m.end()) - 1
        head = text[offs[k] : m.end()]  # the part of this token before the value (the opening quote, a space)
        mass = dict.fromkeys(LABELS, 0.0)
        seen: set[str] = set()
        for alt in [*(tokens[k].get("top_logprobs") or []), tokens[k]]:
            raw = str(alt.get("token", ""))
            if raw in seen or not raw.startswith(head):
                continue
            seen.add(raw)
            spelt = raw[len(head) :]
            label = next((lab for lab in LABELS if spelt and lab.startswith(spelt)), None)
            if label is not None:
                mass[label] += math.exp(float(alt.get("logprob", -math.inf)))
        z = sum(mass.values())
        out.append({lab: v / z for lab, v in mass.items()} if z > 0 else None)
    return out


def scaled(p3: Mapping[str, float], temperature: float) -> dict[str, float]:
    """The three label probabilities under one temperature (softmax of log p / T)."""
    logs = {lab: math.log(max(float(p3.get(lab, 0.0)), _EPS)) / temperature for lab in LABELS}
    top = max(logs.values())
    e = {lab: math.exp(v - top) for lab, v in logs.items()}
    z = sum(e.values())
    return {lab: v / z for lab, v in e.items()}


def p_met(p3: Mapping[str, float], temperature: float = 1.0, unknown: float = 0.5) -> float:
    """P(the criterion's note question is answered yes): ``pass`` plus the share ``unknown`` of ``unknown``, after the
    temperature, rounded so a repeat is byte-identical. Strictly between 0 and 1."""
    s = scaled(p3, temperature)
    return min(max(round(s["pass"] + unknown * s["unknown"], 6), 1e-6), 1 - 1e-6)


def _nll(rows: Sequence[tuple[Mapping[str, float], bool]], temperature: float, unknown: float = 0.5) -> float:
    total = 0.0
    for p3, met in rows:
        p = p_met(p3, temperature, unknown)
        total -= math.log(p if met else 1 - p)
    return total / max(1, len(rows))


#: the temperatures tried: 0.05 to 50, log-spaced (the bench's grid, bench6 ``fit_T``)
GRID = tuple(math.exp(math.log(0.05) + i * (math.log(50) - math.log(0.05)) / 199) for i in range(200))


#: the shares of ``unknown`` tried: 0 to 1 in twentieths
SHARES = tuple(i / 20 for i in range(21))


def fit(rows: Sequence[tuple[Mapping[str, float], bool]]) -> tuple[float, float]:
    """The temperature and the share of ``unknown`` with the least negative log-likelihood of the gold "met" over
    ``rows`` (label probs, met); ties go to the smaller temperature, then to the share nearest one half."""
    best = min(((t, u) for t in GRID[::2] for u in SHARES), key=lambda tu: (_nll(rows, *tu), tu[0], abs(tu[1] - 0.5)))
    return round(best[0], 4), best[1]


def ece(ps: Sequence[float], met: Sequence[bool], bins: int = 10) -> float:
    """Expected calibration error of a yes/no probability: the confidence max(p, 1 - p) against being right."""
    n = len(ps)
    if not n:
        return 0.0
    acc: dict[int, list[tuple[float, float]]] = {}
    for p, y in zip(ps, met, strict=True):
        conf = max(p, 1 - p)
        b = min(bins - 1, int((conf - 0.5) * 2 * bins))
        acc.setdefault(b, []).append((conf, float((p >= 0.5) == y)))
    return round(
        sum(len(v) / n * abs(sum(c for c, _ in v) / len(v) - sum(o for _, o in v) / len(v)) for v in acc.values()), 4
    )


def set_sha(ids: Iterable[str]) -> str:
    """The sha256 of a labelled set's sorted row ids: which rows the fit saw, without any of their text."""
    return "sha256:" + hashlib.sha256("\n".join(sorted(ids)).encode("utf-8")).hexdigest()


def record(
    *, name: str, ids: Sequence[str], rows: Sequence[tuple[Mapping[str, float], bool]], prompt: str, pin: str, date: str
) -> dict[str, Any]:
    """The calibration record of one fit (aggregates only): set, rows, T, u, ECE raw and scaled, prompt, pin, date."""
    t, u = fit(rows)
    met = [y for _, y in rows]
    return {
        "kind": "label_p.temperature",
        "set": name,
        "set_sha": set_sha(ids),
        "rows": len(rows),
        "temperature": t,
        "unknown_weight": u,
        "ece_raw": ece([p_met(p3) for p3, _ in rows], met),
        "ece": ece([p_met(p3, t, u) for p3, _ in rows], met),
        "prompt": prompt,
        "pin": pin,
        "date": date,
    }


def record_id(rec: Mapping[str, Any]) -> str:
    """``p_calib``: the id of a calibration record, the sha256 of its canonical JSON."""
    return "sha256:" + hashlib.sha256(json.dumps(rec, sort_keys=True).encode("utf-8")).hexdigest()[:16]


__all__ = ["LABELS", "ece", "fit", "p_met", "record", "record_id", "scaled", "set_sha", "slots"]

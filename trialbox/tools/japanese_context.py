"""O-6 synthetic SCREEN rehearsal and offline A6 report."""

from __future__ import annotations

import json
import os
import re
import sys
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict, dataclass, field
from fractions import Fraction
from pathlib import Path
from threading import Lock
from typing import Any

PROFILES = {"ballast": 8192, "head-box": 32768}
MIX = "JP=ja:1.0"


def count(value: Any) -> bool:
    return type(value) is int and value >= 0


@dataclass
class Counts:
    judge_calls: int = 0
    truncated_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    missing_judge_calls: int = 0
    verifier_calls: int = 0

    def observe(self, left_out: int, usage: Any) -> None:
        raw = usage if isinstance(usage, dict) else {}
        incoming, outgoing = raw.get("prompt_tokens"), raw.get("completion_tokens")
        if raw.get("estimated") or not all(count(n) for n in (left_out, incoming, outgoing)):
            self.missing_judge_calls += 1
            return
        self.judge_calls += 1
        self.truncated_calls += left_out > 0
        self.input_tokens += incoming
        self.output_tokens += outgoing

    @property
    def share(self) -> Fraction | None:
        return Fraction(self.truncated_calls, self.judge_calls) if self.judge_calls else None


@dataclass(frozen=True)
class Provenance:
    seed: int
    patients: int
    fixture_sha256: str
    rules_sha256: str

    def __post_init__(self) -> None:
        if not count(self.seed) or not count(self.patients) or not self.patients:
            raise ValueError
        for digest in (self.fixture_sha256, self.rules_sha256):
            if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
                raise ValueError


@dataclass
class Arm:
    profile: str
    provenance: Provenance | None = None
    finished: bool = False
    counts: Counts = field(default_factory=Counts)
    contexts_verified: bool = False

    @property
    def complete(self) -> bool:
        return (
            self.finished
            and self.contexts_verified
            and self.provenance is not None
            and self.counts.judge_calls > 0
            and self.counts.missing_judge_calls == 0
        )

    @classmethod
    def read(cls, path: Path, profile: str) -> Arm:
        if not path.exists():
            return cls(profile)
        raw = json.loads(path.read_text(encoding="utf-8"))
        if (
            not isinstance(raw, dict)
            or raw["profile"] != profile
            or any(type(raw[key]) is not bool for key in ("finished", "contexts_verified"))
        ):
            raise ValueError
        if not isinstance(raw["counts"], dict) or raw["counts"].keys() != vars(Counts()).keys():
            raise ValueError
        counts = Counts(**raw["counts"])
        if not all(count(n) for n in asdict(counts).values()) or counts.truncated_calls > counts.judge_calls:
            raise ValueError
        provenance = Provenance(**raw["provenance"]) if raw["provenance"] is not None else None
        return cls(profile, provenance, raw["finished"], counts, raw["contexts_verified"])

    def write(self, path: Path) -> None:
        staging = path.with_suffix(".tmp")
        staging.write_text(json.dumps(asdict(self), indent=2) + "\n", encoding="utf-8")
        staging.replace(path)


def compare(ballast: Arm, control: Arm) -> tuple[Fraction | None, bool | None]:
    if (
        (ballast.profile, control.profile) != ("ballast", "head-box")
        or not (ballast.complete and control.complete)
        or ballast.provenance != control.provenance
    ):
        return None, None
    low, high = ballast.counts.share, control.counts.share
    assert low is not None and high is not None
    difference = 100 * (low - high)
    return difference, difference <= 2


# A scope is set only around the existing SCREEN evaluation that can issue a call.
# Gateway completion runs inside it, including separate requests for client-level retries.
_scope: ContextVar[tuple[str, int] | None] = ContextVar("o6_scope", default=None)


@contextmanager
def call_scope(role: str, left_out: int):
    token = _scope.set((role, left_out))
    try:
        yield
    finally:
        _scope.reset(token)


class ObservedGateway:
    def __init__(self, gateway: Any, arm: Arm, role: str, study_id: str, lock: Lock) -> None:
        self.gateway = gateway
        self.arm = arm
        self.role = role
        self.study_id = study_id
        self.lock = lock

    def __getattr__(self, name: str) -> Any:
        return getattr(self.gateway, name)

    def complete(self, body: dict, labels: Any) -> dict:
        scope = _scope.get()
        if scope is None or labels.study_id != self.study_id:
            return self.gateway.complete(body, labels)
        stage, left_out = scope
        judge = stage == self.role == "judge"
        usage = None
        try:
            payload = self.gateway.complete(body, labels)
            if payload.get("tb", {}).get("cache") != "hit":
                usage = payload.get("usage")
            return payload
        finally:
            with self.lock:
                if judge:
                    self.arm.counts.observe(left_out, usage)
                else:
                    self.arm.counts.verifier_calls += 1


def main() -> int:
    from tools.japanese_context_text import TEXT, render

    language = os.environ.get("TB_REPORT_LANG", "en")
    labels = TEXT.get(language, TEXT["en"])
    args = sys.argv[1:]
    try:
        if len(args) == 4 and args[0] == "capture" and args[1] in PROFILES:
            from tools.japanese_context_rehearsal import capture

            arm = capture(Path(args[2]), args[1], int(args[3]))
            print(labels["complete" if arm.complete else "incomplete"])
            return 0 if arm.complete else 2
        if len(args) == 2 and args[0] == "report":
            folder = Path(args[1])
            arms = [Arm.read(folder / f"{profile}.json", profile) for profile in PROFILES]
            print(render(*arms, language if language in TEXT else "en"), end="")
            return 0
    except (OSError, ValueError, TypeError, KeyError):
        print(labels["invalid"], file=sys.stderr)
        return 2
    print(labels["usage"], file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

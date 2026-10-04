"""Recruitment calibration used by the FEAS simulation (SPEC §8.1/§8.2): ``calibration/<RULESET>.json`` or
``calibration/site.json`` under the orchestrator data dir, else ``settings.calibration_defaults``."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from tb_contracts import Settings

DEFAULT_CONCENTRATION = 20.0


@dataclass(frozen=True)
class Calibration:
    reach_rate: float
    accept_rate: float
    source: str  # calibrated | default
    contacted: int = 0

    @property
    def concentration(self) -> float:
        """Beta concentration: the number of contacted patients behind a calibrated rate (min 20)."""
        return (
            max(float(self.contacted), DEFAULT_CONCENTRATION) if self.source == "calibrated" else DEFAULT_CONCENTRATION
        )


def load(data_dir: Path, ruleset: str, settings: Settings) -> Calibration:
    for path in (data_dir / "calibration" / f"{ruleset}.json", data_dir / "calibration" / "site.json"):
        if path.exists():
            body = json.loads(path.read_text(encoding="utf-8"))
            if body.get("reach_rate") is not None and body.get("accept_rate") is not None:
                return Calibration(
                    float(body["reach_rate"]), float(body["accept_rate"]), "calibrated", int(body.get("contacted") or 0)
                )
    d = settings.calibration_defaults
    return Calibration(
        d.reach_rate if d and d.reach_rate is not None else 0.6,
        d.accept_rate if d and d.accept_rate is not None else 0.35,
        "default",
    )

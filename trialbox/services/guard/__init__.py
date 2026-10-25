"""PHI guard service (spec v4 §7.14, §8.6; S1-08). Folds in ``tb_common.phi_guard`` by calling it."""

from guard.guard import Guard, Verdict

__all__ = ["Guard", "Verdict"]

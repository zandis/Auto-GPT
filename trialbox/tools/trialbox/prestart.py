"""The steps a release runs on the host before its stack starts (UPDATE-PRESTART).

    python3 -m tools.trialbox pre-start --deploy deploy      # run by the update path, from the install folder

An update switches the box to the new release's tree and then starts the stack with the new compose files. What
the new stack needs on the host before it starts (a secret file a new service reads, a pin the image store lost)
has to be made by the NEW release's code: the updater that is running is the installed, older one, and it cannot
know a step that did not exist when it was written. So the restart of an update runs this command as a process of
its own, in the install folder, where ``tools/`` is already the new tree (``tools/trialbox/update.py``
``ComposeBox.pre_start``).

**A release that adds a step adds it to** :data:`STEPS`. A step takes the box (``ComposeBox``: its ``deploy``
folder, its ``.env``) and returns one line for the log. It must be safe to run again, must work with the stack
down, and fails by raising ``UpdateFailed``: the update then stops before the stack starts and is rolled back.

The first release with this command cannot be helped by it: the release installed before it restarts the stack
the old way. A release that adds a step therefore names, as its ``min_installed_version``, a release that has
this command; the verifier refuses the bundle on an older box before anything is changed.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tools.trialbox.update import ComposeBox


def _image_pins(box: ComposeBox) -> str:
    box.resolve_pins()
    return "compose is pointed at the bundle's images where the image store kept no digest"


def _model_key(box: ComposeBox) -> str:
    return "made now" if box.ensure_model_key() else "in place, or not a GPU box"


#: name, step; in the order they run. The first two are what every release before this one ran in the updater itself.
STEPS: list[tuple[str, Callable[[ComposeBox], str]]] = [
    ("image pins", _image_pins),
    ("model key", _model_key),
]


def run(deploy: Path) -> list[str]:
    """Every step, in order; the lines for the log. Raises ``UpdateFailed`` at the first step that fails."""
    from tools.trialbox.update import ComposeBox

    box = ComposeBox(deploy)
    return [f"pre-start: {name}: {step(box)}" for name, step in STEPS]


def main(deploy: Path) -> int:
    from tools.trialbox.update import UpdateFailed

    try:
        for line in run(deploy):
            print(line)
    except UpdateFailed as exc:
        print(f"pre-start: failed: {exc}", file=sys.stderr)
        return 1
    return 0

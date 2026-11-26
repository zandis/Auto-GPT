"""The product's tools. A host command is typed with no ``PYTHONPATH`` (``sudo python3 -m tools...``): the release's own
``libs`` goes on the import path here, for every tool at once (R22-48; first made on the bench, F-31)."""

import sys as _sys
from pathlib import Path as _Path

_LIBS = str(_Path(__file__).resolve().parents[1] / "libs")
if _LIBS not in _sys.path:
    _sys.path.insert(0, _LIBS)

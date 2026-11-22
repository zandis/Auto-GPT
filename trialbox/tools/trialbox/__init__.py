"""The ``trialbox`` CLI (spec v4 §17.1, §18): ``doctor`` (S1-16) and ``eval`` (S1-13) in this build.

H-88: any ``python3 -m tools.trialbox...`` finds the product's own ``libs/`` from this folder's location, never from
the caller's ``PYTHONPATH`` (the entry, ``launch.enter``, also drops what that added)."""

import os as _os
import sys as _sys

_LIBS = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))), "libs")
if _LIBS not in _sys.path:
    _sys.path.insert(0, _LIBS)

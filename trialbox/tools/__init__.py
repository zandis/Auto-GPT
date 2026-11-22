"""
Top‑level package for the project's tooling.

This module ensures that the repository's ``libs`` and ``services`` directories
are available on ``sys.path`` when the tooling is executed directly (e.g.
``python -m tools.trialbox backup-keygen``).  The backup CLI commands rely on
modules such as ``tb_common`` that live in those directories, and the original
implementation required the user to set ``PYTHONPATH=libs:services:.``.
By inserting the appropriate paths here we make the commands work out‑of‑the‑box
and allow the test suite to import them without external environment tweaks.
"""

import os
import sys

# Determine the repository root (the directory containing this ``tools`` package)
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

# Directories that contain additional Python packages used by the tooling
_FORCED_PATHS = ("libs", "services")

for _name in _FORCED_PATHS:
    _path = os.path.join(_REPO_ROOT, _name)
    if os.path.isdir(_path) and _path not in sys.path:
        # Insert at the front so that repository packages take precedence
        sys.path.insert(0, _path)

# Clean up temporary names
del os, sys, _REPO_ROOT, _FORCED_PATHS, _name, _path

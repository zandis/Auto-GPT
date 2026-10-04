"""doc-parser HTTP service (phase 0: health endpoint only)."""

from __future__ import annotations

from tb_common.http import make_app

app = make_app("doc-parser")

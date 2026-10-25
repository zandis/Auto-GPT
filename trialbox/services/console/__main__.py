"""``python -m console``: serve the console with uvicorn (``PORT``, default 8090)."""

from __future__ import annotations

import os

import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "console.app:create_app",
        factory=True,
        host=os.environ.get("TB_CONSOLE_HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", "8090")),
        proxy_headers=True,
        forwarded_allow_ips=os.environ.get("TB_CONSOLE_FORWARDED_ALLOW_IPS", "127.0.0.1"),
    )

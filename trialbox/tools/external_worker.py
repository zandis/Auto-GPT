#!/usr/bin/env python3
"""External worker: one small card drafted by an outside model, checked by a command, audited by a session.

usage: python tools/external_worker.py --task TASK.md --root . --edit a.py b.py [--read c.md ...] --check "CMD"
           --log OUT.log [--new path ...] [--rounds 3]

The model gets the task, the editable files in full and the read-only files in full, and answers with whole files.
After each round the check command runs in --root; on failure its last lines go back to the model. Only the paths
named by --edit and --new can be written. Where the model lives is the caller's setting, never the repository's:
XW_API_URL (an OpenAI-compatible chat-completions address), XW_MODEL, and XW_API_KEY (a placeholder where the
session's network adds the credential itself). Nothing of these is written to the log. Token use is printed at
the end. The procedure, and what may and may not be sent out, is docs/plan/41-external-worker.md.
"""

from __future__ import annotations

import argparse
import http.client
import json
import os
import re
import subprocess
import sys
import urllib.parse
from pathlib import Path

SYSTEM = (
    "You are a careful senior Python engineer making one small change in an existing repository. Follow the task "
    "exactly. Keep the style of the files you are given. Answer ONLY with the complete new content of every file you "
    "change or create, each in this exact form and nothing else:\n\n=== FILE: <path relative to the root> ===\n"
    "```\n<the whole file>\n```\n\nNever shorten a file with an ellipsis or a comment such as 'unchanged'. Do not "
    "return a file you did not change. Only files listed as editable (or new test files the task asks for) may be "
    "returned."
)
BLOCK = re.compile(r"=== FILE: (?P<path>[^\n=]+?) ===\n```[a-zA-Z0-9]*\n(?P<body>.*?)\n```(?=\n|$)", re.S)


def call(api: str, model: str, messages: list[dict[str, str]], usage: dict[str, int]) -> str:
    # streamed, so a long answer keeps the connection alive through the proxy; two retries on a dropped connection
    body = json.dumps(
        {"model": model, "messages": messages, "temperature": 0, "stream": True,
         "stream_options": {"include_usage": True}}
    ).encode()  # fmt: skip
    url = urllib.parse.urlsplit(api)
    last: Exception | None = None
    for _ in range(3):
        parts: list[str] = []
        u: dict[str, int] = {}
        conn = http.client.HTTPSConnection(url.netloc, timeout=900)
        try:
            conn.request(
                "POST",
                url.path or "/",
                body=body,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": "Bearer " + os.environ.get("XW_API_KEY", "set-by-the-network"),
                },
            )
            r = conn.getresponse()
            if r.status != 200:
                raise OSError(f"status {r.status}")
            for raw in r:
                line = raw.decode("utf-8", "replace").strip()
                if not line.startswith("data:") or line == "data: [DONE]":
                    continue
                d = json.loads(line[5:])
                for ch in d.get("choices") or []:
                    parts.append((ch.get("delta") or {}).get("content") or "")
                if d.get("usage"):
                    u = d["usage"]
        except (OSError, ValueError) as exc:  # a dropped connection or a refusal: try again
            last = exc
            continue
        finally:
            conn.close()
        usage["in"] += int(u.get("prompt_tokens", 0))
        usage["out"] += int(u.get("completion_tokens", 0))
        return "".join(parts)
    raise RuntimeError(f"the model did not answer: {last}")


def write_files(root: Path, answer: str, allowed: set[str]) -> tuple[list[str], list[str]]:
    """Write the answer's files under ``root``; only ``allowed`` paths, never one that leaves the root."""
    written: list[str] = []
    refused: list[str] = []
    for m in BLOCK.finditer(answer):
        path = m["path"].strip()
        if path not in allowed or ".." in Path(path).parts or path.startswith("/"):
            refused.append(path)
            continue
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_text(m["body"] + "\n", encoding="utf-8")
        written.append(path)
    return written, refused


def files_block(root: Path, paths: list[str], label: str) -> str:
    out = []
    for p in paths:
        f = root / p
        text = f.read_text(encoding="utf-8") if f.exists() else ""
        out.append(f"--- {label}: {p} ---\n```\n{text}\n```")
    return "\n\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", type=Path, required=True)
    ap.add_argument("--root", type=Path, required=True)
    ap.add_argument("--edit", nargs="+", required=True)
    ap.add_argument("--read", nargs="*", default=[])
    ap.add_argument("--new", nargs="*", default=[], help="paths the model may create")
    ap.add_argument("--check", required=True)
    ap.add_argument("--rounds", type=int, default=3)
    ap.add_argument("--log", type=Path, required=True)
    a = ap.parse_args()
    api, model = os.environ.get("XW_API_URL", ""), os.environ.get("XW_MODEL", "")
    if not api.startswith("https://") or not model:
        print("external_worker: set XW_API_URL (https) and XW_MODEL", file=sys.stderr)
        return 2
    root = a.root.resolve()
    allowed = set(a.edit) | set(a.new)
    usage = {"in": 0, "out": 0}
    first = (
        a.task.read_text(encoding="utf-8")
        + "\n\n## Files\n\n"
        + files_block(root, a.edit, "EDITABLE")
        + ("\n\n" + files_block(root, a.read, "READ ONLY") if a.read else "")
    )
    messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": first}]
    ok = False
    with a.log.open("w", encoding="utf-8") as log:
        for rnd in range(1, a.rounds + 1):
            answer = call(api, model, messages, usage)
            log.write(f"\n===== round {rnd} answer =====\n{answer}\n")
            written, refused = write_files(root, answer, allowed)
            for path in refused:
                log.write(f"REFUSED path {path}\n")
            r = subprocess.run(
                ["sh", "-c", a.check], check=False, cwd=root, capture_output=True, text=True, timeout=1200
            )
            tail = (r.stdout + "\n" + r.stderr)[-6000:]
            log.write(f"\n===== round {rnd} wrote {written}; check exit {r.returncode} =====\n{tail}\n")
            print(
                f"round {rnd}: wrote {written}; check exit {r.returncode}; tokens in {usage['in']} out {usage['out']}"
            )
            if written and r.returncode == 0:
                ok = True
                break
            messages.append({"role": "assistant", "content": answer})
            fix = (
                "The check command failed. Its output (last lines) is below. Return the complete corrected files, in "
                f"the same form.\n\n```\n{tail}\n```"
                if written
                else "No file was returned in the required form. Return the complete files in the exact form asked."
            )
            messages.append({"role": "user", "content": fix})
    print(json.dumps({"ok": ok, "tokens_in": usage["in"], "tokens_out": usage["out"]}))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

"""The bench host's gate (card H-105, the security review's F1): which job may run on a bench runner at all.

A self-hosted runner registered to a public repository takes any job that names its labels, from any workflow file
of any event: a fork's pull request brings its own workflow files. The workflow on master and its test are no
boundary. This gate is: the runner's job-started hook runs it (``job_started.sh``) from the image's root-owned
``/opt/tb-bench``, before the job's first step, and a refused job ends there.

What it trusts, and why: the facts of the job come from the runner service itself, as it received them from the code
host: the ``GITHUB_*`` variables it sets for the job (a workflow cannot set a ``GITHUB_*`` variable) and the event
payload it writes (``GITHUB_EVENT_PATH``). The gate runs before any step, so no code of the job has run yet. What
the job must be comes from the host: the job file the launcher's root mint step wrote (``job.json``: the repository,
the workflow's path and master's blob of it, fetched by the host with its own credential, never by the job).

A job runs only when ALL hold:

* the event is ``push`` or ``workflow_dispatch`` (never a pull request, a comment, a run after another workflow);
* the repository is the bench's (``GITHUB_REPOSITORY`` and the payload's repository), and not a fork;
* the ref is one of the allowed branches (``train/``, ``agent/``, ``claude/``, ``lane-``; for a run by hand also
  master), one level deep, as the workflow's push filter;
* a run by hand: its actor and triggering actor are the repository's owner;
* the workflow is the bench workflow at that ref (``GITHUB_WORKFLOW_REF``), and its file at the job's workflow commit
  (``GITHUB_WORKFLOW_SHA``) is the same blob as on master. A branch on an older master whose copy of the file is
  unchanged passes; a branch that changed the file, or that lacks a change master made to it, is refused until it
  carries master's file. The blob at the commit is read from the code host by that commit (immutable).

Standard library only: the job image's python3 runs it.
"""

from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import os
import re
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

EVENTS = ("push", "workflow_dispatch")
PUSH_REF = re.compile(r"refs/heads/(?:(?:train|agent|claude)/[^/]+|lane-[^/]+)")
DISPATCH_REF = re.compile(rf"{PUSH_REF.pattern}|refs/heads/master")
SHA = re.compile(r"[0-9a-f]{40}")
RAW_HOST = "raw.githubusercontent.com"
FETCH_SECONDS = 30
FETCH_BYTES = 1_000_000

Fetch = Callable[[str, str, str, str], bytes]  # (proxy, repository, commit, path) -> the file's bytes


def blob_sha(content: bytes) -> str:
    """The git blob id of a file's bytes (what the code host's contents endpoint calls the file's sha)."""
    return hashlib.sha1(b"blob %d\0" % len(content) + content, usedforsecurity=False).hexdigest()


def fetch_raw(proxy: str, repo: str, commit: str, path: str) -> bytes:
    """The file at a commit, by the commit's id (immutable), through the job's proxy (its only way out; its address
    is the host's job file's, never a variable)."""
    m = re.fullmatch(r"([0-9.]+):([0-9]+)", proxy)
    if not m:
        raise RuntimeError("the host's job file gives no proxy address")
    conn = http.client.HTTPSConnection(m.group(1), int(m.group(2)), timeout=FETCH_SECONDS)
    conn.set_tunnel(RAW_HOST, 443)
    try:
        conn.request("GET", f"/{repo}/{commit}/{path}", headers={"User-Agent": "tb-bench-gate"})
        resp = conn.getresponse()
        body = resp.read(FETCH_BYTES + 1)
    finally:
        conn.close()
    if resp.status != 200 or len(body) > FETCH_BYTES:
        raise RuntimeError(f"the workflow file at the job's commit could not be read (HTTP {resp.status})")
    return body


def decide(env: Mapping[str, str], event: Mapping[str, Any], facts: Mapping[str, Any], fetch: Fetch) -> list[str]:
    """Every reason to refuse the job; an empty list lets it run. Missing facts refuse (fail closed)."""
    repo = str(facts.get("repo", ""))
    path = str(facts.get("workflow", ""))
    master_blob = str(facts.get("workflow_blob", ""))
    if not repo or not path or not SHA.fullmatch(master_blob):
        return ["the host's job file does not name the repository, the workflow and master's blob of it"]
    out: list[str] = []
    name = env.get("GITHUB_EVENT_NAME", "")
    if name not in EVENTS:
        out.append(f"the event is {name or 'not given'}: only a push or the owner's run by hand reaches the bench")
    if env.get("GITHUB_REPOSITORY") != repo:
        out.append(f"the repository is {env.get('GITHUB_REPOSITORY') or 'not given'}, not {repo}")
    found = event.get("repository")
    payload_repo: Mapping[str, Any] = found if isinstance(found, dict) else {}
    if payload_repo.get("full_name") != repo or payload_repo.get("fork") is not False:
        out.append("the event's repository is not this repository (or is a fork)")
    ref = env.get("GITHUB_REF", "")
    pattern = DISPATCH_REF if name == "workflow_dispatch" else PUSH_REF
    if not pattern.fullmatch(ref):
        out.append(f"the ref {ref or 'not given'} is not an allowed branch")
    if name == "workflow_dispatch":
        owner = env.get("GITHUB_REPOSITORY_OWNER", "")
        if not owner or env.get("GITHUB_ACTOR") != owner or env.get("GITHUB_TRIGGERING_ACTOR") != owner:
            out.append("a run by hand by someone who is not the repository's owner")
    if env.get("GITHUB_WORKFLOW_REF") != f"{repo}/{path}@{ref}":
        out.append(f"the workflow is {env.get('GITHUB_WORKFLOW_REF') or 'not given'}, not {path} at the job's ref")
    commit = env.get("GITHUB_WORKFLOW_SHA", "")
    if not SHA.fullmatch(commit):
        out.append("the workflow's commit is not given")
    if out:
        return out  # never read anything for a job that is refused already
    try:
        got = blob_sha(fetch(str(facts.get("proxy", "")), repo, commit, path))
    except (OSError, RuntimeError, http.client.HTTPException) as exc:
        return [f"the workflow file at the job's commit could not be read ({type(exc).__name__}): refused"]
    if got != master_blob:
        return [f"the workflow file at {commit[:12]} is not master's ({got[:12]} against {master_blob[:12]})"]
    return []


def main(argv: Sequence[str] | None = None, env: Mapping[str, str] | None = None, fetch: Fetch = fetch_raw) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--job", required=True, help="the host's job file (job.json in the job's scratch folder)")
    args = ap.parse_args(argv)
    env = os.environ if env is None else env
    try:
        facts = json.loads(Path(args.job).read_text(encoding="utf-8"))
        event_path = env.get("GITHUB_EVENT_PATH", "")
        event = json.loads(Path(event_path).read_text(encoding="utf-8")) if event_path else {}
        problems = decide(env, event if isinstance(event, dict) else {}, facts, fetch)
    except (OSError, ValueError) as exc:
        problems = [f"the job's facts could not be read ({type(exc).__name__})"]
    for p in problems:
        print(f"bench gate: refused: {p}", file=sys.stderr)
    if problems:
        print("bench gate: this job does not run on the bench host", file=sys.stderr)
        return 1
    print("bench gate: a push or the owner's run of master's bench workflow, in this repository: runs")
    return 0


if __name__ == "__main__":
    sys.exit(main())

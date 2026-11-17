"""A stand-in for restic 0.19 in the tests (D-968): the subcommands and exit codes tools/trialbox/restic_repo.py uses,
over a folder. Not restic's format and not encrypted: it only checks what the box asks of restic. Every call is
logged (argv and whether RESTIC_PASSWORD was set, never its value) to $FAKE_RESTIC_LOG."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import uuid
from pathlib import Path
from typing import Any


def log(argv: list[str]) -> None:
    path = os.environ.get("FAKE_RESTIC_LOG")
    if path:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"argv": argv, "password_set": "RESTIC_PASSWORD" in os.environ}) + "\n")


def pw_hash(pw: str) -> str:
    return hashlib.sha256(pw.encode()).hexdigest()


def opened(repo: Path, pw_var: str = "RESTIC_PASSWORD") -> Path:
    if not (repo / "config").is_file():
        print("Fatal: repository does not exist: unable to open config file", file=sys.stderr)
        sys.exit(10)
    if json.loads((repo / "config").read_text())["pw"] != pw_hash(os.environ.get(pw_var, "")):
        print("Fatal: wrong password or no key found", file=sys.stderr)
        sys.exit(12)
    return repo


def snapshots(repo: Path) -> list[dict[str, Any]]:
    d = repo / "snapshots"
    return (
        sorted((json.loads((p / "meta.json").read_text()) for p in d.iterdir()), key=lambda s: s["seq"])
        if d.is_dir()
        else []
    )


def main(argv: list[str]) -> int:
    log(argv)
    args = list(argv)
    repo = None
    if args[:1] == ["-r"]:
        repo, args = Path(args[1]), args[2:]
    cmd, rest = args[0], args[1:]
    if cmd == "version":
        print("restic 0.19.1 (fake)")
        return 0
    if repo is None:
        print("Fatal: Please specify repository location (-r)", file=sys.stderr)
        return 1
    if cmd == "cat" and rest == ["config"]:
        opened(repo)
        print(json.dumps({"version": 2}))
        return 0
    if cmd == "init":
        if (repo / "config").exists():
            print(
                "Fatal: create key in repository failed: repository master key and config already initialized",
                file=sys.stderr,
            )
            return 1
        if "--from-repo" in rest:
            opened(Path(rest[rest.index("--from-repo") + 1]), "RESTIC_FROM_PASSWORD")
        repo.mkdir(parents=True, exist_ok=True)
        (repo / "config").write_text(json.dumps({"pw": pw_hash(os.environ.get("RESTIC_PASSWORD", ""))}))
        print(f"created restic repository {uuid.uuid4().hex[:10]} at {repo}")
        return 0
    opened(repo)
    if cmd == "backup":
        listing = Path(rest[rest.index("--files-from-verbatim") + 1]).read_text().splitlines()
        tag = rest[rest.index("--tag") + 1]
        sid = uuid.uuid4().hex
        seq = len(snapshots(repo)) + 1
        dest = repo / "snapshots" / sid
        missing = []
        for rel in listing:
            src = Path(os.getcwd()) / rel
            if not src.is_file():
                missing.append(rel)
                continue
            # as restic does: an absolute entry is kept under its whole path, a relative one under the relative path
            # as written (not prefixed with the working folder; D-978, the box rehearsal's restore found the files at
            # <target>/db/..., not <target>/<root>/db/...)
            to = dest / "data" / (str(src).lstrip("/") if Path(rel).is_absolute() else rel)
            to.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, to)
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "meta.json").write_text(json.dumps({"id": sid, "tags": [tag], "seq": seq}))
        for rel in missing:
            print(json.dumps({"message_type": "error", "error": {"message": "no such file"}, "item": rel}))
        print(json.dumps({"message_type": "summary", "snapshot_id": sid, "files_new": len(listing) - len(missing)}))
        return 3 if missing else 0
    if cmd == "copy":
        src = opened(Path(rest[rest.index("--from-repo") + 1]), "RESTIC_FROM_PASSWORD")
        for sid in [a for a in rest if not a.startswith("-") and a != str(src)]:
            if not (repo / "snapshots" / sid).exists():
                shutil.copytree(src / "snapshots" / sid, repo / "snapshots" / sid)
        return 0
    if cmd == "forget":
        if "--keep-last" in rest:
            keep = int(rest[rest.index("--keep-last") + 1])
            tag = rest[rest.index("--tag") + 1]
            mine = [s for s in snapshots(repo) if tag in s["tags"]]
            for s in mine[: max(0, len(mine) - keep)]:
                shutil.rmtree(repo / "snapshots" / s["id"])
            return 0
        for sid in [a for a in rest if not a.startswith("-")]:
            if not (repo / "snapshots" / sid).exists():
                print(f"Ignoring {sid!r}: no matching ID found", file=sys.stderr)
                return 1
            shutil.rmtree(repo / "snapshots" / sid)
        return 0
    if cmd == "prune":
        return 0
    if cmd == "snapshots":
        want = rest[rest.index("--tag") + 1] if "--tag" in rest else None
        rows = [s for s in snapshots(repo) if want is None or want in s["tags"]]
        print(json.dumps([{"id": s["id"], "short_id": s["id"][:8], "tags": s["tags"]} for s in rows]))
        return 0
    if cmd == "restore":
        sid = rest[0]
        target = Path(rest[rest.index("--target") + 1])
        src = repo / "snapshots" / sid / "data"
        if not src.parent.exists():
            print(f"Fatal: no matching ID found for prefix {sid!r}", file=sys.stderr)
            return 1
        shutil.copytree(src, target, dirs_exist_ok=True)
        return 0
    print(f"fake restic: unknown command {cmd}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

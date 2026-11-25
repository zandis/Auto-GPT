"""The site seed (M1; plan 10, 10K-2).

    python3 -m tools.site_seed verify site-seed.json --pub deploy/keys/vendor_ed25519.pub   # the vendor's signed
    python3 -m tools.site_seed run --deploy deploy                                           # after the install

``verify``: one JSON file of the hospital's questionnaire answers, made before shipping and signed by the vendor
(``<file>.sig``, ``tools/sign_bundle.py sign-file``). With it the install asks only the person and the passphrase. It
may hold the site's answers only: no person, no password, no environment.

``run``: the box starts with a usable record. The site and its departments are in ``settings.yaml`` since the plan
(``tools/box/plan.py``); this checks them and, on a box that is not in use, makes the sample hospital (600 synthetic
patients), loads it, installs the example study and screens it once. Each step first asks whether it is done: a second
run changes nothing, and a value a person changed since is never written over. A PRODUCTION box gets no sample.
Standard library only; the work runs in the box's own containers.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "libs") not in sys.path:
    sys.path.insert(0, str(ROOT / "libs"))  # the host's python3

from tb_common import box_answers  # noqa: E402

from tools.box.plan import SAMPLE_FEED  # noqa: E402
from tools.trialbox.finish_check import read_env  # noqa: E402

#: what a seed may answer (tb_common.box_answers.parse's names): the site's, never a person's
KEYS = ("site_name", "language", "tz", "country", "box_name", "source", "source_dir", "ssmix2_root",
        "ssmix2_order_numbers", "chartno_rule", "sae_office_mailbox", "smtp_host", "smtp_port", "mta_authserv_id",
        "anchor_dir", "printed_dates", "year_basis")  # fmt: skip
STUDY = "GZQO"  # the example study of the image (rulesets/GZQO)
BY = "synthetic-run:site-seed"
DONE = Path("site") / "box" / "seed.json"  # under deploy/: which steps are done
PERSON = {"owner_full_name": "seed", "owner_username": "seed", "owner_email": "seed@example.invalid"}

# run in the mail gateway's container, whose token starts jobs (D-464): the sample screen, once
SCREEN = """
import sys, time, httpx
from tb_common.service_auth import auth_headers
orch = "http://orchestrator:8010"
body = {"type": "SCREEN", "ruleset": "%s", "options": {"version": "1.0.0"}, "comment": "site-seed",
        "requested_by": "%s", "message_id": "<site-seed@box.invalid>"}
r = httpx.post(f"{orch}/jobs", json=body, headers=auth_headers(), timeout=60)
if r.status_code != 200:
    sys.exit(f"the sample screen was not accepted: {r.status_code} {r.text[:200]}")
jid, end = r.json()["job_id"], time.monotonic() + 1800
while time.monotonic() < end:
    j = httpx.get(f"{orch}/jobs/{jid}", headers=auth_headers(), timeout=60).json()
    if j["state"] in ("done", "failed", "cancelled", "rejected"):
        sys.exit(None if j["state"] == "done" else f"the sample screen ended {j['state']}: {j.get('error')}")
    time.sleep(5)
sys.exit("the sample screen did not end within 30 minutes")
"""


class SeedError(RuntimeError):
    pass


# ------------------------------------------------------------------------------------------------ the signed answers
def answers(path: Path) -> dict[str, Any]:
    """The seed's answers; refused when it holds anything else, or an answer the box cannot use."""
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SeedError(f"{path.name} is not a JSON file ({type(exc).__name__})") from None
    if not isinstance(doc, dict):
        raise SeedError(f"{path.name} is not a site seed")
    other = sorted(set(doc) - set(KEYS))
    if other:
        raise SeedError(f"{path.name} holds what a site seed may not: {', '.join(other)[:200]}")
    trial = box_answers.fill({"tz": "UTC", **PERSON, **doc})
    got, problems = box_answers.parse(trial)
    if got is None:
        raise SeedError(f"{path.name}: {'; '.join(map(str, problems))}")
    return {k: v for k, v in doc.items() if v not in ("", None)}


def verify(path: Path, pub: Path) -> dict[str, Any]:
    """The seed's answers once its signature checks with the vendor's key (``openssl``, as the bootstrap's)."""
    sig = path.with_name(path.name + ".sig")
    if not (pub.is_file() and sig.is_file()):
        raise SeedError(f"{path.name}: the vendor's key or {sig.name} is missing")
    done = subprocess.run(
        ["openssl", "pkeyutl", "-verify", "-pubin", "-inkey", str(pub), "-rawin", "-in", str(path),
         "-sigfile", str(sig)],
        capture_output=True, text=True, check=False,
    )  # fmt: skip
    if done.returncode != 0:
        raise SeedError(f"{path.name}: the signature does not check with the vendor's key")
    return answers(path)


# ------------------------------------------------------------------------------------------------ after the install
def _run(argv: list[str], text: str | None = None, timeout: int = 3600) -> str:
    done = subprocess.run(argv, input=text, capture_output=True, text=True, timeout=timeout, check=False)
    if done.returncode != 0:
        tail = " ".join((done.stderr or done.stdout).split())[-300:]
        raise SeedError(f"{argv[0]} ended {done.returncode}: {tail}")
    return done.stdout


def run(deploy: Path, sh: Callable[..., str] = _run) -> list[str]:
    """The steps not done yet, in order; each is written down as it ends. Returns what was done (empty: nothing)."""
    from tools.box.__main__ import write_whole

    env = read_env(deploy / ".env")
    kept = deploy / DONE
    done: dict[str, str] = json.loads(kept.read_text(encoding="utf-8")) if kept.is_file() else {}
    did: list[str] = []

    def step(key: str, work: Callable[[], object]) -> None:
        if key in done:
            return
        work()
        done[key] = datetime.now(UTC).isoformat(timespec="seconds")
        write_whole(kept, json.dumps(done, indent=1, sort_keys=True) + "\n")
        did.append(key)

    step("site", lambda: _site(deploy))
    feed = (env.get("TB_SOURCE_DIR") or "").removeprefix("./")
    if (env.get("TB_ENV") or "PRODUCTION").upper() == "PRODUCTION" or feed != SAMPLE_FEED.removeprefix("./"):
        return did  # a box in use, or a source of the hospital's own: no sample
    image = env.get("TB_IMAGE") or "trialbox-py:1.0.0"
    dc = ["docker", "compose", "--project-directory", str(deploy), "exec", "-T"]
    folder = deploy / feed
    mount = env.get("TB_SOURCE_MOUNT") or "/data/source/site"

    made = "python -m tools.make_fixtures --out /tmp/s --sites a && cp /tmp/s/site-a/*.csv /out/ && chmod a+r /out/*"
    today = datetime.now(UTC).date().isoformat()
    study = (
        f"cd /app/rulesets && python -m zipfile -c /tmp/{STUDY}.zip {STUDY} && "
        f"python -m criteria_compiler.import_ruleset /tmp/{STUDY}.zip --by {BY}"
    )

    def make() -> None:
        folder.mkdir(parents=True, exist_ok=True)
        sh(
            [
                "docker",
                "run",
                "--rm",
                "--network",
                "none",
                "--user",
                "0",
                "-v",
                f"{folder}:/out",
                image,
                "sh",
                "-c",
                made,
            ]
        )

    step("sample_hospital", make)
    load = [
        *dc,
        "adapter",
        "python",
        "-m",
        "adapter.cli",
        "run",
        "--source",
        "csv",
        "--path",
        mount,
        "--snapshot",
        today,
    ]
    step("sample_loaded", lambda: sh(load))
    step("sample_study", lambda: sh([*dc, "criteria-compiler", "sh", "-c", study]))
    who = (env.get("TB_BACKUP_MAILTO") or "").strip()
    step("sample_list", lambda: sh([*dc, "mail-gateway", "python", "-"], SCREEN % (STUDY, who)))
    return did


def _site(deploy: Path) -> None:
    """The site, its zone and its departments are in the settings (the plan wrote them); nothing is written here."""
    text = (deploy / "settings.yaml").read_text(encoding="utf-8")
    missing = [k for k in ("site:", "departments:") if not any(ln.startswith(k) for ln in text.splitlines())]
    if missing:
        raise SeedError(f"settings.yaml holds no {', '.join(missing)}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="tools.site_seed", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)  # fmt: skip
    sub = ap.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("verify")
    v.add_argument("seed", type=Path)
    v.add_argument("--pub", type=Path, required=True)
    r = sub.add_parser("run")
    r.add_argument("--deploy", type=Path, default=ROOT / "deploy")
    args = ap.parse_args(argv)
    try:
        if args.cmd == "verify":
            got = verify(args.seed, args.pub)
            print(f"site seed: signed by the vendor's key; {len(got)} answers")
        else:
            did = run(args.deploy.resolve())
            print("site seed: " + (", ".join(did) if did else "nothing to do"))
    except (SeedError, OSError, subprocess.SubprocessError) as exc:
        print(f"site seed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

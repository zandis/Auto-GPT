"""The public security contact: one file, one check, one ``security.txt`` (card 10G-9, D-1239).

    python -m tools.security_contact show                  # the contact as written, and whether it is set
    python -m tools.security_contact release-check [ARGS]  # exit 1 while the contact is not set (make release-bundle)
    python -m tools.security_contact security-txt          # print the RFC 9116 file (exit 1 while not set)

The contact is written in one place, ``deploy/security/contact.json``. It is *set* when ``contact`` is a ``mailto:``
URI with one address or an ``https:`` URI (RFC 9116 section 2.5.3). Anything else (the placeholder the repository
carries until the owner chooses an address) is *not set*; no other file repeats the placeholder, so nothing needs a
second edit when the owner fills it.

``release-check`` is the release gate: ``make release-bundle`` runs it before the gates, with its ``BUNDLE_ARGS``.
It fails while the contact is not set, except for a bundle that is not a release: one built with ``--rehearsal``
(D-726: a site box refuses it) or ``--allow-dirty`` (D-631: release.json says dirty). Those pass with a warning, so
the rehearsals and the P-0 media keep working. Nothing else calls it: master stays green while the owner decides.

Standard library only: ``tools/build_site.py`` loads this file to write ``/.well-known/security.txt`` on the website,
and the Netlify build has nothing but Python.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CONTACT_FILE = ROOT / "deploy" / "security" / "contact.json"
# RFC 9116 section 2.5.5: Expires should be less than a year ahead; the site is rebuilt on every push
EXPIRES_DAYS = 180
# what a bundle that is not a release carries in make_bundle.sh's arguments
NOT_A_RELEASE = ("--rehearsal", "--allow-dirty")
_MAILTO = re.compile(r"^mailto:[^@\s/<>\"',;]+@[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?(?:\.[A-Za-z0-9-]+)+$")
_HTTPS = re.compile(r"^https://[A-Za-z0-9.-]+\.[A-Za-z]{2,}(?:[/?#][^\s]*)?$")


class ContactError(Exception):
    """The contact file cannot be read."""


def load(path: Path = CONTACT_FILE) -> dict[str, Any]:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContactError(f"{path}: not readable as JSON ({exc})") from exc
    if not isinstance(doc, dict) or not isinstance(doc.get("contact"), str):
        raise ContactError(f"{path}: no `contact` string")
    return doc


def is_uri(value: object) -> bool:
    """A Contact value RFC 9116 accepts and a reporter can use: mailto: with one address, or https:."""
    return isinstance(value, str) and bool(_MAILTO.match(value) or _HTTPS.match(value))


def problems(doc: dict[str, Any]) -> list[str]:
    """Why the contact is not ready for a release; empty when it is."""
    out: list[str] = []
    if not is_uri(doc.get("contact")):
        out.append(
            "the security contact is not set: `contact` in deploy/security/contact.json must be a mailto: or https: "
            "URI chosen by the owner (card 10G-9, D-1239)"
        )
    for key in ("encryption", "github_private_reporting"):
        value = doc.get(key)
        if value is not None and not (isinstance(value, str) and _HTTPS.match(value)):
            out.append(f"`{key}` in deploy/security/contact.json must be null or an https: URI")
    return out


def not_a_release(bundle_args: Sequence[str]) -> str | None:
    """The flag that makes these make_bundle.sh arguments a non-release bundle, if any."""
    for arg in bundle_args:
        if arg in NOT_A_RELEASE:
            return arg
    return None


def security_txt(doc: dict[str, Any], now: datetime | None = None) -> str:
    """The RFC 9116 file for the website; raises ContactError while the contact is not set."""
    if trouble := problems(doc):
        raise ContactError("; ".join(trouble))
    now = now or datetime.now(UTC)
    expires = (now + timedelta(days=EXPIRES_DAYS)).replace(microsecond=0)
    lines = [
        "# TrialBox security contact (RFC 9116). The policy, in English, Japanese and Traditional Chinese: Policy.",
        f"Contact: {doc['contact']}",
    ]
    if doc.get("github_private_reporting"):
        lines.append(f"Contact: {doc['github_private_reporting']}")
    lines.append(f"Expires: {expires.strftime('%Y-%m-%dT%H:%M:%SZ')}")
    if doc.get("encryption"):
        lines.append(f"Encryption: {doc['encryption']}")
    langs = [str(x) for x in doc.get("preferred_languages") or []]
    if langs:
        lines.append(f"Preferred-Languages: {', '.join(langs)}")
    if doc.get("policy"):
        lines.append(f"Policy: {doc['policy']}")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    ap.add_argument("--file", type=Path, default=CONTACT_FILE, help=argparse.SUPPRESS)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("show", help="the contact as written, and whether it is set")
    # release-check takes make_bundle.sh's arguments (BUNDLE_ARGS) as they are, after the command
    sub.add_parser("release-check", help="exit 1 while the contact is not set (make release-bundle)")
    sub.add_parser("security-txt", help="print the RFC 9116 file")
    args, bundle_args = ap.parse_known_args(argv)
    if bundle_args and args.cmd != "release-check":
        ap.error(f"unrecognized arguments: {' '.join(bundle_args)}")
    try:
        doc = load(args.file)
    except ContactError as exc:
        print(f"security_contact: {exc}", file=sys.stderr)
        return 1
    trouble = problems(doc)
    if args.cmd == "show":
        print(f"contact: {doc['contact']}")
        print("set" if not trouble else "NOT SET: " + "; ".join(trouble))
        return 0
    if args.cmd == "security-txt":
        if trouble:
            print("security_contact: " + "; ".join(trouble), file=sys.stderr)
            return 1
        sys.stdout.write(security_txt(doc))
        return 0
    if not trouble:
        print(f"security contact: {doc['contact']}")
        return 0
    flag = not_a_release(bundle_args)
    if flag:
        print(f"security_contact: WARNING, not a release ({flag}): " + "; ".join(trouble), file=sys.stderr)
        return 0
    print("security_contact: refusing a release bundle: " + "; ".join(trouble), file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

"""Every file an answers file names, checked on the host before anything is loaded (M1, found on the bench: a mapping
that is nowhere stopped the install only at its settings step, after an hour of loading images).

    python3 -m tools.answers_files ANSWERS --deploy deploy [--environment PRODUCTION]

Exit 1 names each missing file and where to put it, in the words of the step that would stop later. The mapping stops
every box, as the settings step does; a certificate file stops a PRODUCTION box only (elsewhere the later
step warns). The feed folder is a mount, not a file: it stays with its own step. The shipped mappings are named by the country table (``tb_common.site_country``), since the image
that holds them is not loaded yet. Standard library and the host's python3-yaml.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from tb_common import site_country


def shipped_mappings() -> frozenset[str]:
    """The mappings of the image a site may name (a test holds them to the files in the tree)."""
    named = {site_country.defaults(c).mapping for c in site_country.COUNTRIES} | {site_country.LEGACY.mapping}
    return frozenset(m for m in named if m)


def missing(answers: dict[str, Any], folder: Path, deploy: Path, production: bool) -> list[str]:
    """What the answers name that is not there. ``folder``: the answers file's own (its ``mapping/`` is copied in)."""
    out: list[str] = []
    name = str(answers.get("mapping") or "").strip()
    if name:
        path = Path(name)
        rel = Path(*path.parts[1:]) if path.parts[:1] == ("mapping",) else path
        places = [path] if path.is_absolute() else [deploy / "site" / "mapping" / rel, folder / "mapping" / rel]
        if name not in shipped_mappings() and not any(p.is_file() for p in places):
            out.append(
                f"mapping file {name} not found in the site mapping folder (deploy/site/mapping) or the image "
                "(copy a template from services/adapter/mapping/templates into deploy/site/mapping)"
            )
    if not production:
        return out
    if str(answers.get("tls_mode") or "hospital") == "hospital" and str(answers.get("tls_hostname") or "").strip():
        for key in ("tls_cert_file", "tls_key_file"):
            given = str(answers.get(key) or "").strip()
            if given and not Path(given).is_file():
                out.append(f"{key} {given} is not a file on this host: put the hospital's file there, then re-run")
    return out


def main(argv: list[str] | None = None) -> int:
    import yaml

    ap = argparse.ArgumentParser(prog="tools.answers_files", description=__doc__.split("\n\n")[0])
    ap.add_argument("answers", type=Path)
    ap.add_argument("--deploy", type=Path, required=True)
    ap.add_argument("--environment", default="")
    a = ap.parse_args(argv)
    try:
        doc = yaml.safe_load(a.answers.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        print(f"install: the answers file {a.answers} cannot be read ({type(exc).__name__})", file=sys.stderr)
        return 1
    found = missing(doc if isinstance(doc, dict) else {}, a.answers.resolve().parent, a.deploy,
                    a.environment.upper() not in ("DEV", "TEST", "VALIDATION"))  # fmt: skip
    for line in found:
        print(f"install: {line}", file=sys.stderr)
    if found:
        print("install: nothing was loaded or changed", file=sys.stderr)
    return 1 if found else 0


if __name__ == "__main__":
    raise SystemExit(main())

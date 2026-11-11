"""The site the journeys walk on (T-315a, D-448): the synthetic Taiwan site of the PoC (T-504, ``tw-ra``) built in
process as ``tests/integration/test_poc_scripts.py`` builds it, but as a working site rather than a demonstration:
demo mode stays off (a protocol can be sent in), and one account per console role is issued, each to be set up with
its own password and authenticator at first sign-in.

Before the first journey the owner's seeding has run with the built-in accounts, which are then switched off: the
RA-JAK and GZQO v1.0.0 lists, and the GOUT-COH registry linked to the REDCap simulator with one member taken on.
Stub model, synthetic data only, no network."""

from __future__ import annotations

import csv
import html
from pathlib import Path
from typing import Any

import pytest

from tests.integration import test_poc_scripts as poc
from tools import cgmh_demo as cd
from tools import demo
from tools import feas_demo as fd
from tools import list_demo as ld

Site = poc.Site
OWN_PW = poc.OWN_PW
LANGS = ("en", "ja", "zh-TW")

# account key -> (user name, console role, affiliation, studies, delegation-log entries)
ACCOUNTS: dict[str, tuple[str, str, str, tuple[str, ...], list[dict[str, Any]]]] = {
    "it": ("tw.it", "admin", "hospital", (), []),
    "stw": ("tw.stw", "steward", "hospital", (), []),
    "dpo": ("tw.dpo", "privacy", "hospital", (), []),
    "pi": ("tw.pi", "investigator", "hospital", (), [{"study": "RA-JAK", "role": "pi"}, {"study": "GZQO", "role": "pi"}]),
    "subpi": ("tw.subpi", "investigator", "hospital", (),
              [{"study": "RA-JAK", "role": "sub_pi", "tasks": ["screen", "refer"]}]),
    "crc": ("tw.crc", "coordinator", "hospital", (), [{"study": s, "role": "crc"} for s in ("RA-JAK", "GZQO", "GOUT-COH")]),
    "cra": ("tw.cra", "cro", "cro", ("RA-JAK",), []),
    "view": ("tw.view", "viewer", "hospital", (), []),
}  # fmt: skip


def text(page: str) -> str:
    """What a reader sees of a page's main part: tags removed, entities decoded (for the ja and zh-TW checks)."""
    return html.unescape(poc.text(page))


def build(work: Path, monkeypatch: pytest.MonkeyPatch) -> Site:
    from console.app import COOKIE
    from console.teamstore import TeamStore
    from tb_common.audit import AuditLog

    monkeypatch.setenv("TB_TZ", cd.SITE_TW["site"]["tz"])  # one synthetic site in one process: its site.tz (D-315)
    box, client, repo, _ = fd.build_site(work, cd.PROFILE, cd.SITE_TW)
    clock = ld.Clock(box.today[0])
    app = ld.console(work, box, client, repo, poc.SEED_PW, clock, extra_env={"TB_CONSOLE_MFA": "totp"})
    served = demo.DefaultLanguage(app, app.state.helpers.users, {}, COOKIE)
    s = Site("tw", work, box, app, served, clock, {})
    app.state.identity.now = lambda: s.seconds[0]
    users = app.state.helpers.users
    for name in ("admin", "crc", "pi"):
        s.sign_in(name, poc.SEED_PW, users.issue_enrol_code(name))
    # the owner's seeding: the first lists and the registry (the amendment is the coordinator's step J-CRC-02)
    ctx = {"crc": s.c["crc"], "box": s.box, "h": s.h}
    cd.screen(ctx, "RA-JAK")
    cd.screen(ctx, "GZQO")
    poc.seed_registry(s)
    # the accounts: the five roles the accounts file knows through tools.demo, the steward and the privacy office
    # (roles the PoC file does not carry) directly, each with a password someone else set and an enrolment code
    file_roles = {k: v for k, v in ACCOUNTS.items() if v[1] in demo.ROLES}
    rows = [{"username": u, "name": f"Journey tester ({k})", "role": role, "language": "en", "affiliation": aff,
             "studies": list(studies), "delegation": log} for k, (u, role, aff, studies, log) in file_roles.items()]  # fmt: skip
    accounts = demo.parse_accounts({"accounts": rows})
    issued = work / demo.ISSUED
    demo.seed_accounts(users, TeamStore(), accounts, today=users.today(), now=clock().isoformat(), totp=True,
                       issued=issued, known_studies={r.id.upper() for r in s.h.bk.rulesets()},
                       audit=AuditLog(box.audit_dir))  # fmt: skip
    for line in issued.read_text(encoding="utf-8").splitlines():
        _, user, kind, value = line.split("\t")
        s.issued.setdefault(user, {})[kind] = value
    for key, (user, role, aff, studies, _log) in ACCOUNTS.items():
        if key in file_roles:
            continue
        password = f"issued-{key}-password-0001"
        users.create(user, role, password, f"{key}@hospa.test", must_change=True)
        users.set_scope(user, aff, ",".join(studies), None)
        s.issued[user] = {"password": password, "enrolment code": users.issue_enrol_code(user)}
    s.served.langs.update({u: "en" for u, *_ in ACCOUNTS.values()})
    demo.switch_off_builtin(users, {u for u, *_ in ACCOUNTS.values()})
    s.state["trial"] = "RA-JAK"
    return s


def chart_numbers(s: Site) -> dict[str, str]:
    """pseudonym -> chart number of the synthetic hospital (what a paper opt-out form carries)."""
    from tb_common.crypto import pid_for_mrn

    with (s.work / "hospital" / "patient.csv").open(encoding="utf-8") as fh:
        return {pid_for_mrn(fd.KEY, r["mrn"]): r["mrn"] for r in csv.DictReader(fh)}

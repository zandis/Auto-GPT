"""P2-04 (ASSESS-1-ADDENDUM D5): the third-party containers take the controls of the box's own services.

The audit's inventory of an installed box: Caddy (the one published service) ran as root with every default
capability, the two model servers likewise, and the rehearsal's mail-sink had no security option, no memory cap and a
writable root. Here, in every stack that runs them: Caddy, llm-service and llm-verifier drop every capability and add
none back, with no privilege gain; Caddy's 443 rests on a port sysctl written in its file; the installer's TLS check
reads the hospital's key with the same dropped capabilities, so a key Caddy could not read stops the install there;
mail-sink is non-root, read-only, capped, with every capability dropped.
"""

from __future__ import annotations

import yaml

from tests.unit.test_compose_limits import DEPLOY, _active, _merge
from tests.unit.test_container_hardening import HARDENING_STACKS, _has

ROOT = DEPLOY.parent
THIRD_PARTY = ("caddy", "llm-service", "llm-verifier")


class _Compose(yaml.SafeLoader):
    """Compose's own tags (``!reset`` in the stand-ins file) read as an empty value."""


_Compose.add_constructor("!reset", lambda _loader, _node: None)


def test_caddy_and_the_model_servers_drop_every_capability_in_every_stack() -> None:
    seen: set[str] = set()
    for stack, profiles in HARDENING_STACKS:
        for svc, body in _merge(stack).items():
            if svc in THIRD_PARTY and _active(body, profiles):
                seen.add(svc)
                assert body.get("cap_drop") == ["ALL"], (stack, svc)
                assert not body.get("cap_add"), (stack, svc)
                assert _has(body, "no-new-privileges"), (stack, svc)
    assert seen == set(THIRD_PARTY)


def test_caddy_binds_443_through_its_own_sysctl() -> None:
    caddy = _merge(("docker-compose.yml", "docker-compose.identity.yml"))["caddy"]
    assert caddy["sysctls"] == {"net.ipv4.ip_unprivileged_port_start": 0}
    assert any(str(p).endswith(":443:443") for p in caddy["ports"])


def test_install_checks_the_tls_key_with_caddys_capabilities() -> None:
    install = (DEPLOY / "install.sh").read_text(encoding="utf-8")
    line = next(x for x in install.splitlines() if "python -m console.cli check-tls" in x)
    assert "--user 0 --cap-drop ALL" in line


def test_the_rehearsal_stand_ins_take_the_baseline() -> None:
    doc = _Compose((ROOT / "tools" / "rehearse_box" / "standins.yml").read_text(encoding="utf-8")).get_single_data()
    for svc in ("mail-sink", "llm-service", "llm-verifier"):  # the verifier's stand-in also runs with no tier overlay
        body = doc["services"][svc]
        for control in ("no-new-privileges", "read_only", "user"):
            assert _has(body, control), (svc, control)
        assert body["cap_drop"] == ["ALL"] and body["tmpfs"] == ["/tmp"] and not body.get("cap_add"), svc
    assert doc["services"]["mail-sink"]["mem_limit"] and doc["services"]["mail-sink"]["pids_limit"]


def test_the_closed_exceptions_stay_closed() -> None:
    from tests.unit.test_container_hardening import CAP_ADD, EXCEPTIONS

    assert not {(s, c) for s, c in EXCEPTIONS if c == "cap_drop" and s in THIRD_PARTY}
    assert CAP_ADD == {}

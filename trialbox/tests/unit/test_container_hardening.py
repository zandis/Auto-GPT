"""10G-1 (D-1323; review 16-17, 9l-18): the four container controls on all 15 services of the base compose file.

Every one of the 15 services in deploy/docker-compose.yml drops every capability (``cap_drop: [ALL]``), cannot gain a
privilege (``no-new-privileges:true``), runs on a read-only root filesystem (``read_only: true``, a tmpfs for what it
writes) and as a fixed numeric non-root user (``user: "uid:gid"``), in every stack a box or a developer runs. A
service that cannot take a control is in EXCEPTIONS with the reason; a control missing without a line there fails,
and a line there whose control has since been applied fails too, so the ledger stays the truth. No capability is
added back (CAP_ADD is empty).

H-58 (D-1337, H10G1-03): the services the overlay files add (OUTSIDE_THE_15) are checked the same way, in every
stack that runs them, with their exceptions in the same EXCEPTIONS list; every service of every compose file is
active in at least one stack checked here.

Two levels, as tests/unit/test_compose_limits.py: the YAML level needs no Docker; the rendered level asks
``docker compose config`` (skipped without the compose plugin; CI has it). Nothing is pulled or started: whether
each service still works under the controls is proved on a compose box (D-1323 lists the runs).
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from tests.unit.test_compose_limits import BASE, DEPLOY, STACKS, TWO_DEVICE_STACKS, _active, _merge, _render

CONTROLS = ("cap_drop", "no-new-privileges", "read_only", "user")
THE_15 = frozenset({
    "db", "fhir-store", "lake", "embed-service", "doc-parser", "criteria-compiler", "adapter", "audit-writer",
    "orchestrator", "mail-gateway", "gateway", "console", "llm-stub", "llm-service", "model-guard",
})  # fmt: skip
# (service, control) -> why it is not applied. Written in D-1323 and in the compose file beside the service.
EXCEPTIONS: dict[tuple[str, str], str] = {
    ("adapter", "read_only"): "the HL7 validator writes indexes into and renames packages in /opt/hl7/home (an image "
    "path, 399 MB); it fails on a read-only root; a fix is in the adapter's validator, not in deploy/",
    ("orchestrator", "read_only"): "runs the same HL7 validator for the TWPAS scenario (scenarios/twpas.py)",
    ("llm-service", "read_only"): "the upstream vLLM image writes compile and kernel caches under /root/.cache and "
    "/tmp, gigabytes a memory tmpfs would take from the model; to be proved on a GPU box",
    ("llm-service", "user"): "the upstream vLLM image runs as root with its caches under /root; to be proved on a "
    "GPU box with the caches moved",
    # H-58 (D-1337): the overlay services. Written beside each service in its overlay file too.
    ("llm-verifier", "read_only"): "the GPU overlays' second vLLM server: the same image and caches as llm-service",
    ("llm-verifier", "user"): "the same upstream vLLM image as llm-service, run as root with its caches under /root",
    ("judge-sleep-init", "user"): "runs the vLLM image's python, which that image runs as root; not shown to start "
    "as another uid, and no rehearsal leg runs the rtx5090 profile",
    ("judge-wake-init", "user"): "as judge-sleep-init: the vLLM image's python, run as root there",
    ("model-swap-init", "user"): "as judge-sleep-init: the vLLM image's python, run as root there",
    ("caddy", "user"): "the image runs as root and binds 443; caddy-data's files are root's, so a fixed uid would "
    "also need them handed over",
    ("authelia", "user"): "the image starts as root (PUID=0, PGID=0); its entrypoint sets the owner of /config and "
    "the user it runs as at start",
    ("authelia", "cap_drop"): "its entrypoint changes owners and the user at start (CHOWN, SETUID, SETGID as root)",
    ("authelia", "read_only"): "writes /app/.healthcheck.env at start, an image path its own health check reads",
    ("mailpit", "read_only"): "with no MP_DATABASE its message database is a file in /tmp: on a read-only root a "
    "memory tmpfs under its 256m cap, filled by every test mail (test profile only)",
}
CAP_ADD: dict[tuple[str, str], str] = {}  # (service, capability) -> why; none is needed
# Services of the overlay files that are not one of the 15 (10G-1 names the 15 of the base file). Each is checked for
# the four controls as the 15 are (H-58, D-1337), with its exceptions in EXCEPTIONS; listed so that a new service
# anywhere fails here until it is placed in THE_15 or here with what it is.
OUTSIDE_THE_15: dict[str, str] = {
    "greenmail": "test profile only (docker-compose.test.yml), a developer's mail server",
    "mailpit": "test profile only (docker-compose.test.yml), a developer's mail viewer",
    "testbench": "dev profile only (docker-compose.testbench.yml)",
    "llm-verifier": "the GPU overlays' second vLLM server (gb10, rtx5090, rtxpro6000, dgpu48, shared-quota, platform)",
    "judge-sleep-init": "rtx5090 overlay one-shot model swap helper",
    "judge-wake-init": "rtx5090 overlay one-shot model swap helper",
    "model-swap-init": "rtx5090 overlay one-shot model swap helper",
    "caddy": "identity overlay's TLS front on 443",
    "authelia": "identity overlay's sign-in service (oidc profile)",
    "prometheus": "monitoring overlay",
    "doctor": "platform overlay's doctor job (doctor profile)",
    "acceptance-directory": "acceptance overlay's test directory (LLDAP)",
    "acceptance-directory-seed": "acceptance overlay's one-shot directory seed",
    "acceptance-mail": "acceptance overlay's test mail server (GreenMail)",
    "link": "the two-device form's mutual-TLS link (two-device/docker-compose.spark.yml and .workstation.yml)",
}
NUMERIC_USER = re.compile(r"^(\d+):(\d+)$")
# H-58: the stacks checked here: test_compose_limits's, and the two-device form's (the Spark beside a workstation,
# T-214), whose files sit under deploy/two-device and add the `link` service
# the stacks test_compose_limits lints, the two-device ones included (one list: H58-03)
HARDENING_STACKS: list[tuple[tuple[str, ...], tuple[str, ...]]] = [*STACKS, *TWO_DEVICE_STACKS]
# the keys of a service that bear on the four controls: an overlay that sets none of them on a service changes
# nothing this test checks there
CONTROL_KEYS = frozenset({"user", "read_only", "tmpfs", "cap_drop", "cap_add", "security_opt", "privileged"})


def _has(body: dict[str, Any], control: str) -> bool:
    if control == "cap_drop":
        return "ALL" in [str(c).upper() for c in body.get("cap_drop") or []]
    if control == "no-new-privileges":
        return any(str(o).replace("=", ":") == "no-new-privileges:true" for o in body.get("security_opt") or [])
    if control == "read_only":
        return body.get("read_only") is True
    m = NUMERIC_USER.match(str(body.get("user") or ""))
    return m is not None and m.group(1) != "0" and m.group(2) != "0"


def problems(services: dict[str, dict[str, Any]], profiles: tuple[str, ...]) -> list[str]:
    """The lint: '<service>: <what is wrong>' for every active service; empty when the stack is clean."""
    bad: list[str] = []
    for svc, body in sorted(services.items()):
        if not _active(body, profiles):
            continue
        if svc not in THE_15 and svc not in OUTSIDE_THE_15:
            bad.append(f"{svc}: not one of the 15 and not in OUTSIDE_THE_15")
            continue
        for control in CONTROLS:
            has, excused = _has(body, control), (svc, control) in EXCEPTIONS
            if not has and not excused:
                bad.append(f"{svc}: no {control}")
            elif has and excused:
                bad.append(f"{svc}: {control} applied but still in EXCEPTIONS")
        for cap in body.get("cap_add") or []:
            if (svc, str(cap).upper()) not in CAP_ADD:
                bad.append(f"{svc}: cap_add {cap} without a reason in CAP_ADD")
        if body.get("privileged"):
            bad.append(f"{svc}: privileged")
    return bad


def test_the_base_file_has_the_15_services_and_each_takes_the_four_controls() -> None:
    """Compose test 15 of 15: every service carries each control or its written exception."""
    base = _merge((BASE,))
    assert set(base) == THE_15
    assert problems(base, ("stub", "gpu")) == []
    clean = [s for s in sorted(base) if all(_has(base[s], c) or (s, c) in EXCEPTIONS for c in CONTROLS)]
    assert len(clean) == 15
    assert {s for s, _ in EXCEPTIONS} <= THE_15 | set(OUTSIDE_THE_15) and all(c in CONTROLS for _, c in EXCEPTIONS)
    assert all(_has(base[s], "no-new-privileges") for s in THE_15)  # no exception
    # cap_drop: no exception left (llm-service's, written for rc1, closed by P2-04 / ASSESS-1-ADDENDUM D5)
    assert {s for s in THE_15 if not _has(base[s], "cap_drop")} == set()


@pytest.mark.parametrize(
    ("stack", "profiles"), HARDENING_STACKS, ids=lambda x: "+".join(x) if isinstance(x, tuple) else x
)
def test_every_stack_keeps_the_controls(stack: tuple[str, ...], profiles: tuple[str, ...]) -> None:
    assert problems(_merge(stack), profiles) == []


def _files() -> list[str]:
    """Every compose file under deploy/ (as test_compose_limits names them: relative to deploy/)."""
    return sorted(str(p.relative_to(DEPLOY)) for p in DEPLOY.rglob("docker-compose*.yml"))


def test_every_service_of_every_overlay_is_checked_in_a_stack_that_runs_it() -> None:
    """H-58 (H10G1-03): each service a compose file defines is active (its profile on) in at least one stack of
    HARDENING_STACKS that holds the file, so test_every_stack_keeps_the_controls checks it there, or the file sets
    none of the control keys on it (gb10's llm-stub: a memory cap and a platform, in a gpu-only stack); and each
    service the base file does not define is in OUTSIDE_THE_15."""
    files = _files()
    assert {"platform/docker-compose.platform.yml", "two-device/docker-compose.spark.yml", BASE} <= set(files)
    assert len(files) >= 16 and set(files) <= {f for stack, _ in HARDENING_STACKS for f in stack}
    unchecked, overlay_services = [], set()
    for name in files:
        for svc, body in sorted(_merge((name,)).items()):
            if name != BASE:
                overlay_services.add(svc)
            run = any(name in st and _active(_merge(st)[svc], pr) for st, pr in HARDENING_STACKS)
            if not run and set(body) & CONTROL_KEYS:
                unchecked.append(f"{name}: {svc}")
    assert unchecked == []
    assert overlay_services - THE_15 == set(OUTSIDE_THE_15)  # each listed one is real, each real one listed


def test_every_overlay_service_takes_the_four_controls_or_names_its_exception() -> None:
    """H-58 (D-1337): per service of OUTSIDE_THE_15, in every stack that runs it, each control is applied or written
    in EXCEPTIONS with a reason; and the pins of the card: no GPU model server gains or loses a capability rule
    (llm-verifier keeps llm-service's exceptions), nothing is added back."""
    seen: dict[str, set[str]] = {}
    for stack, profiles in HARDENING_STACKS:
        merged = _merge(stack)
        for svc, body in merged.items():
            if svc in OUTSIDE_THE_15 and _active(body, profiles):
                seen.setdefault(svc, set()).update(c for c in CONTROLS if _has(body, c))
                assert not body.get("cap_add") and not body.get("privileged"), (stack, svc)
    assert set(seen) == set(OUTSIDE_THE_15)
    for svc, applied in sorted(seen.items()):
        for control in CONTROLS:
            excused = (svc, control) in EXCEPTIONS
            assert (control in applied) != excused, (svc, control)  # one or the other, never both, never neither
            assert not excused or len(EXCEPTIONS[(svc, control)]) > 20
    # every overlay service now gives up privilege gain; the model servers keep llm-service's three exceptions
    assert all("no-new-privileges" in seen[s] for s in OUTSIDE_THE_15)
    assert {c for s, c in EXCEPTIONS if s == "llm-verifier"} == {c for s, c in EXCEPTIONS if s == "llm-service"}
    fully = sorted(s for s in OUTSIDE_THE_15 if not any((s, c) in EXCEPTIONS for c in CONTROLS))
    assert fully == [
        "acceptance-directory", "acceptance-directory-seed", "acceptance-mail", "doctor", "greenmail", "link",
        "prometheus", "testbench",
    ]  # fmt: skip


def test_the_overlay_users_match_their_images() -> None:
    """The numeric users of the overlay services are each image's own user: tb (10001, python.Dockerfile) for the
    doctor and the test bench, nobody (65534) for Prometheus (its image's USER) and Mailpit (no USER: root before),
    greenmail (999, its image's /etc/passwd) for both GreenMail servers, lldap (1000, the rootless image's UID and
    GID; tools/acceptance_env.py chowns the directory's files to it)."""
    want = {
        ("platform/docker-compose.platform.yml", "doctor"): "10001:10001",
        ("docker-compose.testbench.yml", "testbench"): "10001:10001",
        ("docker-compose.monitoring.yml", "prometheus"): "65534:65534",
        ("docker-compose.test.yml", "mailpit"): "65534:65534",
        ("docker-compose.test.yml", "greenmail"): "999:999",
        ("docker-compose.acceptance.yml", "acceptance-mail"): "999:999",
        ("docker-compose.acceptance.yml", "acceptance-directory"): "1000:1000",
        ("docker-compose.acceptance.yml", "acceptance-directory-seed"): "1000:1000",
    }
    assert {k: _merge((k[0],))[k[1]].get("user") for k in want} == want
    assert "DIRECTORY_UID = 1000" in (DEPLOY.parent / "tools" / "acceptance_env.py").read_text(encoding="utf-8")


def test_the_lint_names_an_overlay_service_without_the_controls() -> None:
    """Negative: an overlay service that loses a control is named; an exception whose control is then applied is
    named too."""
    services = _merge((BASE, "docker-compose.monitoring.yml", "docker-compose.identity.yml"))
    names = ("prometheus", "caddy", "authelia")
    assert [p for p in problems(services, ("stub", "oidc")) if p.startswith(names)] == []
    services["prometheus"] = {**services["prometheus"], "read_only": False, "user": None}
    services["authelia"] = {**services["authelia"], "cap_drop": ["ALL"], "cap_add": ["NET_BIND_SERVICE"]}
    services["caddy"] = {**services["caddy"], "cap_drop": []}  # P2-04 (D5): caddy's cap_drop is no longer excused
    assert [p for p in problems(services, ("stub", "oidc")) if p.startswith(names)] == [
        "authelia: cap_drop applied but still in EXCEPTIONS",
        "authelia: cap_add NET_BIND_SERVICE without a reason in CAP_ADD",
        "caddy: no cap_drop",
        "prometheus: no read_only",
        "prometheus: no user",
    ]


def test_read_only_services_get_a_tmpfs_for_what_they_write() -> None:
    base = _merge((BASE,))
    for svc in THE_15 - {"model-guard", "llm-service"}:
        assert "/tmp" in [str(t).split(":")[0] for t in base[svc].get("tmpfs") or []], svc
    assert any(str(t).startswith("/var/run/postgresql:uid=999,gid=999") for t in base["db"]["tmpfs"])
    # 10G-1 review D1: db's /tmp is capped (memory under db's mem_limit, shared with shared_buffers); what goes there
    # is bookkeeping only, the data streams through exec (backup_schedule.EMIT_SH, update.RESTORE_SH)
    tmp = [str(t) for t in base["db"]["tmpfs"] if str(t).split(":")[0] == "/tmp"]
    assert len(tmp) == 1 and re.search(r"(^|[:,])size=\d+[km]\b", tmp[0]), tmp


def test_the_users_match_the_images_and_the_installer() -> None:
    """tb is uid 10001 in python.Dockerfile (the jvm and embed images build on it), and install.sh gives
    settings.yaml to group 10001; the db runs as postgres (999), which owns its volume already."""
    base = _merge((BASE,))
    py = {s for s in THE_15 if str(base[s].get("image", "")).startswith("${TB_")}
    assert {"lake", "console", "adapter", "embed-service"} <= py
    assert {base[s]["user"] for s in py} == {"10001:10001"}
    assert "--uid 10001" in (DEPLOY / "docker" / "python.Dockerfile").read_text(encoding="utf-8")
    assert 'chown "$(id -u):10001" deploy/settings.yaml' in (DEPLOY / "install.sh").read_text(encoding="utf-8")
    assert base["db"]["user"] == "999:999"
    # a numeric user gets no supplementary group: postgres's own ssl-cert (D-993) is added by name, so PID 1 has
    # exactly postgres's groups (the box rehearsal's SC-1b check), and nothing else is added
    assert base["db"]["group_add"] == ["ssl-cert"]
    assert all("group_add" not in base[s] for s in THE_15 if s != "db")
    assert base["fhir-store"]["user"] == "65532:65532"


#: host -> container copies (``compose cp HOST SERVICE:PATH``) in the installer and the update path: docker cp
#: refuses to write into a read-only root, and a tmpfs /tmp is no volume to it (box rehearsal, CI run 44458900188:
#: the reference data pack was never loaded). Copies out of a container (``SERVICE:PATH HOST``) still work.
_CP_IN = re.compile(r"""\bcp\b[^\n]*?\s["']?([a-z][a-z-]+):/""")
_CP_IN_PY = re.compile(r"""_c\(\s*"cp"\s*,[^\n]*?"([a-z][a-z-]+):/""")


def _cp_sources() -> list[str]:
    """Every file that drives the box's containers: the installer and the deploy scripts, the update, backup,
    restore and support-bundle tools (``tools/trialbox``), the drills and the box helper."""
    root = DEPLOY.parent
    files = [*sorted((root / "deploy").glob("*.sh")), *sorted((root / "tools" / "trialbox").glob("*.py")),
             *sorted((root / "tools" / "box").glob("*.py"))]  # fmt: skip
    files += [root / "tools" / f for f in ("restore_drill.py", "backup_drill.py", "update_drill.py")]
    rels = [str(f.relative_to(root)) for f in files if f.is_file()]
    assert {
        "deploy/install.sh",
        "tools/trialbox/update.py",
        "tools/trialbox/backup_schedule.py",
        "tools/trialbox/backup.py",
        "tools/trialbox/restore_drill.py",
        "tools/restore_drill.py",
    } <= set(rels)
    return rels


def test_nothing_copies_a_file_into_a_read_only_service() -> None:
    base = _merge((BASE,))
    ro = {s for s, body in base.items() if body.get("read_only") is True}
    assert "criteria-compiler" in ro
    root = DEPLOY.parent
    found = []
    for rel in _cp_sources():
        rx = _CP_IN if rel.endswith(".sh") else _CP_IN_PY
        for line in (root / rel).read_text(encoding="utf-8").splitlines():
            m = rx.search(line)
            if m and m.group(1) in ro and not re.search(r"\bcp\s+[\"']?" + re.escape(m.group(1)) + ":", line):
                found.append(f"{rel}: {line.strip()}")
    assert found == []
    # negative: the line the rehearsal caught is found
    bad = '  if "${COMPOSE[@]}" cp "$f" criteria-compiler:/tmp/refdata-install.tar \\'
    assert _CP_IN.search(bad) and _CP_IN.search(bad).group(1) == "criteria-compiler"  # type: ignore[union-attr]
    bad_py = 'self.run(self._c("cp", str(pack), "criteria-compiler:/tmp/refdata-update.tar"))'
    assert _CP_IN_PY.search(bad_py) and _CP_IN_PY.search(bad_py).group(1) == "criteria-compiler"  # type: ignore[union-attr]
    # a copy out (caddy's root certificate, install.sh) is not a copy in
    out = '"${COMPOSE[@]}" cp caddy:/data/caddy/pki/authorities/local/root.crt deploy/secrets/tls/caddy-root.crt'
    m = _CP_IN.search(out)
    assert m is None or re.search(r"\bcp\s+[\"']?" + re.escape(m.group(1)) + ":", out)


#: container -> host copies (``compose cp SERVICE:PATH HOST``): ``docker cp`` reads a container's layers and volumes,
#: not a tmpfs mount, so a copy out of a hardened service's tmpfs /tmp finds nothing (box rehearsal, CI run
#: 44469191433: the nightly's ``cp db:/tmp/tb-backup/.``, "Could not find the file /tmp/tb-backup/.").
_CP_OUT = re.compile(r"""\bcp\s+(?:-[a-zA-Z]+\s+)*["']?([a-z][a-z-]+):([^\s"']+)""")
_CP_OUT_PY = re.compile(r'_c\(\s*"cp"\s*,\s*f?"([a-z][a-z-]+):([^"]*)"')
_CONST = re.compile(r"""^([A-Z][A-Z0-9_]*)\s*(?::\s*str\s*)?=\s*"([^"]*)"\s*(?:#.*)?$""", re.M)


def _tmpfs(body: dict[str, Any]) -> list[str]:
    t = body.get("tmpfs") or []
    return [str(x).split(":", 1)[0] for x in ([t] if isinstance(t, str) else t)]


def _on_tmpfs(path: str, mounts: list[str]) -> bool:
    """Whether ``path`` is on one of ``mounts``; a path that is not a literal (a variable left in it) counts as
    one: the guard cannot tell, so it names the line."""
    if "{" in path or "$" in path or not path.startswith("/"):
        return True
    return any(path == m or path.startswith(m.rstrip("/") + "/") for m in mounts)


def _copies_out_of_a_tmpfs(rel: str, text: str, tmpfs: dict[str, list[str]]) -> list[str]:
    consts = dict(_CONST.findall(text))
    found = []
    for line in text.splitlines():
        for m in (_CP_OUT if rel.endswith(".sh") else _CP_OUT_PY).finditer(line):
            svc, path = m.group(1), m.group(2)
            if svc not in tmpfs:
                continue
            path = re.sub(r"\{([A-Z][A-Z0-9_]*)\}", lambda c: consts.get(c.group(1), c.group(0)), path)
            if _on_tmpfs(path, tmpfs[svc]):
                found.append(f"{rel}: {line.strip()}")
    return found


def test_nothing_copies_a_file_out_of_a_tmpfs() -> None:
    """10G-1: no copy out of a service from a path on its tmpfs, in any file that drives the box (the nightly backup,
    the restore and drills, update's snapshot and rollback, the support bundle, the installer). The backup streams
    instead (``exec -T`` to the host's file)."""
    base = _merge((BASE,))
    tmpfs = {s: _tmpfs(body) for s, body in base.items() if _tmpfs(body)}
    assert "/tmp" in tmpfs["db"] and "/var/run/postgresql" in tmpfs["db"]
    root = DEPLOY.parent
    found = []
    for rel in _cp_sources():
        found += _copies_out_of_a_tmpfs(rel, (root / rel).read_text(encoding="utf-8"), tmpfs)
    assert found == []
    # negative: the nightly's line the rehearsal caught is found, through its module constant
    bad = 'CONTAINER_SPOOL = "/tmp/spool"\nself.box.run(self.box._c("cp", f"db:{CONTAINER_SPOOL}/.", str(work)))\n'
    assert len(_copies_out_of_a_tmpfs("tools/trialbox/backup_schedule.py", bad, tmpfs)) == 1
    assert _copies_out_of_a_tmpfs("x.sh", '  "${COMPOSE[@]}" cp db:/tmp/x.sql "$OUT/"', tmpfs)
    # a copy out of a volume is not one (caddy's root certificate, install.sh)
    out = '"${COMPOSE[@]}" cp caddy:/data/caddy/pki/authorities/local/root.crt deploy/secrets/tls/caddy-root.crt'
    assert not _copies_out_of_a_tmpfs("x.sh", out, {**tmpfs, "caddy": ["/tmp"]})


def test_the_lint_names_a_service_without_the_controls() -> None:
    """Negative: a planted service missing each control is named for each; a stale exception and an unexplained
    cap_add are named too."""
    services = _merge((BASE,))
    services["lake"] = {**services["lake"], "read_only": False, "user": "0:0", "cap_drop": [], "security_opt": []}
    services["gateway"] = {**services["gateway"], "cap_add": ["NET_ADMIN"]}
    services["planted"] = {"image": "x"}
    services["adapter"] = {**services["adapter"], "read_only": True}
    found = problems(services, ("stub",))
    assert found == [
        "adapter: read_only applied but still in EXCEPTIONS",
        "gateway: cap_add NET_ADMIN without a reason in CAP_ADD",
        "lake: no cap_drop",
        "lake: no no-new-privileges",
        "lake: no read_only",
        "lake: no user",
        "planted: not one of the 15 and not in OUTSIDE_THE_15",
    ]


def _compose() -> bool:
    if not shutil.which("docker"):
        return False
    return subprocess.run(["docker", "compose", "version"], capture_output=True, check=False).returncode == 0


@pytest.mark.skipif(not _compose(), reason="needs the docker compose plugin")
@pytest.mark.parametrize(
    ("stack", "profiles"), HARDENING_STACKS, ids=lambda x: "+".join(x) if isinstance(x, tuple) else x
)
def test_compose_config_renders_the_controls(tmp_path: Path, stack: tuple[str, ...], profiles: tuple[str, ...]) -> None:
    two_device = "TB_LINK_ADDR=192.0.2.1\nTB_LINK_PEER=192.0.2.2\n"  # documentation addresses (RFC 5737)
    services = _render(tmp_path, stack, profiles, two_device if any("two-device/" in f for f in stack) else "")[
        "services"
    ]
    assert problems(services, profiles) == []
    if "db" in services:
        assert services["db"]["group_add"] == ["ssl-cert"]  # rendered by name, resolved in the image at start
    if stack == (BASE,):
        assert set(services) == THE_15  # both profiles: 15 of 15

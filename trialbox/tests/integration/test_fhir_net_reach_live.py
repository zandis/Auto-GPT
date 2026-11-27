"""P2-03 (ASSESS-1-ADDENDUM D2), live: a container that is not on fhir-net cannot connect to the FHIR store.

The networks are made from deploy/docker-compose.yml as it stands (each with its ``internal`` flag): the store joins
every network compose gives it, under its compose name; a client joins doc-parser's networks (the audit's untrusted-
document reader) and must get no answer, by name or by address; a client on fhir-net (the adapter's way in) must be
answered. The db image's PostgreSQL stands in for the store's listener (the port is what is reached, not HAPI). As
tests/integration/test_db_image.py: marker ``integration``, ``TB_INTEGRATION=1`` and a built db image.
"""

from __future__ import annotations

import subprocess
import time
import uuid

import pytest

from tests.integration.test_db_image import _docker, _image
from tests.unit.test_compose_limits import BASE, _load
from tests.unit.test_fhir_network_isolation import FHIR_NET, _networks

NO_RESPONSE = 2  # pg_isready: 0 accepting, 1 rejecting (reached, so not isolated), 2 no response, 3 no attempt


def expect(proc: subprocess.CompletedProcess[str], code: int) -> None:
    """The probe's exit code must be exactly ``code``: a probe that did not run (docker's 125-127) or a server that
    answered while rejecting (1) is never counted as isolation (#1597 review r1, R1/M1)."""
    assert proc.returncode == code, (proc.returncode, proc.stderr)


@pytest.mark.integration
def test_a_container_off_fhir_net_gets_no_answer_and_a_member_does() -> None:
    image = _image()
    nets = _networks((BASE,), ("stub", "gpu"))
    declared = _load(BASE)["networks"]
    tag = uuid.uuid4().hex[:8]
    made = {k: f"tb-fhirreach-{k}-{tag}" for k in nets["fhir-store"] | nets["doc-parser"] | {FHIR_NET}}
    store = f"tb-fhirreach-store-{tag}"
    created: list[str] = []
    try:
        for key, name in made.items():
            _docker("network", "create", *(["--internal"] if declared[key].get("internal") else []), name)
        first, *rest = sorted(nets["fhir-store"])
        _docker("run", "-d", "--name", store, "--network", made[first], "--network-alias", "fhir-store",
                "-e", "POSTGRES_PASSWORD=probe-only", image)  # fmt: skip
        for key in rest:
            _docker("network", "connect", "--alias", "fhir-store", made[key], store)
        # over TCP: the entrypoint's init server answers on the socket only (listen_addresses=''), not on the port
        for _ in range(90):
            if (
                _docker("exec", store, "pg_isready", "-q", "-h", "127.0.0.1", "-U", "postgres", check=False).returncode
                == 0
            ):
                break
            time.sleep(1)
        else:
            pytest.fail(
                f"the stand-in store never accepted TCP connections: {_docker('logs', store, check=False).stderr}"
            )
        addresses = _docker("inspect", "-f", "{{range .NetworkSettings.Networks}}{{.IPAddress}} {{end}}", store).stdout

        def probe(networks: list[str], host: str) -> subprocess.CompletedProcess[str]:
            args = ["--entrypoint", "pg_isready", image, "-h", host, "-t", "5", "-U", "postgres"]
            if len(networks) == 1:
                return _docker("run", "--rm", "--network", networks[0], *args, check=False)
            # a container on several networks: create, connect each, then start (removed in finally, started or not)
            cid = _docker("create", "--network", networks[0], *args).stdout.strip()
            created.append(cid)
            for n in networks[1:]:
                _docker("network", "connect", n, cid)
            return _docker("start", "-a", cid, check=False)

        expect(probe([made[FHIR_NET]], "fhir-store"), 0)  # the control first: the store is up and reachable
        reader = [made[k] for k in sorted(nets["doc-parser"])]
        expect(probe(reader, "fhir-store"), NO_RESPONSE)
        for ip in addresses.split():
            expect(probe(reader, ip), NO_RESPONSE)
        expect(probe([made[FHIR_NET]], "fhir-store"), 0)  # and still up after the negatives
    finally:
        for name in [*created, store]:
            _docker("rm", "-f", name, check=False)
        for name in made.values():
            _docker("network", "rm", name, check=False)


@pytest.mark.parametrize("code", [1, 3, 125, 126, 127])
def test_a_probe_that_was_answered_or_never_ran_is_not_isolation(code: int) -> None:
    """R1/M1 failing-first: the old ``returncode == 0`` read each of these as "no answer"."""
    with pytest.raises(AssertionError):
        expect(subprocess.CompletedProcess([], code, "", "err"), NO_RESPONSE)

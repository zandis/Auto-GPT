"""P2-03 (ASSESS-1-ADDENDUM D2), live: a container that is not on fhir-net cannot connect to the FHIR store.

The networks are made from deploy/docker-compose.yml as it stands (each with its ``internal`` flag): the store joins
every network compose gives it, under its compose name; a client joins doc-parser's networks (the audit's untrusted-
document reader) and must get no answer, by name or by address; a client on fhir-net (the adapter's way in) must be
answered. The db image's PostgreSQL stands in for the store's listener (the port is what is reached, not HAPI). As
tests/integration/test_db_image.py: marker ``integration``, ``TB_INTEGRATION=1`` and a built db image.
"""

from __future__ import annotations

import time
import uuid

import pytest

from tests.integration.test_db_image import _docker, _image
from tests.unit.test_compose_limits import BASE, _load
from tests.unit.test_fhir_network_isolation import FHIR_NET, _networks


@pytest.mark.integration
def test_a_container_off_fhir_net_gets_no_answer_and_a_member_does() -> None:
    image = _image()
    nets = _networks((BASE,), ("stub", "gpu"))
    declared = _load(BASE)["networks"]
    tag = uuid.uuid4().hex[:8]
    made = {k: f"tb-fhirreach-{k}-{tag}" for k in nets["fhir-store"] | nets["doc-parser"] | {FHIR_NET}}
    store = f"tb-fhirreach-store-{tag}"
    try:
        for key, name in made.items():
            _docker("network", "create", *(["--internal"] if declared[key].get("internal") else []), name)
        first, *rest = sorted(nets["fhir-store"])
        _docker("run", "-d", "--name", store, "--network", made[first], "--network-alias", "fhir-store",
                "-e", "POSTGRES_PASSWORD=probe-only", image)  # fmt: skip
        for key in rest:
            _docker("network", "connect", "--alias", "fhir-store", made[key], store)
        for _ in range(90):
            if _docker("exec", store, "pg_isready", "-q", "-U", "postgres", check=False).returncode == 0:
                break
            time.sleep(1)
        addresses = _docker("inspect", "-f", "{{range .NetworkSettings.Networks}}{{.IPAddress}} {{end}}", store).stdout

        def answered(networks: list[str], host: str) -> bool:
            run = ["run", "--rm", "--network", networks[0], "--entrypoint", "pg_isready", image]
            if len(networks) > 1:  # a container on several networks: create, connect each, then start
                cid = _docker("create", "--rm", *run[2:], "-h", host, "-t", "5", "-U", "postgres").stdout.strip()
                for n in networks[1:]:
                    _docker("network", "connect", n, cid)
                return _docker("start", "-a", cid, check=False).returncode == 0
            return _docker(*run, "-h", host, "-t", "5", "-U", "postgres", check=False).returncode == 0

        reader = [made[k] for k in sorted(nets["doc-parser"])]
        assert not answered(reader, "fhir-store")
        for ip in addresses.split():
            assert not answered(reader, ip), ip
        assert answered([made[FHIR_NET]], "fhir-store")
    finally:
        _docker("rm", "-f", store, check=False)
        for name in made.values():
            _docker("network", "rm", name, check=False)

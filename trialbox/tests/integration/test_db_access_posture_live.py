"""P2-06 (ASSESS-1-ADDENDUM D3/D4), live: the db image started with deploy/docker-compose.yml's own db settings.

Entrypoint, command, user, groups, tmpfs and the two access files are read from the compose file (its defaults put in
for ``${VAR:-default}``), with the read-only root and no capability. Then, on a new volume: the socket answers the
container's own user with TLS on and mode 0770; a client in another container on the same internal network gets TLS
by libpq's default and is refused when it asks for none; the key is 0600 to postgres in the tmpfs. As
tests/integration/test_db_image.py: marker ``integration``, ``TB_INTEGRATION=1`` and a built db image.
"""

from __future__ import annotations

import re
import time
import uuid

import pytest

from tests.integration.test_db_image import _docker, _image
from tests.unit.test_compose_limits import BASE, DEPLOY, _merge


def _env(value: object) -> str:
    """Compose's interpolation of a default, and ``$$``."""
    return re.sub(r"\$\{[A-Z0-9_]+:-([^}]*)\}", r"\1", str(value)).replace("$$", "$")


@pytest.mark.integration
def test_the_db_starts_as_compose_says_with_tls_and_no_trust() -> None:
    image = _image()
    db = _merge((BASE,))["db"]
    tag = uuid.uuid4().hex[:8]
    name, net, vol = f"tb-dbpost-{tag}", f"tb-dbpost-net-{tag}", f"tb-dbpost-vol-{tag}"
    entry, cmd = [_env(x) for x in db["entrypoint"]], [_env(x) for x in db["command"]]
    files = [("-v", f"{DEPLOY / src[2:]}:{dst}:ro") for src, dst, *_ in (str(v).split(":") for v in db["volumes"])
             if src.startswith("./docker/pg_")]  # fmt: skip
    opts = [a for t in db["tmpfs"] for a in ("--tmpfs", str(t))]
    opts += [a for g in db.get("group_add", []) for a in ("--group-add", str(g))]
    opts += [a for pair in files for a in pair]
    _docker("network", "create", "--internal", net)
    try:
        _docker("run", "-d", "--name", name, "--network", net, "--network-alias", "db", "--user", str(db["user"]),
                "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges:true", *opts,
                "-v", f"{vol}:/var/lib/postgresql/data", "-e", "POSTGRES_DB=hapi", "-e", "POSTGRES_USER=hapi",
                "-e", "POSTGRES_PASSWORD=probe-only", "--entrypoint", entry[0], image, *entry[1:], *cmd)  # fmt: skip
        for _ in range(120):
            if _docker("exec", name, "pg_isready", "-q", "-U", "hapi", "-d", "hapi", check=False).returncode == 0:
                break
            time.sleep(1)
        time.sleep(3)  # the image's first start restarts the server once after db-init
        sock = _docker("exec", name, "psql", "-X", "-At", "-U", "hapi", "-d", "hapi", "-c",
                       "select current_setting('ssl') || ' ' || current_setting('unix_socket_permissions')")  # fmt: skip
        assert sock.stdout.strip() == "on 0770"

        def tcp(mode: str) -> tuple[int, str, str]:
            r = _docker("run", "--rm", "--network", net, "-e", "PGPASSWORD=probe-only", "--entrypoint", "psql", image,
                        "-X", "-At", f"host=db dbname=hapi user=hapi{mode}", "-c",
                        "select ssl from pg_stat_ssl where pid = pg_backend_pid()", check=False)  # fmt: skip
            return r.returncode, r.stdout.strip(), r.stderr

        assert tcp("")[:2] == (0, "t")  # libpq's default sslmode (prefer): TLS
        rc, _out, err = tcp(" sslmode=disable")
        assert rc != 0 and "no encryption" in err
        key = _docker("exec", name, "stat", "-c", "%a %U", "/tmp/tb-db-tls.key").stdout.split()
        assert key == ["600", "postgres"]
    finally:
        _docker("rm", "-f", name, check=False)
        _docker("network", "rm", net, check=False)
        _docker("volume", "rm", vol, check=False)

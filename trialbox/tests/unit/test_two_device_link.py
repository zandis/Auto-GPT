"""The two-device link (T-214, D-373): mutual TLS 1.3 between the Spark and the workstation, real sockets on 127.0.0.1.

The card's acceptance (4), "the link refuses an unauthenticated peer", here on one host; the bench run on two devices
is left to the Spark.
"""

from __future__ import annotations

import asyncio
import ssl
import stat
from pathlib import Path

import pytest

from tools import two_device as td


def test_selftest_round_trip_and_every_refusal(tmp_path: Path) -> None:
    results = asyncio.run(td.selftest_async(tmp_path))
    assert dict(results) == {
        "an authenticated peer reaches the exported route": True,
        "a peer without a certificate is refused": True,
        "a peer of another link CA is refused": True,
        "a peer that names this device, not the other, is refused": True,
        "an unknown route is refused": True,
    }


def test_selftest_command() -> None:
    assert td.main(["selftest"]) == 0


def test_certs_name_each_device_and_keep_no_ca_key(tmp_path: Path) -> None:
    from cryptography import x509

    written = td.make_certs(tmp_path / "c", days=2)
    assert sorted(p.name for p in written) == sorted(
        ["ca.pem", "spark.pem", "spark.key", "workstation.pem", "workstation.key"]
    )
    assert not list((tmp_path / "c").glob("ca.key"))
    for role in td.ROLES:
        assert stat.S_IMODE((tmp_path / "c" / f"{role}.key").stat().st_mode) == 0o600
        cert = x509.load_pem_x509_certificate((tmp_path / "c" / f"{role}.pem").read_bytes())
        san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
        assert san.get_values_for_type(x509.DNSName) == [td.link_name(role)]


def test_the_contexts_require_tls13_and_a_peer_certificate(tmp_path: Path) -> None:
    td.make_certs(tmp_path, days=2)
    cfg = td.LinkConfig("spark", "127.0.0.1", tmp_path)
    for server in (True, False):
        ctx = td._context(cfg, server=server)
        assert ctx.minimum_version == ssl.TLSVersion.TLSv1_3
        assert ctx.verify_mode == ssl.CERT_REQUIRED
        assert ctx.check_hostname is (not server)


def test_link_config_from_the_environment() -> None:
    cfg = td.LinkConfig.from_env({"TB_LINK_ROLE": "spark", "TB_LINK_PEER": "10.20.0.3", "TB_LINK_PORT": "9443"})
    assert cfg.routes == {"gateway": ("gateway", 8020)}
    assert cfg.imports == {"db": 5432}
    assert (cfg.port, cfg.peer_port, cfg.certs) == (9443, 9443, Path("/run/secrets/tb_link"))
    ws = td.LinkConfig.from_env({"TB_LINK_ROLE": "workstation", "TB_LINK_PEER": "10.20.0.2", "TB_LINK_PEER_PORT": "1"})
    assert ws.routes == {"db": ("db", 5432)} and ws.imports == {"gateway": 8020}
    assert (ws.port, ws.peer_port) == (td.LINK_PORT, 1)


@pytest.mark.parametrize(
    "env", [{}, {"TB_LINK_ROLE": "spark"}, {"TB_LINK_ROLE": "laptop", "TB_LINK_PEER": "10.20.0.3"}]
)
def test_link_config_refuses_a_missing_role_or_peer(env: dict[str, str]) -> None:
    with pytest.raises(ValueError):
        td.LinkConfig.from_env(env)


def test_an_unreachable_route_target_is_refused_not_hung(tmp_path: Path) -> None:
    async def go() -> bytes:
        td.make_certs(tmp_path, days=1)
        spark = td.Link(
            td.LinkConfig(
                "spark", "127.0.0.1", tmp_path, port=0, bind="127.0.0.1", routes={"gateway": ("127.0.0.1", 1)}
            )
        )
        await spark.start()
        try:
            ctx = ssl.create_default_context(cafile=str(tmp_path / "ca.pem"))
            ctx.load_cert_chain(str(tmp_path / "workstation.pem"), str(tmp_path / "workstation.key"))
            got = await td._try_raw(spark.cfg.port, ctx, td.HELLO + b"gateway\n")
        finally:
            await spark.close()
        assert spark.refused == 1
        return got

    assert asyncio.run(go()) == b"ERR\n"


def test_a_workstation_import_with_no_peer_closes_the_caller(tmp_path: Path) -> None:
    async def go() -> bytes:
        td.make_certs(tmp_path, days=1)
        ws = td.Link(
            td.LinkConfig(
                "workstation", "127.0.0.1", tmp_path, port=0, peer_port=1, bind="127.0.0.1", imports={"gateway": 0}
            )
        )
        await ws.start()
        try:
            r, w = await asyncio.open_connection("127.0.0.1", ws.import_port("gateway"))
            w.write(b"GET / HTTP/1.0\r\n\r\n")
            await w.drain()
            got = await asyncio.wait_for(r.read(), 15)
            w.close()
        finally:
            await ws.close()
        return got

    assert asyncio.run(go()) == b""

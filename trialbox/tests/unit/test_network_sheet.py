"""TB-PLAN-04 step 8 (D-138): the one-page network, port and secret sheet lists every listening port of every
compose file a box runs, in three languages, and never a secret value."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from tools import network_sheet as ns

ROOT = Path(__file__).resolve().parents[2]
SHEET = ROOT / "docs/handover/network-sheet"
OVERLAYS = sorted(p.name for p in (ROOT / "deploy").glob("docker-compose.*.yml"))


class _AnyTag(yaml.SafeLoader):
    """compose's merge tags (!reset, !override) read as plain values: the test's own reading, not the sheet's."""


_AnyTag.add_multi_constructor(
    "!",
    lambda loader, suffix, node: (
        loader.construct_sequence(node) if isinstance(node, yaml.SequenceNode)
        else loader.construct_mapping(node) if isinstance(node, yaml.MappingNode)
        else loader.construct_scalar(node)
    ),
)  # fmt: skip


def _compose_ports() -> dict[str, set[int]]:
    """Independently of the sheet's code: every port the compose files say a service listens on."""
    out: dict[str, set[int]] = {}
    for f in ns.FILES:
        doc = yaml.load((ROOT / f).read_text(encoding="utf-8"), Loader=_AnyTag)
        for name, svc in (doc.get("services") or {}).items():
            got = out.setdefault(name, set())
            text = " ".join(str(c) for c in (svc.get("command") or []))
            got |= {int(m) for m in re.findall(r"--port[= ](\d+)", text)}
            got |= {int(str(p).rsplit(":", 1)[-1]) for p in svc.get("ports") or []}
            got |= {int(str(e).split("/")[0]) for e in svc.get("expose") or []}
            image = str(svc.get("image") or "")
            if not got and name not in ns.NO_LISTEN:
                got |= {p for k, p in ns.IMAGE_PORTS.items() if k in image}
    return out


def test_the_production_compose_set_is_the_one_install_uses() -> None:
    sh = (ROOT / "deploy/install.sh").read_text(encoding="utf-8")
    for f in ns.FILES:
        assert f in sh, f"install.sh does not use {f}"


def test_every_service_has_its_ports_or_is_a_one_shot_job() -> None:
    ports = _compose_ports()
    for name, got in ports.items():
        assert got or name in ns.NO_LISTEN, f"{name}: no listening port known; add it to the sheet's rules"
    sheet = {s.name: set(s.ports) for s in ns.services(list(ns.FILES))}
    assert set(sheet) == set(ports)
    for name, got in ports.items():
        assert got <= sheet[name] | {8090}, name  # console's host port maps to 8090


@pytest.mark.parametrize("lang", ns.LANGS)
def test_the_committed_sheet_lists_every_port_and_is_up_to_date(lang: str) -> None:
    md = SHEET.with_name(f"network-sheet.{lang}.md").read_text(encoding="utf-8")
    html = SHEET.with_name(f"network-sheet.{lang}.html").read_text(encoding="utf-8")
    assert md == ns.render_md(list(ns.FILES), None, lang), "regenerate: python -m tools.network_sheet"
    assert html == ns.render_html(list(ns.FILES), None, lang), "regenerate: python -m tools.network_sheet"
    ports_part = md.split(f"## {ns.T['ports'][lang]}")[1].split("\n## ")[0]
    rows = {ln.split("|")[1].strip(): ln for ln in ports_part.splitlines() if ln.startswith("| ") and "---" not in ln}
    for name, ports in _compose_ports().items():
        assert name in rows, f"{name} missing from the {lang} sheet"
        for p in ports:
            assert re.search(rf"\b{p}\b", rows[name]), f"{name}:{p} missing from the {lang} sheet"
    # T-632: every PRODUCTION box runs behind Caddy; the console's own port is not published (identity overlay)
    assert ns.T["not_published"][lang] in rows["console"] and "0.0.0.0:443:443" in rows["caddy"]
    assert "@page" in html and "A4 landscape" in html  # prints on one page


def test_a_site_sheet_shows_the_sites_hosts_and_no_secret(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text(
        "SMTP_HOST=smtp.hospa.example\nSMTP_PORT=587\nIMAP_HOST=imap.hospa.example\nIMAP_PASS=imap-secret-xyz\n"
        "SMTP_PASS=smtp-secret-xyz\nPOSTGRES_PASSWORD=pg-secret-xyz\nTB_SERVICE_TOKEN=tok-secret-xyz\n"
        "CLOUD_LLM_API_KEY=key-secret-xyz\nTB_CTGOV_MODE=cassette\n",
        encoding="utf-8",
    )
    out = tmp_path / "site" / "network-sheet"
    assert ns.main(["--env", str(env), "--out", str(out)]) == 0
    for lang in ns.LANGS:
        for ext in ("md", "html"):
            text = out.with_name(f"network-sheet.{lang}.{ext}").read_text(encoding="utf-8")
            assert "smtp.hospa.example:587" in text and "imap.hospa.example:993" in text
            assert "clinicaltrials.gov" not in text  # closed with TB_CTGOV_MODE=cassette
            assert "secret-xyz" not in text
    assert ns.main(["--env", str(env), "--out", str(out), "--check"]) == 0


def test_every_secret_has_a_place_and_the_services_that_get_it() -> None:
    md = SHEET.with_name("network-sheet.en.md").read_text(encoding="utf-8")
    for svc in ("lake", "orchestrator", "console", "mail-gateway", "gateway", "doc-parser"):
        assert f"service token: {svc} | deploy/secrets/services/{svc}.token (0600) | {svc} only" in md
    assert "| IMAP_PASS, SMTP_PASS | deploy/.env (0600, root) | mail-gateway |" in md
    assert "| CLOUD_LLM_API_KEY (empty by default) | deploy/.env (0600, root) | gateway |" in md
    assert "doc-parser" not in md.split("POSTGRES_WF_PASSWORD")[1].split("\n")[0]  # cleared where never used


@pytest.mark.parametrize("overlay", OVERLAYS)
def test_every_overlay_renders(overlay: str, tmp_path: Path) -> None:
    """OPS-014: the sheet renders the base, the secrets and each overlay (compose's !reset and !override too)."""
    files = ["deploy/docker-compose.yml", "deploy/docker-compose.secrets.yml", f"deploy/{overlay}"]
    for lang in ns.LANGS:
        md = ns.render_md(files, None, lang)
        assert ns.T["host_h"][lang] in md and "NTP" in md and "backup share" in md
        assert ns.render_html(files, None, lang).startswith("<!doctype html>")
    assert ns.main(["--files", ":".join(files), "--out", str(tmp_path / "s")]) == 0


def test_the_identity_overlay_shows_443_ldaps_and_no_console_port(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("TB_TLS_HOSTNAME=trialbox.hospa.example\nTB_BACKUP_TARGETS=/mnt/tb-backup\n", encoding="utf-8")
    files = "deploy/docker-compose.yml:deploy/docker-compose.secrets.yml:deploy/docker-compose.identity.yml"
    out = tmp_path / "site" / "network-sheet"
    assert ns.main(["--files", files, "--env", str(env), "--out", str(out)]) == 0
    md = out.with_name("network-sheet.en.md").read_text(encoding="utf-8")
    rows = {ln.split("|")[1].strip(): ln for ln in md.splitlines() if ln.startswith("| ")}
    assert "443" in rows["caddy"] and "not published" in rows["console"]  # !reset [] took the console's port away
    assert "clinic PCs -> trialbox.hospa.example:443 (caddy)" in md
    assert "authelia -> domain controller:636 (LDAPS)" in md
    assert "host -> backup share (/mnt/tb-backup)" in md and "UDP 123" in md
    assert "Caddy's internal CA keys" in md and "| oidc_client_secret |" in md

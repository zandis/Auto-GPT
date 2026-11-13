"""T-717 (D-485; trust review TR-5): the key that signs people is not the console's service token.

The console sends its token on every call, to the orchestrator and to the mail gateway and the adapter. Until this
card the actor-signing key was ``HMAC(token, label)``: every service that received a console call could compute it
and name any person to the orchestrator. The tests take that position (a callee that holds the console's token and
nothing else) and sign a person the old way; the orchestrator must not accept it.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from pathlib import Path
from typing import Any

import pytest
from tb_common import actor_v3 as v3
from tb_common import service_auth as sa

from tests.service_tokens import per_service_tokens, token_of


def _forged_v2(key: bytes, actor: str, role: str, scope: str) -> str:
    exp, nonce = int(time.time()) + 60, secrets.token_urlsafe(16)[:22]
    return f"{sa.ACTOR_VERSION}.{exp}.s1.{nonce}.{sa._actor_mac(key, actor, 's1', exp, nonce, role, scope)}"


def _forged_v3(key: bytes, **claim: Any) -> str:
    t = int(time.time())
    doc = {"sub": "console:dr_tanaka", "role": "investigator", "session": "s1", "study": "GZQO",
           "standing": {"is_pi": True, "tasks": [], "log_names_pi": True, "monitor": False},
           "action": "id.reveal", "target": "POST /jobs/J1/reveal", "grant": None, "reauth_at": None,
           "body": v3.body_hash({"pid": "PID-00000001"}), "nonce": secrets.token_urlsafe(16)[:22], "iat": t,
           "exp": t + 60, **claim}  # fmt: skip
    b64 = base64.urlsafe_b64encode(json.dumps(doc, sort_keys=True, separators=(",", ":")).encode()).decode().rstrip("=")
    head = f"v3.{b64}"
    return f"{head}.{hmac.new(key, head.encode('ascii'), hashlib.sha256).hexdigest()}"


def test_a_holder_of_the_consoles_token_cannot_sign_a_person(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The acceptance of the first clause of the row: with nothing but the console's token, no assertion verifies."""
    per_service_tokens(tmp_path, monkeypatch)  # a box: the registry, the orchestrator's keys file, the console's key
    received = token_of("console")  # what the mail gateway and the adapter see on every console call
    derived = sa.actor_key(received)  # the old key: a function of the token
    with pytest.raises(sa.ActorError, match="does not verify"):
        sa.verify_actor("dr_tanaka", _forged_v2(derived, "dr_tanaka", "investigator", "*"), role="investigator",
                        scope="*", replay=sa.ReplayGuard())  # fmt: skip
    with pytest.raises(sa.ActorError, match="does not verify"):
        v3.verify(_forged_v3(derived), replay=sa.ReplayGuard())
    # the console itself, which holds the signing key, still signs
    who = sa.verify_actor("dr_tanaka", sa.sign_actor("dr_tanaka", "s1", role="investigator", scope="*"),
                          role="investigator", scope="*", replay=sa.ReplayGuard())  # fmt: skip
    assert who.verified and who.name == "dr_tanaka"
    tok = v3.mint(sub="console:crc", role="coordinator", action="study.setup", method="POST", path="/x", study="GZQO")
    assert v3.verify(tok, replay=sa.ReplayGuard()).verified


def test_who_holds_a_signing_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """``signing_key``: the file of the console's compose secret; on a box with per-service tokens nothing else."""
    per_service_tokens(tmp_path, monkeypatch)
    key = sa.signing_key()
    assert key is not None and len(key) == 32 and key != sa.actor_key(token_of("console"))
    # a service of the box without the secret (every service but the console) signs nobody, with either format
    monkeypatch.delenv(sa.ACTOR_SIGN_KEY_ENV)
    assert sa.signing_key() is None and sa.sign_actor("dr_tanaka") is None
    assert sa.ASSERTION_HEADER not in sa.actor_header("dr_tanaka", role="investigator", scope="*")
    assert v3.mint(sub="console:crc", role="coordinator", action="study.setup", method="POST", path="/x").endswith(".")
    # a key file that cannot be read, or is not a key: no key (fail closed), never a fall-back to the token
    for bad in ("/nonexistent/actor-sign.key", str(tmp_path / "short.key")):
        (tmp_path / "short.key").write_text("abcd\n", encoding="utf-8")
        monkeypatch.setenv(sa.ACTOR_SIGN_KEY_ENV, bad)
        assert sa.signing_key() is None and sa.sign_actor("dr_tanaka") is None
    # one shared token and no registry (tests, `make demo`, a box before per-service tokens): every service holds
    # that token anyway, and the key is derived from it as before
    monkeypatch.delenv(sa.ACTOR_SIGN_KEY_ENV)
    monkeypatch.delenv(sa.REGISTRY_ENV)
    monkeypatch.delenv(sa.ACTOR_KEYS_ENV)
    assert sa.signing_key() == sa.actor_key(token_of("console"))
    who = sa.verify_actor("dr_tanaka", sa.sign_actor("dr_tanaka", "s1"), replay=sa.ReplayGuard())
    assert who.verified
    monkeypatch.delenv("TB_SERVICE_TOKEN")  # no token at all (DEV, TEST): nothing is signed, nothing verified
    assert sa.signing_key() is None and sa.actor_keys() is None


def test_the_update_gives_an_older_box_its_signing_key(tmp_path: Path) -> None:
    """A box with per-service tokens from before this card has no ``actor-sign.key``; the secrets overlay needs the
    file. ``trialbox update`` makes it (``ensure_actor_sign_key``), and the orchestrator's keys file from it."""
    from tools.trialbox import svc_secrets as sx

    deploy = tmp_path / "deploy"
    sx.init(deploy, uid=None)
    sign, keys = sx.actor_sign_key_path(deploy), sx.actor_keys_path(deploy)
    sign.unlink()
    keys.write_text(sx.actor_key_hex(sx.token_path(deploy, "console").read_text().strip()) + "\n")  # the old file
    assert sx.ensure_actor_sign_key(deploy, None) is True
    made = sign.read_text(encoding="utf-8").strip()
    assert len(made) == 64 and keys.read_text(encoding="utf-8").split() == [made]  # the token-derived key is gone
    assert sx.ensure_actor_sign_key(deploy, None) is False and sign.read_text(encoding="utf-8").strip() == made
    src = (Path(sx.__file__).parent / "update.py").read_text(encoding="utf-8")
    assert "ensure_actor_sign_key(self.deploy)" in src


@pytest.mark.xfail(strict=True, reason="T-717 not done (trust review F8): the adapter and the orchestrator share one "
                                       "secrets volume, so the adapter can open edc_sign.key and audit_sign.key")  # fmt: skip
def test_the_adapter_cannot_open_the_edc_or_audit_signing_keys() -> None:
    """The acceptance of the row's last clause, recorded as it stands. It becomes a pass, and this mark an error,
    when the keys of the orchestrator alone (the EDC and audit signing keys, the object key) live on a volume the
    adapter does not mount."""
    import yaml

    doc = yaml.safe_load(
        (Path(__file__).resolve().parents[2] / "deploy/docker-compose.yml").read_text(encoding="utf-8")
    )

    def secret_volumes(service: str) -> set[str]:
        return {str(v).split(":")[0] for v in doc["services"][service].get("volumes", []) if "secrets" in str(v)}

    assert not secret_volumes("adapter") & secret_volumes("orchestrator")


# ------------------------------------------------------------------------------ the adversarial review's findings
def test_a_service_that_can_sign_nobody_says_so_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                                     caplog: pytest.LogCaptureFixture) -> None:  # fmt: skip
    """Review M2: a console without a usable key signed nobody and said nothing; every person's action was then a
    403 at the orchestrator with no reason at the source."""
    per_service_tokens(tmp_path, monkeypatch)
    bad = tmp_path / "unreadable.key"
    bad.write_text("not a key\n", encoding="utf-8")
    monkeypatch.setenv(sa.ACTOR_SIGN_KEY_ENV, str(bad))
    monkeypatch.setattr(sa, "_NO_KEY_SAID", False)
    with caplog.at_level("ERROR", logger="tb.service_auth"):
        assert sa.signing_key() is None and sa.signing_key() is None
    said = [r for r in caplog.records if "can sign nobody" in r.getMessage()]
    assert len(said) == 1 and str(bad) in said[0].getMessage() and "not a key" not in said[0].getMessage()


def test_the_status_lists_the_signing_key_and_never_its_value(tmp_path: Path) -> None:
    """Review M2: `trialbox secrets status` did not list the key, so a box without it looked whole."""
    from tools.trialbox import svc_secrets as ss

    deploy = tmp_path / "deploy"
    deploy.mkdir()
    row = next(r for r in ss.status(deploy) if r["name"] == "actor signing key")
    assert row["present"] is False
    ss.ensure_actor_sign_key(deploy, uid=None)
    key = ss.actor_sign_key_path(deploy).read_text(encoding="utf-8").strip()
    row = next(r for r in ss.status(deploy) if r["name"] == "actor signing key")
    assert row["present"] is True and row["mode"] == "0o600" and key not in json.dumps(ss.status(deploy))


def test_the_tool_and_the_service_agree_on_what_a_key_is(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Review L3: the tool took an upper-case hex key for no key and replaced it; the service accepted it."""
    from tools.trialbox import svc_secrets as ss

    deploy = tmp_path / "deploy"
    deploy.mkdir()
    upper = secrets.token_hex(32).upper()
    path = ss.actor_sign_key_path(deploy)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(upper + "\n", encoding="utf-8")
    assert ss.ensure_actor_sign_key(deploy, uid=None) is False  # a key the service accepts is not replaced
    assert path.read_text(encoding="utf-8").strip() == upper
    monkeypatch.setenv(sa.ACTOR_SIGN_KEY_ENV, str(path))
    assert sa.signing_key() == bytes.fromhex(upper)

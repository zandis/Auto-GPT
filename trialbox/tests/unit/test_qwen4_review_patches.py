"""Regression tests for the model-suggested fixes of the Qwen4 Max review (2026-11-24); pure, no database."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json

import pytest
from datacore.forms import Field
from edc import prefill
from edc_backend import events, oidc
from edc_backend.config import load_config

TOKEN_A = "A" * 32
TOKEN_B = "B" * 32


def _forged(sub: str, aud: str = "edc") -> str:
    def b64(raw: bytes) -> str:
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    head = b64(b'{"alg":"HS256","typ":"JWT"}')
    body = b64(json.dumps({"sub": sub, "aud": aud, "exp": 9_999_999_999}).encode())
    sig = hmac.new(b"", f"{head}.{body}".encode(), hashlib.sha256).digest()
    return f"{head}.{body}.{b64(sig)}"


def test_an_empty_client_secret_neither_signs_nor_verifies_a_token() -> None:
    env = {"TB_EDC_OIDC": "1", "TB_EDC_OIDC_CLIENT_ID": "edc", "TB_EDC_OIDC_CLIENT_SECRET": ""}
    assert oidc.subject_of(_forged("admin"), env) is None
    with pytest.raises(ValueError):
        oidc.sign_id_token("crc", env)
    env["TB_EDC_OIDC_CLIENT_SECRET"] = "oidc-secret"
    assert oidc.subject_of(oidc.sign_id_token("crc", env), env) == "crc"


def test_an_integer_is_not_shown_by_a_quote_of_its_leading_digit() -> None:
    f = Field(name="hr", form="vs", kind="integer", label="HR")
    assert prefill._value_in_quote(f, "70", "HR 70 bpm")
    assert not prefill._value_in_quote(f, "70", "HR 7 bpm")
    d = Field(name="t", form="vs", kind="decimal", label="T")
    assert prefill._value_in_quote(d, "7.0", "pH 7 today")


def test_a_non_hex_event_signature_is_refused_not_raised() -> None:
    assert events.signature_ok("s3cret", b"{}", "sha256=" + "é" * 64) is False
    assert events.signature_ok("s3cret", b"{}", "sha256=zz") is False
    good = hmac.new(b"s3cret", b"{}", hashlib.sha256).hexdigest()
    assert events.signature_ok("s3cret", b"{}", "sha256=" + good) is True


def test_the_short_token_alias_never_overrides_the_tb_setting() -> None:
    cfg = load_config(
        {
            "TB_EDC_BACKEND": "redcap",
            "TB_REDCAP_API_URL": "https://redcap.example/",
            "TB_REDCAP_TOKEN_gzqo": TOKEN_B,
            "REDCAP_TOKEN_gzqo": TOKEN_A,
            "REDCAP_TOKEN_rabio": TOKEN_A,
        }
    )
    assert cfg.token_for("gzqo") == TOKEN_B
    assert cfg.token_for("rabio") == TOKEN_A

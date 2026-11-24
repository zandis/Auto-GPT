"""Bug-hunt probe BH1-05: the KMS client follows a redirect to another host with the KMS token.

Entry point: ``tb_common.kek.kms_seal`` / ``kms_open`` (``_kms_call``). The address is the operator's
``TB_KMS_URL`` or the ``kms_url`` recorded in ``kek.json``; the redirect is whatever answers at that address.
``_kms_endpoint`` allows only https (or loopback http), but the opener ``_kms_call`` builds keeps urllib's default
redirect handler, which re-sends the request's headers (the token header among them) to the ``Location`` it is
given, on any host and over plain http.

No network: the opener's http and https handlers are replaced by a stand-in that records each request and answers
it; the product's own redirect handling is left as it is.
"""

from __future__ import annotations

import contextlib
import email.message
import io
import json
import urllib.request
import urllib.response
from typing import Any

import pytest
from tb_common import kek

KMS = "https://kms.example.org/v1/transit"
OTHER = "http://other.example.org/collect"
TOKEN = "synthetic-kms-token-0000"  # a synthetic value, not a credential


class _Resp(urllib.response.addinfourl):
    msg: str  # the status text the redirect handler reads


def _answer(url: str, code: int, body: bytes, headers: dict[str, str]) -> Any:
    msg = email.message.Message()
    for k, v in headers.items():
        msg[k] = v
    resp = _Resp(io.BytesIO(body), msg, url, code)
    resp.msg = "Found" if code == 302 else "OK"  # read by the redirect handler
    return resp


def _stand_in(seen: list[tuple[str, dict[str, str]]]) -> tuple[type, type]:
    def answer(req: urllib.request.Request) -> Any:
        seen.append((req.full_url, {k.lower(): v for k, v in req.header_items()}))
        if req.host == "kms.example.org":
            return _answer(req.full_url, 302, b"", {"Location": OTHER})
        return _answer(req.full_url, 200, json.dumps({"data": {"ciphertext": "v1:AAAA"}}).encode(),
                       {"Content-Type": "application/json"})  # fmt: skip

    class FakeHttps(urllib.request.HTTPSHandler):
        def https_open(self, req: urllib.request.Request) -> Any:
            return answer(req)

    class FakeHttp(urllib.request.HTTPHandler):
        def http_open(self, req: urllib.request.Request) -> Any:
            return answer(req)

    return FakeHttps, FakeHttp


@pytest.mark.xfail(
    strict=True,
    reason="open finding: BH1-05: the KMS call follows a 302 to another host and plain http with the token header",
)
def test_kms_token_is_not_sent_to_a_redirect_target(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[tuple[str, dict[str, str]]] = []
    fake_https, fake_http = _stand_in(seen)
    real = urllib.request.build_opener

    def build_opener(*handlers: Any) -> urllib.request.OpenerDirector:
        return real(*handlers, fake_https, fake_http)

    monkeypatch.setattr(urllib.request, "build_opener", build_opener)
    with contextlib.suppress(kek.KekError):  # refusing the redirect is the safe outcome
        kek.kms_seal(b"\x00" * kek.KEK_LEN, KMS, "trialbox", TOKEN)
    assert seen and seen[0][0].startswith(KMS)  # the stand-in was reached: the probe ran
    leaked = [url for url, hdr in seen if TOKEN in hdr.values() and not url.startswith(KMS)]
    assert leaked == [], f"the KMS token was sent to {leaked}"

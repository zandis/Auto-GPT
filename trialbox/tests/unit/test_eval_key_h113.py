"""H-113: the model-quality suites send ``TB_LLM_EVAL_KEY`` as a Bearer credential to a local endpoint only.

* The suites marked ``llm`` (the gpu stage of ``tools/full_set.py``) run against a strict stand-in that wants the key
  (``tools/vllm_standin.py``): with the key set nothing is skipped and the stand-in answers no call with 401; without
  it the same calls get 401.
* A planted synthetic key appears in no stdout, stderr, log file, junit report or exception text of that run.
* A host that is not local never receives it; unset, the requests are the plain client's, byte for byte.

No model, no network: everything is on the loopback. The key is a made-up value."""

from __future__ import annotations

import os
import socket
import subprocess
import threading
import xml.etree.ElementTree as ET
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
from tb_common.llm import LlmClient, LlmError
from tb_testkit.eval_key import ENV, LocalBearer, eval_client, is_local

from tools import vllm_standin as vs

# the pure tests are `nodb`; the two that start the gpu stage are not: its judge suite needs the test database
NODB = pytest.mark.nodb

ROOT = Path(__file__).resolve().parents[2]
PLANTED = "h113-synthetic-eval-key-7f3c9a1e5d"  # made up for this test; recognisable in any output
SERVED = "h113-standin"
VARIABLES = {"ruleset": "H113", "language": "en", "criteria": [{"text": "Age >= 18", "kind": "inc", "source_ref": "1"}]}


@pytest.fixture()
def standin() -> Iterator[tuple[vs.Standin, str]]:
    s = vs.Standin([SERVED], PLANTED)
    srv = vs.serve(s)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        yield s, f"http://127.0.0.1:{srv.server_address[1]}/v1"
    finally:
        srv.shutdown()
        srv.server_close()


@NODB
@pytest.mark.parametrize(
    ("host", "local"),
    [
        ("localhost", True),
        ("LOCALHOST.", True),
        ("box.localhost", True),
        ("127.0.0.1", True),
        ("127.8.9.10", True),
        ("::1", True),
        ("[::1]", True),
        ("model-guard", True),
        ("llm-service", True),
        ("llm-verifier-vllm", True),
        ("10.1.2.3", True),
        ("172.20.0.5", True),
        ("192.168.1.9", True),
        ("169.254.1.1", True),
        ("fd00::7", True),
        ("", False),
        ("example.org", False),
        ("llm-service.example.org", False),
        ("localhost.example.org", False),
        ("gateway", False),
        ("bench", False),
        ("8.8.8.8", False),
        ("203.0.113.7", False),
        ("172.32.0.1", False),
        ("2001:db8::1", False),
    ],
)
def test_is_local_is_exactly_the_documented_set(host: str, local: bool) -> None:
    assert is_local(host) is local


def _recording(seen: list[httpx.Request], location: str = "") -> httpx.MockTransport:
    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        if location and req.url.host != httpx.URL(location).host:
            return httpx.Response(307, headers={"Location": location})
        return httpx.Response(200, json={"data": []})

    return httpx.MockTransport(handler)


@NODB
def test_a_host_that_is_not_local_never_gets_the_key() -> None:
    # the client refuses a set key with a public endpoint, and says so without the key
    with pytest.raises(ValueError) as exc:
        eval_client("https://llm.example.org/v1", SERVED, {ENV: PLANTED})
    assert PLANTED not in str(exc.value) and PLANTED not in repr(exc.value)
    assert "llm.example.org" in str(exc.value)
    # per request: only the endpoint's own local host gets it, a redirect elsewhere or any other host does not
    seen: list[httpx.Request] = []
    with httpx.Client(
        auth=LocalBearer("127.0.0.1", PLANTED),
        transport=_recording(seen, "http://203.0.113.7/v1/models"),
        follow_redirects=True,
    ) as c:
        c.get("http://127.0.0.1:8000/v1/models")
        c.get("http://203.0.113.7/v1/models")
        c.get("http://example.org/v1/models")
        c.get("http://localhost:8000/v1/models")  # local, but not the endpoint's host
    got = {(str(r.url.host), "authorization" in r.headers) for r in seen}
    assert got == {("127.0.0.1", True), ("203.0.113.7", False), ("example.org", False), ("localhost", False)}
    # a binding to a public host sends nothing, even to that host
    seen.clear()
    with httpx.Client(auth=LocalBearer("example.org", PLANTED), transport=_recording(seen)) as c:
        c.get("http://example.org/v1/models")
    assert "authorization" not in seen[0].headers


def _raw_requests(make: object) -> list[bytes]:
    """Every request ``make(url)``'s client sends for one ``chat_json``, as the bytes on the wire."""
    srv = socket.create_server(("127.0.0.1", 0))
    url = f"http://127.0.0.1:{srv.getsockname()[1]}/v1"
    got: list[bytes] = []

    def serve() -> None:
        srv.settimeout(10)
        while True:
            try:
                conn, _ = srv.accept()
            except OSError:
                return
            with conn:
                buf = b""
                while b"\r\n\r\n" not in buf:
                    buf += conn.recv(65536)
                head, _, body = buf.partition(b"\r\n\r\n")
                length = next(
                    (int(h.split(b":")[1]) for h in head.split(b"\r\n") if h.lower().startswith(b"content-length")), 0
                )
                while len(body) < length:
                    body += conn.recv(65536)
                got.append(head + b"\r\n\r\n" + body)
                conn.sendall(b"HTTP/1.1 400 Bad Request\r\nContent-Length: 2\r\nConnection: close\r\n\r\n{}")

    t = threading.Thread(target=serve, daemon=True)
    t.start()
    client = make(url)  # type: ignore[operator]
    with pytest.raises(LlmError):
        client.chat_json("ir_extract", VARIABLES, job_id="H113")
    client.http.close()
    srv.close()
    t.join(5)
    hostport = url.split("/")[2].encode()
    return [r.replace(hostport, b"127.0.0.1:PORT") for r in got]  # each call has its own port; the rest is compared


@NODB
def test_unset_or_empty_key_sends_todays_requests_byte_for_byte() -> None:
    plain = _raw_requests(lambda u: LlmClient(u, SERVED))
    assert plain
    assert _raw_requests(lambda u: eval_client(u, SERVED, {})) == plain
    assert _raw_requests(lambda u: eval_client(u, SERVED, {ENV: ""})) == plain
    keyed = _raw_requests(lambda u: eval_client(u, SERVED, {ENV: PLANTED}))
    auth = f"Authorization: Bearer {PLANTED}\r\n".encode()
    assert all(auth.lower() in r.lower() for r in keyed)
    stripped = [b"".join(line for line in r.splitlines(keepends=True) if line.lower() != auth.lower()) for r in keyed]
    assert stripped == plain  # the key is the only difference


@NODB
def test_no_object_shows_the_key() -> None:
    client = eval_client("http://127.0.0.1:9/v1", SERVED, {ENV: PLANTED})
    for obj in (client, client.http, client.http.auth, vars(client.http.auth)):
        assert PLANTED not in repr(obj) and PLANTED not in str(obj)
    with pytest.raises(LlmError) as exc:  # nothing listens on port 9: the error names the endpoint, not the key
        client.chat_json("ir_extract", VARIABLES, job_id="H113")
    assert PLANTED not in repr(exc.value) and PLANTED not in str(exc.value)
    assert all(PLANTED not in str(getattr(exc.value, a, "")) for a in ("__cause__", "__context__"))


def _gpu_stage(url: str, out: Path, key: str | None, *extra: str) -> tuple[int, list[ET.Element]]:
    """The gpu stage's own command and environment (``tools.full_set``) against ``url``, all it writes under ``out``.

    The child session starts its own test database under ``out``: never the cluster of this session or of its xdist
    worker (review 1460-1)."""
    import argparse
    from unittest import mock

    from tools import full_set

    gpu = next(st for st in full_set.STAGES if st.name == "gpu")
    base = {k: v for k, v in os.environ.items() if k != ENV and not k.startswith(("TB_LLM_EVAL", "TB_JUDGE"))}
    for k in ("PYTEST_XDIST_WORKER", "PYTEST_XDIST_WORKER_COUNT", "TB_TEST_PG_DIR", "TB_TEST_DB_URL"):
        base.pop(k, None)
    if key is not None:
        base[ENV] = key
    with mock.patch.dict(os.environ, base, clear=True):
        env = full_set._env(gpu, argparse.Namespace(llm_url=url, llm_model=SERVED, out=str(out)))
    env["PYTHONPATH"] = os.pathsep.join(["libs", "services", "."])
    junit = out / "junit.xml"
    report = ["-rA", "-l", "--tb=long", "-p", "no:xdist", f"--junitxml={junit}", f"--log-file={out / 'pytest.log'}",
              "--log-file-level=DEBUG", "--log-level=DEBUG"]  # fmt: skip
    with (out / "stdout.txt").open("wb") as so, (out / "stderr.txt").open("wb") as se:
        rc = subprocess.run(
            [*gpu.commands[0], *report, *extra], cwd=ROOT, env=env, stdout=so, stderr=se, check=False, timeout=900
        ).returncode
    return rc, list(ET.parse(junit).getroot().iter("testcase"))


def test_gpu_stage_with_the_key_skips_nothing_and_never_shows_it(
    standin: tuple[vs.Standin, str], tmp_path: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    s, url = standin
    rc, cases = _gpu_stage(url, tmp_path, PLANTED)
    skipped = [(c.get("name"), sk.get("message") or "") for c in cases if (sk := c.find("skipped")) is not None]
    assert skipped == [], skipped  # not the missing URL, not the missing key: no skip at all
    names = {c.get("name") for c in cases}
    assert {"test_ir_extract_against_gold", "test_concept_map_200", "test_judge_set_agreement_real_model"} <= names
    stats = s.stats()
    assert stats["counts"].get("200", 0) > 0 and "401" not in stats["counts"], stats
    assert rc in (0, 1)  # the stand-in's answers are not a model's: pass or fail, but run
    # the invariant: the planted key is in nothing the run wrote or printed
    written = [p for p in tmp_path.rglob("*") if p.is_file()]
    assert {"stdout.txt", "stderr.txt", "junit.xml", "pytest.log"} <= {p.name for p in written}
    leaked = [str(p.relative_to(tmp_path)) for p in written if PLANTED.encode() in p.read_bytes()]
    seen = capfd.readouterr()
    assert leaked == [] and PLANTED not in seen.out and PLANTED not in seen.err


def test_gpu_stage_without_the_key_is_refused_by_the_stand_in(standin: tuple[vs.Standin, str], tmp_path: Path) -> None:
    """The contrast: today's client, no key, against a server that wants one: every model call is a 401."""
    s, url = standin
    rc, _ = _gpu_stage(url, tmp_path, None, "-x", "-k", "ir_extract")
    assert rc == 1
    counts = s.stats()["counts"]
    assert counts.get("401", 0) > 0 and "200" not in counts, counts


@NODB
def test_full_set_gpu_stage_passes_the_key_through_and_names_both_endpoints(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import argparse

    from tools import full_set

    monkeypatch.setenv(ENV, PLANTED)
    gpu = next(st for st in full_set.STAGES if st.name == "gpu")
    opts = argparse.Namespace(llm_url="http://127.0.0.1:8000/v1", llm_model=SERVED, out=str(tmp_path))
    env = full_set._env(gpu, opts)
    assert env[ENV] == PLANTED  # from the operator's environment, never on the command line
    assert env["TB_LLM_EVAL_URL"] == env["TB_JUDGE_LLM_URL"] == opts.llm_url
    assert env["TB_LLM_EVAL_MODEL"] == env["TB_JUDGE_MODEL"] == SERVED
    assert all(PLANTED not in a for argv in (*gpu.commands, *gpu.always) for a in argv)


@NODB
def test_the_key_is_a_secret_setting_the_support_bundle_scrubs_and_no_service_holds() -> None:
    from tools import bundle_scrub, support_bundle

    assert ENV in support_bundle.SECRET_SETTINGS
    assert ENV in bundle_scrub.declarations().secret
    overlay = (ROOT / "deploy/docker-compose.secrets.yml").read_text(encoding="utf-8")
    tokens = overlay.split("x-tokens: &tokens", 1)[1].split("\n\n", 1)[0]
    assert f'  {ENV}: ""' in tokens.splitlines()  # cleared in every service that takes the tokens block


@NODB
def test_only_the_gpu_stage_names_the_judge_endpoint(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Review 1460-2: the unit stage runs test_judge_set_agreement_stub (not marked llm), which takes the real
    endpoint whenever TB_JUDGE_LLM_URL is set: no stage but the gpu stage may set it."""
    import argparse

    from tools import full_set

    monkeypatch.delenv("TB_JUDGE_LLM_URL", raising=False)
    monkeypatch.delenv("TB_JUDGE_MODEL", raising=False)
    opts = argparse.Namespace(llm_url="http://localhost:8000/v1", llm_model=SERVED, out=str(tmp_path))
    for st in full_set.STAGES:
        env = full_set._env(st, opts)
        named = "TB_JUDGE_LLM_URL" in env or "TB_JUDGE_MODEL" in env
        assert named is (st.name == "gpu"), st.name


@NODB
def test_only_the_gpu_stage_gets_the_key(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Review 1460-4: the other stages (images, compose, poc, perf, ...) never need the key, so they never hold it."""
    import argparse

    from tools import full_set

    monkeypatch.setenv(ENV, PLANTED)
    opts = argparse.Namespace(llm_url="http://localhost:8000/v1", llm_model=SERVED, out=str(tmp_path))
    for st in full_set.STAGES:
        assert (ENV in full_set._env(st, opts)) is (st.name == "gpu"), st.name


@NODB
@pytest.mark.parametrize(
    "bad",
    [PLANTED + "\r", PLANTED + " ", " " + PLANTED, PLANTED + "\x00", PLANTED + "\t"],
    ids=["cr", "space", "lead", "nul", "tab"],
)
def test_a_malformed_key_is_refused_before_any_call_and_never_shown(standin: tuple[vs.Standin, str], bad: str) -> None:
    """Review 1460-3: the HTTP layer refuses such a header value with an error that quotes it, key and all, and
    LlmClient puts that text in its LlmModelFault: the key must be refused before a request, by a message without it."""
    s, url = standin
    try:
        eval_client(url, SERVED, {ENV: bad}).chat_json("ir_extract", VARIABLES, job_id="H113")
    except ValueError as exc:
        shown = f"{exc!s} {exc!r}"
    except Exception as exc:  # the fault before the fix: report its type only, never its text (it holds the key)
        pytest.fail(f"not refused before the call: {type(exc).__name__}")
    else:
        pytest.fail("not refused")
    assert PLANTED not in shown
    assert s.stats()["counts"] == {}

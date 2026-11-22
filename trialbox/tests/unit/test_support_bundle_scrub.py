"""H-71 (D-1354): the support bundle's scrub, rule by rule, with the near-misses it must leave alone.

Every value here is synthetic and built at run time (``secrets.token_hex``), so no scanner reads a credential in this
file. The planted-corpus test of a whole bundle is ``test_support_bundle_planted.py``."""

from __future__ import annotations

import ast
import json
import re
import secrets
import urllib.parse
from pathlib import Path

import pytest

from tools import bundle_scrub as bs
from tools import support_bundle as sb

ROOT = Path(__file__).resolve().parents[2]


def _v(tag: str = "v") -> str:
    return f"{tag}{secrets.token_hex(10)}"


def _pid() -> str:
    return secrets.token_hex(bs.pid_hex_len() // 2)


# ------------------------------------------------------------------------------------------------ the shapes' sources
def test_the_pseudonym_length_is_the_one_crypto_mints() -> None:
    from tb_common import crypto

    assert bs.pid_hex_len() == crypto.PID_HEX_LEN
    pid = crypto.pid_for_mrn(b"k" * 32, "A0000001")  # a minted pseudonym of a synthetic chart number
    assert bs.scrub_text(f"pid={pid}") == "pid=[pseudonym]"


def _source_regex(path: Path, name: str) -> str:
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
            call = node.value
            assert isinstance(call, ast.Call) and isinstance(call.args[0], ast.Constant)
            return str(call.args[0].value)
    raise AssertionError(f"{name} not in {path}")


def test_every_screening_number_the_console_can_make_is_masked() -> None:
    """``sitestore._number``: ``f"{prefix}{seq:04d}"``, prefix the site's (study_api._PREFIX) or ``<ruleset>-``."""
    src = (ROOT / "services/console/sitestore.py").read_text(encoding="utf-8")
    assert 'prefix = settings.screening_prefix or f"{ruleset}-"' in src and 'no = f"{prefix}{seq:04d}"' in src
    ruleset = re.compile(_source_regex(ROOT / "services/console/app.py", "_RULESET_ID"))
    prefix = re.compile(_source_regex(ROOT / "services/orchestrator/study_api.py", "_PREFIX"))
    for rs in ("RA01", "A", "X_9-Z", "LONGRULESET12345", "ab-c"):
        for seq in (1, 42, 9999, 123456):
            no = f"{rs}-{seq:04d}"
            if ruleset.match(rs):
                assert bs.scrub_text(f"screening no {no} done") == "screening no [screening-no] done", no
            assert bs.scrub_text(f'{{"no": "{no}"}}') == '{"no": "[screening-no]"}', no
    for site in ("SCR-", "tb_", "TBX", "RA2026-"):
        assert prefix.match(site)
        assert bs.scrub_text(f"no={site}0007;") == "no=[screening-no];", site


# ------------------------------------------------------------------------------------------------ patient tokens
@pytest.mark.parametrize(
    "form",
    [
        "{t}", "pid={t}", "pid_{t}", '"{t}"', '{{"pid": "{t}"}}', "/patients/{t}/notes", "0x{t}", "'{t}'",
        "https://box/console/p/{t}?x=1", "{T}", "[{t}]", "pid:{t},", "\\\"{t}\\\"",
    ],
)  # fmt: skip
def test_a_pseudonym_is_masked_in_every_form(form: str) -> None:
    pid = _pid()
    text = form.format(t=pid, T=pid.upper())
    out = bs.scrub_text(text)
    assert pid not in out.lower() and "[pseudonym]" in out


def test_the_short_form_of_a_pseudonym_is_masked() -> None:
    pid = _pid()
    assert bs.scrub_text(f"one pseudonym for two chart numbers ({pid[:8]}…)") == (
        "one pseudonym for two chart numbers ([pseudonym])"
    )


def test_a_bundle_tag_is_stable_in_one_bundle_and_differs_between_bundles() -> None:
    pid, other = _pid(), _pid()
    a, b = bs.Scrubber.for_bundle(), bs.Scrubber.for_bundle()
    one = re.findall(r"\[[^\]]*\]", a.text(f"{pid} {pid.upper()} {other}"))
    assert one[0] == one[1] != one[2]  # one patient, one tag; any case
    assert re.fullmatch(r"\[pseudonym #[bcdfghjkmnpqrstvwxz]{5}\]", one[0])
    pids = [_pid() for _ in range(4)]
    assert [a.text(p) for p in pids] != [b.text(p) for p in pids]  # another bundle, other tags (1 in 19**20 not)
    assert bs.scrub_text(pid) == "[pseudonym]"  # no scrubber: no tag at all


# ------------------------------------------------------------------------------------------------ secrets
def test_query_and_form_secrets_are_replaced() -> None:
    pw, tok, pwd, key = _v("p"), _v("t"), _v("w"), _v("k")
    text = (
        f"GET /login?user=amy&password={pw}&lang=en HTTP/1.1\n"
        f"POST body: username=amy&pwd={pwd}&remember=1\n"
        f"next=%2Flogin%3Faccess_token%3D{tok}%26x%3D1\n"
        f"curl https://api.test/v1?api_key={key}\n"
    )
    out = bs.scrub_text(text)
    for v in (pw, tok, pwd, key):
        assert v not in out
    assert "user=amy" in out and "lang=en" in out and "remember=1" in out and "x%3D1" in out


def test_url_userinfo_is_replaced_plain_and_encoded() -> None:
    pw, user = _v("p"), _v("u")
    out = bs.scrub_text(f"smtp://{user}:{pw}@relay.test:587 and https%3A%2F%2F{user}%3A{pw}%40host.test%2Fx "
                        f"and https://{user}@git.test/r")  # fmt: skip
    assert pw not in out and user not in out
    assert "smtp://[redacted]@relay.test:587" in out and "%3A%2F%2F[redacted]%40host.test" in out


def test_tb_smtp_login_and_every_declared_secret_setting_are_replaced() -> None:
    names = sorted({"TB_SMTP_LOGIN", *bs.declarations().secret, *sb.SECRET_SETTINGS})
    for name in names:
        v = _v()
        for text in (f"{name}={v}", f"  {name}: {v}", f'{{"{name}": "{v}"}}', f"?{name}={v}&a=1", f"export {name}={v}",
                     f"- {name}={v}", f"{{'{name}': '{v}'}}", f'\\"{name}\\": \\"{v}\\"'):  # fmt: skip
            assert v not in bs.scrub_text(text), (name, text)


def test_a_new_secret_setting_is_covered_without_editing_the_scrub(tmp_path: Path) -> None:
    """The names come from the declarations: a setting declared secret tomorrow, whose name says nothing, is
    replaced by the scrub as it is today."""
    src = (ROOT / "libs/tb_common/config.py").read_text(encoding="utf-8")
    added = src.replace(
        "DECLARED: dict[str, Declared] = {",
        'DECLARED: dict[str, Declared] = {\n    "TB_ZEBRA_ORCHID": Declared("str", "", "a new thing (secret)"),',
        1,
    )
    assert added != src
    conf = tmp_path / "config.py"
    conf.write_text(added, encoding="utf-8")
    decl = bs.declarations(conf)
    assert "TB_ZEBRA_ORCHID" in decl.secret
    v = _v().translate(str.maketrans("0123456789", "ghijklmnop"))  # letters: no phone pattern can take part of it
    assert v not in bs.Scrubber(decl=decl).text(f"TB_ZEBRA_ORCHID={v}")
    assert v in bs.scrub_text(f"TB_ZEBRA_ORCHID={v}")  # the name alone says nothing: the declaration covers it


def test_the_parsed_declarations_are_the_imported_ones() -> None:
    from tb_common import config

    marked = {n for n, d in config.DECLARED.items() if bs.SECRET_MARK.search(d.doc)}
    assert bs.declarations().secret == frozenset(marked) and marked
    assert set(bs.declarations().names) >= set(config.DECLARED)
    assert "TB_REDCAP_TOKEN_" in bs.declarations().families and "TB_DB_PW_" in bs.declarations().families


def test_a_missing_declaration_file_refuses_rather_than_scrubbing_with_fewer(tmp_path: Path) -> None:
    with pytest.raises(bs.ScrubError):
        bs.declarations(tmp_path / "nothing.py")


def test_headers_bearer_and_cookies_are_replaced() -> None:
    tok, sid, b64 = _v("t"), _v("s"), _v("b")
    text = (
        f"> Authorization: Bearer {tok}\n"
        f"request headers={{'Cookie': 'sessionid={sid}; theme=dark', 'Accept': 'text/html'}}\n"
        f"  Cookie: sessionid={sid}; csrftoken={tok}\n"
        f"Proxy-Authorization: Basic {b64}\n"
        f"x-api-key: {tok}\n"
        f"curl -H 'Authorization: token {tok}' https://x.test\n"
    )
    out = bs.scrub_text(text)
    for v in (tok, sid, b64):
        assert v not in out
    assert "'Accept': 'text/html'" in out


def test_pem_blocks_go_whole_and_a_cut_block_to_the_end() -> None:
    body = secrets.token_hex(40)
    begin, end = "-----BEGIN " + "CERTIFICATE-----", "-----END " + "CERTIFICATE-----"
    out = bs.scrub_text(f"a\n{begin}\n{body}\n{end}\nb\n")
    assert out == "a\n[pem block removed]\nb\n"
    cut = bs.scrub_text(f'{{"key": "{begin}\\n{body}"}}')
    assert body not in cut


def test_multi_line_and_block_values_are_replaced() -> None:
    a, b, c = _v("a"), _v("b"), _v("c")
    text = f'TB_SMTP_LOGIN="{a}\n{b}"\nTB_TZ=Asia/Taipei\nsecrets:\n  password: |\n    {c}\n    {a}\n  user: amy\n'
    out = bs.scrub_text(text)
    for v in (a, b, c):
        assert v not in out
    assert "TB_TZ=Asia/Taipei" in out and "  user: amy" in out


def test_json_stays_json() -> None:
    pid, pw = _pid(), _v()
    doc = {"pid": pid, "password": pw, "secrets_hidden": 3, "bytes": 31415926, "nested": {"api_key": 12345678}}
    s = bs.Scrubber(mrn=re.compile(r"(?<![0-9A-Za-z])\d{8}(?![0-9A-Za-z])"))
    out = s.content("x.json", json.dumps(doc))
    back = json.loads(out)
    assert back["pid"] == "[pseudonym]" and back["password"] == "[redacted]" and back["secrets_hidden"] == 3
    assert back["bytes"] == "[MRN]" and back["nested"]["api_key"] == "[redacted]"
    lines = s.content("x.jsonl", json.dumps({"detail": pid}) + "\n" + json.dumps({"ok": True}) + "\n")
    assert [json.loads(x) for x in lines.splitlines()] == [{"detail": "[pseudonym]"}, {"ok": True}]


def test_the_scrub_settles_and_the_writer_check_holds() -> None:
    s = bs.Scrubber.for_bundle()
    text = f"pid={_pid()} password={_v()} smtp://u:{_v()}@h Authorization: Bearer {_v()} RA01-0042\n"
    once = s.text(text)
    assert s.text(once) == once and s.is_clean("logs/x.log", once) and not s.is_clean("logs/x.log", text)


# ------------------------------------------------------------------------------------------------ near-misses
#: what the scrub must leave alone, and why (the page lists these)
NEAR_MISSES = [
    "sha256 " + "ab12" * 16,  # a 64-digit hash: not a pseudonym (no 32-digit run with no hex digit beside it)
    "commit 4b825dc642cb6eb9a060e54bf8d69288fbee4904",  # a 40-digit commit
    "id " + "a" * 31 + " and " + "b" * 33,  # 31 and 33 hex digits
    "request 550e8400-e29b-41d4-a716-446655440000",  # a UUID with its dashes
    "2026-11-22T10:00:00Z console | GET /healthz 200 in 12ms",  # a timestamp, a status, a duration
    "snapshot 2026-10-04 and 2026-11-22T01:02:03",  # ISO dates
    "/trialbox-console-1 restarts=2 status=running",  # a container, a count
    '{"ok": true, "mem_limit": "512m", "authserv": "mx.hospa.test", "gpu": "rtxpro6000"}',  # the review's JSON
    "job 01JITCOMPILE00000000000000",  # a ULID
    "OPS-047 and T-209b and R-61",  # ids of fewer than four digits
    "TB_METRICS_TOKEN_FILE=/run/secrets/metrics.token",  # where a secret is, not the secret
    "TB_GPU_KEY=rtxpro6000",  # a profile's name (NOT_SECRETS)
    '"key": "lake.snapshot", "monkey": "x", "keyboard": "us"',  # "key" alone is not a secret's word
    "token expired; bypass=1; passed=12; compass=north",  # words that only contain a secret's word
    '"secrets_hidden": 3, "credentials_removed": 2',  # counts next to a secret's name
    "TB_CONSOLE_SECURE_COOKIE=true",  # a flag
    "postgres:16 on port 5432, 0.0.0.0:8443->443/tcp",  # versions and ports
    "iso-8859-1 and utf-8",  # encodings
]


@pytest.mark.parametrize("text", NEAR_MISSES)
def test_a_near_miss_is_left_alone(text: str) -> None:
    assert bs.scrub_text(text) == text


def test_what_is_masked_on_purpose_though_it_may_not_be_a_token() -> None:
    """Over-masks the page owns up to: a decision number of four digits, a 32-digit trace id, an uppercase word
    straight before four digits. A bundle loses them; it never keeps a token that looks like them."""
    assert bs.scrub_text("D-1354") == "[screening-no]"
    assert bs.scrub_text("trace " + "0af7651916cd43dd8448eb211c80319c") == "trace [pseudonym]"
    assert bs.scrub_text("RFC3339") == "[screening-no]"
    assert bs.scrub_text("born 22-11-2026") == "born [screening-no]"  # a day-month-year date goes too


# ------------------------------------------------------------------------------------------------ history, text
def test_the_update_history_keeps_an_errors_type_and_length_only() -> None:
    pid, pw = _pid(), _v()
    detail = f"CalledProcessError: restore of {pid} failed with password={pw}"
    line = json.dumps({"at": "2026-11-20T09:00:00Z", "bundle": "1.4.2", "step": "restore", "ok": False,
                       "detail": detail, "extra": {"x": pid}})  # fmt: skip
    out = bs.history_text(line + "\nnot json " + pid + "\n")
    rows = [json.loads(x) for x in out.splitlines()]
    assert rows[0]["detail"] == {"type": "CalledProcessError", "length": len(detail)}
    assert rows[0]["extra"] == {"type": "text", "length": len(str({"x": pid}))}
    assert rows[0]["step"] == "restore" and rows[0]["ok"] is False
    assert rows[1] == {"unreadable_line": {"type": "text", "length": len("not json " + pid)}}
    assert pid not in out and pw not in out


def test_only_text_the_scrub_can_read_is_text() -> None:
    assert bs.as_text("plain\tline\x1b[0m\n") is not None
    assert bs.as_text("pid".encode("utf-16")) is None  # UTF-16: the rules would read nothing
    assert bs.as_text(b"a\x00b") is None and bs.as_text(b"\xff\xfe") is None
    assert bs.as_text("é".encode()[:1], cut=True) == ""  # a character cut at the read limit is dropped
    assert bs.as_text("é".encode()[:1]) is None  # review L3: only when the caller cut the bytes
    assert bs.as_text(urllib.parse.quote("x").encode()) == "x"

"""DEMO-FETCH (D-632): a build's pinned download is tried three times. On train 7 Maven Central answered 404 once
for the translator's quick jar and the demo image's build, which asked once, cost a full CI run."""

from __future__ import annotations

import hashlib
import io
import urllib.error
from pathlib import Path
from typing import Any

import pytest

from tools import fetch_fonts, fetch_pinned

ROOT = Path(__file__).resolve().parents[2]
URL = "https://repo.example.org/quick-5.4.0.jar"
DATA = b"the jar's bytes"
SHA = hashlib.sha256(DATA).hexdigest()

pytestmark = pytest.mark.nodb


class Net:
    """The network: each answer in turn (bytes, or an exception to raise); counts the asks and the waits."""

    def __init__(self, *answers: Any) -> None:
        self.answers = list(answers)
        self.asked = 0
        self.waits: list[float] = []

    def get(self, url: str) -> bytes:
        self.asked += 1
        a = self.answers.pop(0)
        if isinstance(a, BaseException):
            raise a
        return a  # type: ignore[no-any-return]


def _404() -> urllib.error.HTTPError:
    return urllib.error.HTTPError(URL, 404, "Not Found", {}, io.BytesIO(b""))  # type: ignore[arg-type]


def test_one_bad_answer_from_the_mirror_is_asked_again(tmp_path: Path) -> None:
    net = Net(_404(), DATA)
    out = tmp_path / "quick.jar"
    fetch_pinned.fetch(URL, out, SHA, get=net.get, sleep=net.waits.append)
    assert out.read_bytes() == DATA and net.asked == 2 and net.waits == [2]


@pytest.mark.parametrize(
    "fault", [_404(), urllib.error.URLError("refused"), TimeoutError("timed out"), ConnectionResetError()]
)
def test_three_failures_in_a_row_stop_the_build_with_each_reason(tmp_path: Path, fault: BaseException) -> None:
    net = Net(fault, fault, fault, DATA)
    out = tmp_path / "quick.jar"
    with pytest.raises(fetch_pinned.FetchError) as exc:
        fetch_pinned.fetch(URL, out, SHA, get=net.get, sleep=net.waits.append)
    assert net.asked == 3 and net.waits == [2, 5]  # bounded: never a fourth ask
    assert "3 tries" in str(exc.value) and URL in str(exc.value)
    assert not out.exists() and list(tmp_path.iterdir()) == []


def test_a_file_that_is_not_the_pinned_one_is_refused_at_once_and_never_written(tmp_path: Path) -> None:
    net = Net(b"something else", DATA)
    out = tmp_path / "quick.jar"
    with pytest.raises(fetch_pinned.PinError, match="sha256"):
        fetch_pinned.fetch(URL, out, SHA, get=net.get, sleep=net.waits.append)
    assert net.asked == 1 and net.waits == [] and list(tmp_path.iterdir()) == []


def test_the_command_says_what_failed_and_returns_1(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert fetch_pinned.main(["https://127.0.0.1:9/x.jar", str(tmp_path / "x.jar"), "0" * 64, "--wait", "0"]) == 1
    err = capsys.readouterr().err
    assert "3 tries" in err and "x.jar" in err
    assert fetch_pinned.main([URL, str(tmp_path / "x.jar"), "not-a-sha"]) == 2


def test_the_fonts_are_fetched_the_same_way(monkeypatch: pytest.MonkeyPatch) -> None:
    url, want = next(iter(fetch_fonts.SHA256.items()))
    seen: list[str] = []

    def fake(u: str, sha: str, **_kw: Any) -> bytes:
        seen.append(f"{u} {sha}")
        return b"font"

    monkeypatch.setattr(fetch_pinned, "fetch_bytes", fake)
    assert fetch_fonts._get(url) == b"font" and seen == [f"{url} {want}"]
    with pytest.raises(fetch_fonts.PinError):
        fetch_fonts._get("https://repo.example.org/not-pinned.ttf")
    assert seen == [f"{url} {want}"]  # an unpinned URL is never asked for


def test_the_demo_image_fetches_its_jar_with_the_tool() -> None:
    text = (ROOT / "demo" / "Dockerfile").read_text(encoding="utf-8")
    assert "python tools/fetch_pinned.py" in text and '"$CQL_QUICK_SHA256"' in text
    assert "urlopen" not in text  # no second, single-try fetch left in the build
    ignore = (ROOT / ".dockerignore").read_text(encoding="utf-8")
    assert "tools/fetch_pinned.py" not in ignore


@pytest.mark.parametrize(
    "url", ["file:///etc/hostname", "http://repo.example.org/x.jar", "ftp://repo.example.org/x.jar"]
)
def test_only_https_is_ever_asked_for(tmp_path: Path, url: str) -> None:
    """The static scan's point about opening a URL: a file: or plain http address is refused, not fetched."""
    net = Net(DATA)
    with pytest.raises(fetch_pinned.FetchError, match="https"):
        fetch_pinned.fetch(url, tmp_path / "x", SHA, get=net.get, sleep=net.waits.append)
    assert net.asked == 0
    with pytest.raises(fetch_pinned.FetchError, match="https"):
        fetch_pinned._get(url)


def test_the_scan_has_no_entry_left_for_a_fetch_that_moved() -> None:
    ignores = (ROOT / "tools" / "security_scan_ignores.yaml").read_text(encoding="utf-8")
    assert "tools/fetch_fonts.py" not in ignores and "tools/fetch_pinned.py" not in ignores

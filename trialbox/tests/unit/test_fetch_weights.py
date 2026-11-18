"""tools/fetch_weights.py (W-1) against a local fake hub serving tiny synthetic files; no model is downloaded."""

from __future__ import annotations

import errno
import fcntl
import hashlib
import http.server
import io
import json
import os
import threading
import urllib.parse
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
import yaml

from tools import fetch_weights as fw
from tools.pin_model import manifest_sha256_of_files, weight_manifest

ROOT = Path(__file__).resolve().parents[2]
JUDGE, VERIFIER = "gemma-4-26b-a4b-it-rtxpro6000", "qwen3.5-9b-rtxpro6000"  # the profile's builds (PROFILE_PAIRS)
JUDGE_DIR, VERIFIER_DIR = "gemma-4-26b-a4b-it-4bit", "qwen3.5-9b-4bit"
TEMPLATE = "chat-templates/judge/chat_template.jinja"
REV_J, REV_V, REV_T = "a" * 40, "b" * 40, "c" * 40
TOKEN = "hf_synthetic0token"  # a synthetic value


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


# synthetic repositories: what the fake hub serves at each (repository, revision, path)
REPOS: dict[str, dict[str, bytes]] = {
    f"synth/judge@{REV_J}": {
        ".gitattributes": b"*.safetensors filter=lfs\n",
        "config.json": b'{"architectures": ["Synthetic"]}\n',
        "model-00001-of-00002.safetensors": bytes(range(256)) * 300,  # 76,800 bytes: several reads
        "model-00002-of-00002.safetensors": b"\x01" * 5000,
        "tokenizer.json": b'{"synthetic": true}\n',
        "modeling_extra.py": b"print('never fetched')\n",  # on the hub, not in the pin: never asked for
    },
    f"synth/verifier@{REV_V}": {
        "LICENSE": b"synthetic licence text\n",
        "config.json": b'{"architectures": ["Synthetic2"]}\n',
        "model.safetensors": b"\x02" * 3000,
    },
    f"synth/base@{REV_T}": {"chat_template.jinja": b"{{ messages }}\n"},
}


def _files(repo: str) -> list[dict[str, Any]]:
    return [
        {"path": p, "bytes": len(b), "sha256": _sha(b)} for p, b in sorted(REPOS[repo].items()) if not p.endswith(".py")
    ]


class Hub:
    """A local HTTP server with range support. ``cut`` makes the first ask for a path stop after N bytes,
    ``redirect`` answers a path with a 302, ``on_get`` is called on each ask; every ask is recorded with its Range
    and Authorization headers."""

    def __init__(self) -> None:
        self.content = {k: dict(v) for k, v in REPOS.items()}
        self.cut: dict[str, int] = {}
        self.redirect: dict[str, str] = {}
        self.on_get: Callable[[str], None] | None = None
        self.asks: list[tuple[str, str | None]] = []
        self.auth: list[str | None] = []
        hub = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a: Any) -> None:
                pass

            def do_GET(self) -> None:
                parts = urllib.parse.unquote(self.path).lstrip("/").split("/")
                hub.auth.append(self.headers.get("Authorization"))
                if self.path.lstrip("/").startswith("any/"):  # a plain file server (the "content store")
                    hub.asks.append((self.path, self.headers.get("Range")))
                    body = b"stored"
                    self.send_response(200)
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                # /<owner>/<name>/resolve/<revision>/<path>
                repo, rev, rel = "/".join(parts[:2]), parts[3], "/".join(parts[4:])
                hub.asks.append((rel, self.headers.get("Range")))
                if hub.on_get:
                    hub.on_get(rel)
                if rel in hub.redirect:
                    self.send_response(302)
                    self.send_header("Location", hub.redirect[rel])
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                found = hub.content.get(f"{repo}@{rev}", {}).get(rel)
                if found is None:
                    self.send_response(404)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                body = found
                start = 0
                rng = self.headers.get("Range")
                if rng:
                    start = int(rng.split("=")[1].split("-")[0])
                    if start >= len(body):
                        self.send_response(416)
                        self.send_header("Content-Length", "0")
                        self.end_headers()
                        return
                    self.send_response(206)
                    self.send_header("Content-Range", f"bytes {start}-{len(body) - 1}/{len(body)}")
                else:
                    self.send_response(200)
                self.send_header("Content-Length", str(len(body) - start))
                self.end_headers()
                cut = hub.cut.pop(rel, None)
                self.wfile.write(body[start:cut] if cut is not None else body[start:])
                if cut is not None:
                    self.close_connection = True

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        self.url = f"http://127.0.0.1:{self.port}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


class LoopbackTransport(fw.Transport):
    """The real transport, allowed plain http to the loopback fake servers only (the tool itself is https only)."""

    @classmethod
    def url_ok(cls, url: str) -> bool:
        u = urllib.parse.urlsplit(url)
        return u.scheme == "https" or (u.scheme == "http" and u.hostname == "127.0.0.1")


def strict_loopback(port: int) -> type[fw.Transport]:
    """Plain http allowed to one loopback port only: any other address is 'not https'."""

    class Strict(fw.Transport):
        @classmethod
        def url_ok(cls, url: str) -> bool:
            u = urllib.parse.urlsplit(url)
            return u.scheme == "https" or (u.scheme == "http" and u.hostname == "127.0.0.1" and u.port == port)

    return Strict


@pytest.fixture
def hub() -> Iterator[Hub]:
    h = Hub()
    yield h
    h.close()


@pytest.fixture
def store() -> Iterator[Hub]:
    """A second server on another port (a content store, or a host that must not get the token)."""
    h = Hub()
    yield h
    h.close()


@pytest.fixture
def record(tmp_path: Path) -> Path:
    """A synthetic checkout: registry, measured record, licence register."""
    root = tmp_path / "checkout"
    (root / "models").mkdir(parents=True)
    (root / "deploy" / "measured").mkdir(parents=True)
    (root / "docs").mkdir()
    rec = {
        "servers": [
            {
                "model": "synth/judge",
                "model_dir": f"/m/snapshots/{REV_J}",
                "model_files": _files(f"synth/judge@{REV_J}"),
            },
            {
                "model": "synth/verifier",
                "model_dir": f"/m/snapshots/{REV_V}",
                "model_files": _files(f"synth/verifier@{REV_V}"),
            },
        ]
    }
    (root / "deploy" / "measured" / "rec.json").write_text(json.dumps(rec), encoding="utf-8")
    tpl = REPOS[f"synth/base@{REV_T}"]["chat_template.jinja"]
    builds = [
        {
            "build_id": JUDGE,
            "repository": "synth/judge",
            "expected": {
                "manifest_sha256": manifest_sha256_of_files(_files(f"synth/judge@{REV_J}")),
                "revision": REV_J,
                "source": "deploy/measured/rec.json",
            },
            "provenance": {"source": "synth/judge", "revision": REV_J},
            "chat_template": {"source": "synth/base", "revision": REV_T, "file": TEMPLATE, "sha256": _sha(tpl)},
            "licence": {"name": "Synthetic-1.0", "spdx": "MIT", "verified": True, "register": "model-synth-j"},
        },
        {
            "build_id": VERIFIER,
            "repository": "synth/verifier",
            "expected": {
                "manifest_sha256": manifest_sha256_of_files(_files(f"synth/verifier@{REV_V}")),
                "revision": REV_V,
                "source": "deploy/measured/rec.json",
            },
            "licence": {"name": "Synthetic-2.0", "spdx": "MIT", "verified": True, "register": "model-synth-v"},
        },
    ]
    (root / "models" / "registry.yaml").write_text(yaml.safe_dump({"builds": builds}), encoding="utf-8")
    (root / "docs" / "register.csv").write_text(
        "id,licence,spdx,status,obligation,evidence\n"
        "model-synth-j,Synthetic Licence 1,MIT,cleared,keep the notice,synthetic\n"
        "model-synth-v,Synthetic Licence 2,MIT,cleared,keep the licence file,synthetic\n",
        encoding="utf-8",
    )
    return root


def _run(record: Path, hub: Hub | None, models: Path | None, **kw: Any) -> int:
    env = {"HF_ENDPOINT": hub.url} if hub else {}
    env.update(kw.pop("env", {}))
    kw.setdefault("free_bytes", lambda _p: 1 << 40)
    kw.setdefault("transport_cls", LoopbackTransport)
    kw.setdefault("sleep", lambda _s: None)
    return fw.run(
        "rtxpro6000",
        models,
        env=env,
        registry=record / "models" / "registry.yaml",
        register=record / "docs" / "register.csv",
        root=record,
        **kw,
    )


def _assert_pinned(models: Path, record: Path, judge: str = JUDGE_DIR, verifier: str = VERIFIER_DIR) -> None:
    doc = yaml.safe_load((record / "models" / "registry.yaml").read_text(encoding="utf-8"))
    rows = {b["build_id"]: b for b in doc["builds"]}
    # the pin's own manifest (tools/pin_model.py) of each folder is the registry's expected one
    assert weight_manifest(models / judge).sha256 == rows[JUDGE]["expected"]["manifest_sha256"]
    assert weight_manifest(models / verifier).sha256 == rows[VERIFIER]["expected"]["manifest_sha256"]
    assert _sha((models / TEMPLATE).read_bytes()) == rows[JUDGE]["chat_template"]["sha256"]


def _stage_left(models: Path) -> list[str]:
    st = models / fw.STAGE
    return sorted(p.relative_to(st).as_posix() for p in st.rglob("*")) if st.exists() else []


# ------------------------------------------------------------------------------------------- the card's cases


def test_happy_path(record: Path, hub: Hub, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    models = tmp_path / "models"
    assert _run(record, hub, models) == 0
    _assert_pinned(models, record)
    assert _stage_left(models) == [fw.LOCK]  # nothing staged is left; the lock file stays
    assert not (models / JUDGE_DIR / ".gitattributes").exists()  # hidden: outside the manifest, not fetched
    asked = {p for p, _ in hub.asks}
    assert "modeling_extra.py" not in asked and ".gitattributes" not in asked
    out = capsys.readouterr().out
    assert out.startswith(f"fetch-weights: models root {models}")
    assert "Synthetic Licence 1" in out and "keep the licence file" in out
    assert "Next step" in out and "deploy/poc.sh" in out


def test_second_run_finds_everything_present(record: Path, hub: Hub, tmp_path: Path) -> None:
    models = tmp_path / "models"
    assert _run(record, hub, models) == 0
    hub.asks.clear()
    assert _run(record, hub, models) == 0
    assert hub.asks == []  # nothing asked for again
    assert _run(record, None, models, verify_only=True) == 0


def test_wrong_hash_is_refused_and_nothing_moved(record: Path, hub: Hub, tmp_path: Path) -> None:
    hub.content[f"synth/verifier@{REV_V}"]["model.safetensors"] = b"\x03" * 3000  # same size, other bytes
    models = tmp_path / "models"
    assert _run(record, hub, models) == 1
    assert not (models / VERIFIER_DIR).exists()
    assert not list((models / fw.STAGE).rglob("model.safetensors"))  # the refused file is deleted


def test_missing_file_on_hub_fails_without_a_partial_folder(record: Path, hub: Hub, tmp_path: Path) -> None:
    del hub.content[f"synth/judge@{REV_J}"]["tokenizer.json"]
    models = tmp_path / "models"
    assert _run(record, hub, models) == 1
    assert not (models / JUDGE_DIR).exists()


def test_interrupted_download_resumes(record: Path, hub: Hub, tmp_path: Path) -> None:
    hub.cut["model-00001-of-00002.safetensors"] = 10_000  # the first ask stops after 10,000 bytes
    models = tmp_path / "models"
    assert _run(record, hub, models) == 0
    asks = [r for p, r in hub.asks if p == "model-00001-of-00002.safetensors"]
    assert asks == [None, "bytes=10000-"]  # the second ask resumed where the first stopped
    _assert_pinned(models, record)


def test_resume_across_runs(record: Path, hub: Hub, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    models = tmp_path / "models"
    monkeypatch.setattr(fw, "WAITS", ())  # no second ask in this run: it fails with the part kept
    hub.cut["model-00001-of-00002.safetensors"] = 4_096
    assert _run(record, hub, models) == 1
    assert not (models / JUDGE_DIR).exists()
    part = models / fw.STAGE / JUDGE_DIR / fw.PARTS / "model-00001-of-00002.safetensors"
    assert part.stat().st_size == 4_096
    hub.asks.clear()
    assert _run(record, hub, models) == 0
    assert ("model-00001-of-00002.safetensors", "bytes=4096-") in hub.asks
    _assert_pinned(models, record)


@pytest.mark.parametrize("stray", ["modeling_custom.py", "sub/extra.json"])
def test_unexpected_extra_file_in_staging_is_refused_then_cleaned(
    record: Path, hub: Hub, tmp_path: Path, stray: str
) -> None:
    models = tmp_path / "models"
    p = models / fw.STAGE / VERIFIER_DIR / stray
    p.parent.mkdir(parents=True)
    p.write_text("x\n", encoding="utf-8")
    assert _run(record, hub, models) == 1
    assert not (models / VERIFIER_DIR).exists()
    assert not (models / fw.STAGE / VERIFIER_DIR).exists()  # removed: the next run starts it clean
    assert _run(record, hub, models) == 0
    _assert_pinned(models, record)


def test_folder_in_the_way_with_an_extra_file_is_left_alone(record: Path, hub: Hub, tmp_path: Path) -> None:
    models = tmp_path / "models"
    assert _run(record, hub, models) == 0
    extra = models / JUDGE_DIR / "pytorch_model.bin"
    extra.write_bytes(b"pickle")
    assert _run(record, None, models, verify_only=True) == 1
    hub.asks.clear()
    assert _run(record, hub, models) == 1  # refused, and the folder is not touched
    assert extra.exists() and hub.asks == []


def test_insufficient_disk(record: Path, hub: Hub, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    models = tmp_path / "models"
    assert _run(record, hub, models, free_bytes=lambda _p: 10_000) == 1
    assert hub.asks == []
    assert "not enough free disk" in capsys.readouterr().err


def test_dry_run_sends_and_writes_nothing(record: Path, hub: Hub, tmp_path: Path) -> None:
    models = tmp_path / "models"
    assert _run(record, hub, models, dry_run=True) == 0
    assert hub.asks == [] and not models.exists()


def test_verify_only_on_an_empty_folder(record: Path, tmp_path: Path) -> None:
    assert _run(record, None, tmp_path / "models", verify_only=True) == 1


def test_plain_http_is_refused_by_the_real_transport(record: Path, hub: Hub, tmp_path: Path) -> None:
    assert _run(record, hub, tmp_path / "models", transport_cls=fw.Transport) == 2
    assert hub.asks == []


def test_the_repository_pin_record_gives_a_verified_plan() -> None:
    """The committed registry and measured record: every profile file list matches its expected manifest (offline)."""
    targets = fw.plan("rtxpro6000", fw.resolve_env("rtxpro6000", {}))
    assert sorted(t.kind for t in targets) == ["folder", "folder", "template"]
    assert {t.dest for t in targets} == {
        "gemma-4-26b-a4b-it-4bit",
        "qwen3.5-9b-4bit",
        "chat-templates/gemma-4-26b-a4b-it/chat_template.jinja",
    }
    for t in targets:
        assert t.revision and len(t.revision) == 40
        assert all(len(f.sha256) == 64 for f in t.files)
        assert not any(Path(f.path).suffix in (".bin", ".py") for f in t.files)
        assert t.licence["status"] == "cleared"


def test_install_and_start_never_fetch_weights() -> None:
    for script in ("deploy/poc.sh", "deploy/install.sh", "deploy/box-install.sh", "deploy/bootstrap.sh"):
        assert "fetch_weights" not in (ROOT / script).read_text(encoding="utf-8"), script


# ------------------------------------------------------------------------------------------- review 1: one run


def test_a_second_run_stops_while_one_holds_the_lock(
    record: Path, hub: Hub, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    models = tmp_path / "models"
    lock = models / fw.STAGE / fw.LOCK
    lock.parent.mkdir(parents=True)
    fd = os.open(lock, os.O_RDWR | os.O_CREAT)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)  # another run
        assert _run(record, hub, models) == 1
        assert "another fetch-weights run" in capsys.readouterr().err
        assert hub.asks == [] and not (models / JUDGE_DIR).exists()
    finally:
        os.close(fd)
    assert _run(record, hub, models) == 0


def test_the_lock_is_held_for_the_whole_download(record: Path, hub: Hub, tmp_path: Path) -> None:
    models = tmp_path / "models"
    held: list[bool] = []

    def try_lock(_rel: str) -> None:
        fd = os.open(models / fw.STAGE / fw.LOCK, os.O_RDWR)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            held.append(False)
        except BlockingIOError:
            held.append(True)
        finally:
            os.close(fd)

    hub.on_get = try_lock
    assert _run(record, hub, models) == 0
    assert held and all(held)


# ------------------------------------------------------------------------------------------- review 2-4: the token


def test_token_goes_to_the_hub_origin_only_not_another_port(hub: Hub, store: Hub) -> None:
    """Same host, another port (review 2): the redirect target does not get the token."""
    hub.redirect["LICENSE"] = f"{store.url}/any/LICENSE"
    t = LoopbackTransport(token=TOKEN, token_origin=fw.origin(hub.url))
    _status, _total, stream = t.open(fw.url_of(hub.url, "synth/verifier", REV_V, "LICENSE"))
    assert stream.read() == b"stored"
    assert hub.auth == [f"Bearer {TOKEN}"]
    assert store.auth == [None]


def test_token_is_not_sent_to_another_origin_at_first_ask(hub: Hub) -> None:
    t = LoopbackTransport(token=TOKEN, token_origin=("http", "127.0.0.1", hub.port + 1))
    t.open(fw.url_of(hub.url, "synth/verifier", REV_V, "LICENSE"))[2].read()
    assert hub.auth == [None]


@pytest.mark.parametrize("raw", [f"{TOKEN}\n", f"  {TOKEN}\t"])
def test_token_is_stripped(raw: str) -> None:
    assert fw.token_for({"HF_TOKEN": raw}, fw.HUB) == TOKEN


@pytest.mark.parametrize("raw", [f"{TOKEN[:5]} {TOKEN[5:]}", f"{TOKEN}\n{TOKEN}", f"{TOKEN}\x00"])
def test_a_bad_token_is_refused_without_being_shown(
    record: Path, hub: Hub, tmp_path: Path, capsys: pytest.CaptureFixture[str], raw: str
) -> None:
    assert _run(record, hub, tmp_path / "models", env={"HF_TOKEN": raw}) == 2
    out = capsys.readouterr()
    assert "HF_TOKEN" in out.err
    for piece in (TOKEN, TOKEN[:5], TOKEN[5:]):
        assert piece not in out.out + out.err
    assert hub.asks == []


def test_main_never_prints_the_token(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    def boom(*_a: Any, **_k: Any) -> int:
        raise ValueError(f"Invalid header value b'Bearer {TOKEN}'")

    monkeypatch.setenv("HF_TOKEN", TOKEN)
    monkeypatch.setattr(fw, "run", boom)
    assert fw.main(["--profile", "rtxpro6000"]) == 1
    out = capsys.readouterr()
    assert TOKEN not in out.out + out.err and "<HF_TOKEN>" in out.err


def test_a_mirror_never_gets_the_token(
    record: Path, hub: Hub, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert fw.token_for({"HF_TOKEN": TOKEN}, fw.HUB) == TOKEN
    assert fw.token_for({"HF_TOKEN": TOKEN}, "https://mirror.invalid") is None
    assert _run(record, hub, tmp_path / "models", env={"HF_TOKEN": TOKEN}) == 0
    assert hub.auth and all(a is None for a in hub.auth)
    assert "not sent" in capsys.readouterr().out


# ------------------------------------------------------------------------------------------- review 5-6: where


@pytest.mark.parametrize(
    ("var", "value"),
    [
        ("JUDGE_CHAT_TEMPLATE", "../outside.jinja"),
        ("JUDGE_CHAT_TEMPLATE", "/tmp/abs.jinja"),
        ("JUDGE_CHAT_TEMPLATE", f"{JUDGE_DIR}/chat_template.jinja"),  # inside the judge's folder
        ("JUDGE_CHAT_TEMPLATE", ".hidden/t.jinja"),
        ("JUDGE_MODEL_DIR", "../judge"),
        ("JUDGE_MODEL_DIR", "/abs/judge"),
        ("VERIFIER_MODEL_DIR", f"{JUDGE_DIR}/inner"),
    ],
)
def test_destinations_outside_the_root_or_inside_a_folder_are_refused(
    record: Path, hub: Hub, tmp_path: Path, var: str, value: str
) -> None:
    models = tmp_path / "models"
    assert _run(record, hub, models, env={var: value}) == 2
    assert hub.asks == [] and not models.exists()
    assert not (tmp_path / "outside.jinja").exists()


def test_folders_resolve_as_the_start_does(record: Path, hub: Hub, capsys: pytest.CaptureFixture[str]) -> None:
    """TB_MODELS_DIR and JUDGE_MODEL_DIR from deploy/.env, VERIFIER_MODEL_DIR from the profile's compose file."""
    (record / "deploy" / ".env").write_text(
        "# kept by poc.sh\nTB_MODELS_DIR=./kept-models\nJUDGE_MODEL_DIR='judge-from-env-file'\n", encoding="utf-8"
    )
    (record / "deploy" / "docker-compose.rtxpro6000.yml").write_text(
        "services:\n  v:\n    command: [--model=/models/${VERIFIER_MODEL_DIR:-verifier-from-compose}]\n",
        encoding="utf-8",
    )
    assert _run(record, hub, None) == 0
    models = record / "deploy" / "kept-models"
    _assert_pinned(models, record, judge="judge-from-env-file", verifier="verifier-from-compose")
    assert capsys.readouterr().out.startswith(f"fetch-weights: models root {models} (from TB_MODELS_DIR (deploy/.env))")


def test_the_environment_wins_over_deploy_env(record: Path, tmp_path: Path) -> None:
    (record / "deploy" / ".env").write_text("TB_MODELS_DIR=./kept\nJUDGE_MODEL_DIR=from-file\n", encoding="utf-8")
    env = {"TB_MODELS_DIR": "elsewhere", "JUDGE_MODEL_DIR": "from-env"}
    assert fw.models_root(env, record)[0] == record / "elsewhere"
    assert fw.models_root({}, record)[0] == record / "deploy" / "kept"
    assert fw.models_root({"TB_MODELS_DIR": str(tmp_path / "abs")}, record)[0] == tmp_path / "abs"
    assert fw.resolve_env("rtxpro6000", env, record)["JUDGE_MODEL_DIR"] == "from-env"


# ------------------------------------------------------------------------------------------- review 7: errors


def test_a_failed_rename_is_said_plainly(
    record: Path, hub: Hub, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def deny(*_a: Any, **_k: Any) -> None:
        raise PermissionError(errno.EACCES, "Permission denied")

    monkeypatch.setattr(os, "rename", deny)
    assert _run(record, hub, tmp_path / "models") == 1
    assert "no permission" in capsys.readouterr().err


def test_an_empty_folder_appearing_mid_run_is_not_replaced(record: Path, hub: Hub, tmp_path: Path) -> None:
    models = tmp_path / "models"

    def appear(rel: str) -> None:
        if rel == "LICENSE":
            (models / VERIFIER_DIR).mkdir(exist_ok=True)

    hub.on_get = appear
    assert _run(record, hub, models) == 1
    assert (models / VERIFIER_DIR).is_dir() and not any((models / VERIFIER_DIR).iterdir())


def test_a_template_appearing_mid_run_is_not_replaced(record: Path, hub: Hub, tmp_path: Path) -> None:
    models = tmp_path / "models"

    def appear(rel: str) -> None:
        if rel == "chat_template.jinja":
            (models / TEMPLATE).parent.mkdir(parents=True, exist_ok=True)
            (models / TEMPLATE).write_text("mine\n", encoding="utf-8")

    hub.on_get = appear
    assert _run(record, hub, models) == 1
    assert (models / TEMPLATE).read_text(encoding="utf-8") == "mine\n"


def test_a_full_disk_is_said_and_not_retried(
    record: Path, hub: Hub, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    class Full(io.BytesIO):
        def write(self, _b: Any) -> int:
            raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(fw, "_open_part", lambda _p, _a: Full())
    waits: list[float] = []
    assert _run(record, hub, tmp_path / "models", sleep=waits.append) == 1
    assert "disk is full" in capsys.readouterr().err
    assert waits == [] and len(hub.asks) == 1


# ------------------------------------------------------------------------------------------- review 8: staging


@pytest.mark.parametrize("kind", ["symlink", "hidden", "empty-dir", "fifo"])
def test_a_staged_folder_with_odd_entries_is_refused_then_cleaned(
    record: Path, hub: Hub, tmp_path: Path, kind: str
) -> None:
    models = tmp_path / "models"
    stage = models / fw.STAGE / VERIFIER_DIR
    stage.mkdir(parents=True)
    outside = tmp_path / "outside.txt"
    outside.write_text("outside\n", encoding="utf-8")
    if kind == "symlink":
        (stage / "linked").symlink_to(outside)
    elif kind == "hidden":
        (stage / ".hidden").write_text("x", encoding="utf-8")
    elif kind == "empty-dir":
        (stage / "empty").mkdir()
    else:
        os.mkfifo(stage / "pipe")
    assert _run(record, hub, models) == 1
    assert not (models / VERIFIER_DIR).exists() and not stage.exists()
    assert outside.read_text(encoding="utf-8") == "outside\n"
    assert _run(record, hub, models) == 0


def test_a_staged_file_that_is_a_link_is_not_reused(record: Path, hub: Hub, tmp_path: Path) -> None:
    models = tmp_path / "models"
    stage = models / fw.STAGE / VERIFIER_DIR
    stage.mkdir(parents=True)
    good = tmp_path / "good-config.json"
    good.write_bytes(REPOS[f"synth/verifier@{REV_V}"]["config.json"])  # the right bytes, behind a link
    (stage / "config.json").symlink_to(good)
    assert _run(record, hub, models) == 0
    assert not (models / VERIFIER_DIR / "config.json").is_symlink()
    assert ("config.json", None) in hub.asks


def test_a_part_file_that_is_a_link_is_never_written_through(record: Path, hub: Hub, tmp_path: Path) -> None:
    models = tmp_path / "models"
    part = models / fw.STAGE / VERIFIER_DIR / fw.PARTS / "LICENSE"
    part.parent.mkdir(parents=True)
    victim = tmp_path / "victim.txt"
    victim.write_text("keep me\n", encoding="utf-8")
    part.symlink_to(victim)
    assert _run(record, hub, models) == 1
    assert victim.read_text(encoding="utf-8") == "keep me\n"


def test_the_template_body_is_capped(
    record: Path, hub: Hub, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(fw, "TEMPLATE_MAX", 4)
    assert _run(record, hub, tmp_path / "models") == 1
    assert "more than the 4 bytes allowed" in capsys.readouterr().err


def test_old_staged_leftovers_are_removed(record: Path, hub: Hub, tmp_path: Path) -> None:
    models = tmp_path / "models"
    old = models / fw.STAGE / "a-folder-no-longer-asked-for" / "weights.safetensors"
    old.parent.mkdir(parents=True)
    old.write_bytes(b"old")
    assert _run(record, hub, models) == 0
    assert _stage_left(models) == [fw.LOCK]


# ------------------------------------------------------------------------------------------- review 9: dry run


def test_dry_run_reports_a_short_disk_as_the_real_run(
    record: Path, hub: Hub, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _run(record, hub, tmp_path / "models", dry_run=True, free_bytes=lambda _p: 10) == 1
    assert "not enough free disk" in capsys.readouterr().err
    assert hub.asks == []


def test_dry_run_refuses_a_plain_http_endpoint(
    record: Path, hub: Hub, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _run(record, hub, tmp_path / "models", dry_run=True, transport_cls=fw.Transport) == 2
    assert "would fetch http" not in capsys.readouterr().out


# ------------------------------------------------------------------------------------------- review 10: each check


def test_verify_finds_same_size_other_bytes(
    record: Path, hub: Hub, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The sha256 check of check_folder."""
    models = tmp_path / "models"
    assert _run(record, hub, models) == 0
    (models / VERIFIER_DIR / "model.safetensors").write_bytes(b"\x09" * 3000)
    capsys.readouterr()
    assert _run(record, None, models, verify_only=True) == 1
    assert "sha256 is not the pinned" in capsys.readouterr().out


def test_verify_says_a_wrong_size(record: Path, hub: Hub, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """The size check of check_folder."""
    models = tmp_path / "models"
    assert _run(record, hub, models) == 0
    (models / VERIFIER_DIR / "model.safetensors").write_bytes(b"\x02" * 10)
    capsys.readouterr()
    assert _run(record, None, models, verify_only=True) == 1
    assert "10 bytes, pinned 3000" in capsys.readouterr().out


def test_check_folder_holds_the_manifest(tmp_path: Path) -> None:
    """The manifest check of check_folder: right files, but a target whose expected digest differs."""
    folder = tmp_path / "f"
    folder.mkdir()
    (folder / "w.safetensors").write_bytes(b"w")
    t = fw.Target("folder", "f", "s/r", "r", [fw.PinnedFile("w.safetensors", _sha(b"w"), 1)], manifest_sha256="0" * 64)
    assert fw.check_folder(folder, t) == [f"{folder}: manifest is not the expected {'0' * 12}"]
    right = manifest_sha256_of_files([{"path": "w.safetensors", "sha256": _sha(b"w")}])
    assert fw.check_folder(folder, fw.Target("folder", "f", "s/r", "r", t.files, manifest_sha256=right)) == []


def test_a_redirect_to_plain_http_is_not_followed(hub: Hub, store: Hub) -> None:
    """The redirect handler's scheme check: the plain-http target never gets a request."""
    hub.redirect["LICENSE"] = f"{store.url}/any/LICENSE"
    t = strict_loopback(hub.port)()
    with pytest.raises(fw.HubRefused, match="only https"):
        t.open(fw.url_of(hub.url, "synth/verifier", REV_V, "LICENSE"))
    assert store.asks == []


def test_an_answer_from_a_plain_http_address_is_refused() -> None:
    """The final address check after the opener (whatever led there)."""

    class Resp(io.BytesIO):
        status = 200
        headers: dict[str, str] = {}  # noqa: RUF012 - a stand-in

        def geturl(self) -> str:
            return "http://elsewhere.invalid/file"

    t = fw.Transport()
    t._opener.open = lambda *_a, **_k: Resp(b"x")  # type: ignore[method-assign]
    with pytest.raises(fw.HubRefused, match="only https"):
        t.open("https://hub.invalid/o/r/resolve/x/file")


def test_an_oversized_part_is_discarded_and_fetched_again(record: Path, hub: Hub, tmp_path: Path) -> None:
    """The 'part larger than pinned' check: the part is dropped and the file fetched from the start."""
    models = tmp_path / "models"
    part = models / fw.STAGE / VERIFIER_DIR / fw.PARTS / "model.safetensors"
    part.parent.mkdir(parents=True)
    part.write_bytes(b"\x02" * 5000)
    assert _run(record, hub, models) == 0
    assert ("model.safetensors", None) in hub.asks
    _assert_pinned(models, record)


def test_a_body_longer_than_pinned_is_cut_off(
    record: Path, hub: Hub, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The streaming size check: more bytes than pinned are refused as such, not only by the hash."""
    hub.content[f"synth/verifier@{REV_V}"]["model.safetensors"] = b"\x02" * 3000 + b"\x00" * 100
    assert _run(record, hub, tmp_path / "models") == 1
    assert "sent more than the pinned 3000 bytes" in capsys.readouterr().err


@pytest.mark.parametrize("bad", ["../evil.json", "/abs.json", "a/../b.json", "a//b.json"])
def test_record_naming_an_unsafe_path_is_refused(record: Path, tmp_path: Path, bad: str) -> None:
    rec_path = record / "deploy" / "measured" / "rec.json"
    rec = json.loads(rec_path.read_text(encoding="utf-8"))
    rec["servers"][1]["model_files"].append({"path": bad, "bytes": 3, "sha256": "0" * 64})
    rec_path.write_text(json.dumps(rec), encoding="utf-8")
    reg = record / "models" / "registry.yaml"
    doc = yaml.safe_load(reg.read_text(encoding="utf-8"))
    doc["builds"][1]["expected"]["manifest_sha256"] = manifest_sha256_of_files(rec["servers"][1]["model_files"])
    reg.write_text(yaml.safe_dump(doc), encoding="utf-8")
    assert _run(record, None, tmp_path / "models") == 2


def test_record_listing_a_code_file_is_refused(record: Path, tmp_path: Path) -> None:
    rec_path = record / "deploy" / "measured" / "rec.json"
    rec = json.loads(rec_path.read_text(encoding="utf-8"))
    rec["servers"][1]["model_files"].append({"path": "modeling.py", "bytes": 3, "sha256": "0" * 64})
    rec_path.write_text(json.dumps(rec), encoding="utf-8")
    reg = record / "models" / "registry.yaml"
    doc = yaml.safe_load(reg.read_text(encoding="utf-8"))
    doc["builds"][1]["expected"]["manifest_sha256"] = manifest_sha256_of_files(rec["servers"][1]["model_files"])
    reg.write_text(yaml.safe_dump(doc), encoding="utf-8")
    assert _run(record, None, tmp_path / "models") == 2


def test_record_that_disagrees_with_the_registry_is_refused(record: Path, tmp_path: Path) -> None:
    reg = record / "models" / "registry.yaml"
    doc = yaml.safe_load(reg.read_text(encoding="utf-8"))
    doc["builds"][0]["expected"]["manifest_sha256"] = "f" * 64
    reg.write_text(yaml.safe_dump(doc), encoding="utf-8")
    assert _run(record, None, tmp_path / "models") == 2


def test_a_part_is_opened_without_following_a_link(tmp_path: Path) -> None:
    """O_NOFOLLOW on the part file, the guard behind the link check in fetch_file."""
    victim = tmp_path / "victim.txt"
    victim.write_text("keep me\n", encoding="utf-8")
    link = tmp_path / "part"
    link.symlink_to(victim)
    for append in (False, True):
        with pytest.raises(OSError) as exc:
            fw._open_part(link, append)
        assert exc.value.errno == errno.ELOOP
    assert victim.read_text(encoding="utf-8") == "keep me\n"

"""tools/fetch_weights.py (W-1) against a local fake hub serving tiny synthetic files; no model is downloaded."""

from __future__ import annotations

import hashlib
import http.server
import json
import threading
from collections.abc import Iterator
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
    """A local HTTP server with range support; ``cut`` makes the first ask for a path stop after N bytes."""

    def __init__(self) -> None:
        self.content = {k: dict(v) for k, v in REPOS.items()}
        self.cut: dict[str, int] = {}
        self.asks: list[tuple[str, str | None]] = []
        hub = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a: Any) -> None:
                pass

            def do_GET(self) -> None:
                # /<owner>/<name>/resolve/<revision>/<path>
                parts = self.path.lstrip("/").split("/")
                repo, rev, rel = "/".join(parts[:2]), parts[3], "/".join(parts[4:])
                hub.asks.append((rel, self.headers.get("Range")))
                body = hub.content.get(f"{repo}@{rev}", {}).get(rel)
                if body is None:
                    self.send_response(404)
                    self.end_headers()
                    return
                start = 0
                rng = self.headers.get("Range")
                if rng:
                    start = int(rng.split("=")[1].split("-")[0])
                    if start >= len(body):
                        self.send_response(416)
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
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


class LoopbackTransport(fw.Transport):
    """The real transport, allowed plain http for the loopback fake hub only (the tool itself is https only)."""

    allowed = ("https", "http")


@pytest.fixture
def hub() -> Iterator[Hub]:
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


def _run(record: Path, hub: Hub | None, models: Path, **kw: Any) -> int:
    env = {"HF_ENDPOINT": hub.url} if hub else {}
    kw.setdefault("free_bytes", lambda _p: 1 << 40)
    return fw.run(
        "rtxpro6000",
        models,
        env=env,
        transport=LoopbackTransport() if hub else None,
        sleep=lambda _s: None,
        registry=record / "models" / "registry.yaml",
        register=record / "docs" / "register.csv",
        root=record,
        **kw,
    )


def _assert_pinned(models: Path, record: Path) -> None:
    doc = yaml.safe_load((record / "models" / "registry.yaml").read_text(encoding="utf-8"))
    rows = {b["build_id"]: b for b in doc["builds"]}
    # the pin's own manifest (tools/pin_model.py) of each folder is the registry's expected one
    assert weight_manifest(models / JUDGE_DIR).sha256 == rows[JUDGE]["expected"]["manifest_sha256"]
    assert weight_manifest(models / VERIFIER_DIR).sha256 == rows[VERIFIER]["expected"]["manifest_sha256"]
    assert _sha((models / TEMPLATE).read_bytes()) == rows[JUDGE]["chat_template"]["sha256"]


def test_happy_path(record: Path, hub: Hub, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    models = tmp_path / "models"
    assert _run(record, hub, models) == 0
    _assert_pinned(models, record)
    assert not (models / fw.STAGE).exists()  # nothing left over
    assert not (models / JUDGE_DIR / ".gitattributes").exists()  # hidden: outside the manifest, not fetched
    asked = {p for p, _ in hub.asks}
    assert "modeling_extra.py" not in asked and ".gitattributes" not in asked
    out = capsys.readouterr().out
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
    leftovers = list((models / fw.STAGE).rglob("model.safetensors")) if (models / fw.STAGE).exists() else []
    assert leftovers == []  # the refused file is deleted


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


def test_unexpected_extra_file_in_staging_is_refused(record: Path, hub: Hub, tmp_path: Path) -> None:
    models = tmp_path / "models"
    stray = models / fw.STAGE / VERIFIER_DIR / "modeling_custom.py"
    stray.parent.mkdir(parents=True)
    stray.write_text("print('code')\n", encoding="utf-8")
    assert _run(record, hub, models) == 1
    assert not (models / VERIFIER_DIR).exists()


def test_folder_in_the_way_with_an_extra_file_is_left_alone(record: Path, hub: Hub, tmp_path: Path) -> None:
    models = tmp_path / "models"
    assert _run(record, hub, models) == 0
    extra = models / JUDGE_DIR / "pytorch_model.bin"
    extra.write_bytes(b"pickle")
    assert _run(record, None, models, verify_only=True) == 1
    hub.asks.clear()
    assert _run(record, hub, models) == 1  # refused, and the folder is not touched
    assert extra.exists() and hub.asks == []


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
    models = tmp_path / "models"
    rc = fw.run(
        "rtxpro6000",
        models,
        env={"HF_ENDPOINT": hub.url},
        free_bytes=lambda _p: 1 << 40,
        registry=record / "models" / "registry.yaml",
        register=record / "docs" / "register.csv",
        root=record,
    )
    assert rc == 2 and hub.asks == []


def test_token_goes_to_the_hub_only(hub: Hub) -> None:
    seen: list[str | None] = []
    t = LoopbackTransport(token="synthetic-token", hub_host="127.0.0.1")
    orig = t._opener.open

    def spy(req: Any, *a: Any, **k: Any) -> Any:
        seen.append(req.get_header("Authorization"))
        return orig(req, *a, **k)

    t._opener.open = spy  # type: ignore[method-assign,assignment]
    url = fw.url_of(hub.url, "synth/verifier", REV_V, "LICENSE")
    _status, _total, stream = t.open(url)
    stream.read()
    other = LoopbackTransport(token="synthetic-token", hub_host="hub.invalid")
    other._opener.open = spy  # type: ignore[method-assign,assignment]
    _status, _total, stream = other.open(url)
    stream.read()
    assert seen == ["Bearer synthetic-token", None]


def test_the_repository_pin_record_gives_a_verified_plan() -> None:
    """The committed registry and measured record: every profile file list matches its expected manifest (offline)."""
    targets = fw.plan("rtxpro6000", {})
    kinds = sorted(t.kind for t in targets)
    assert kinds == ["folder", "folder", "template"]
    for t in targets:
        assert t.revision and len(t.revision) == 40
        assert all(len(f.sha256) == 64 for f in t.files)
        assert not any(Path(f.path).suffix in (".bin", ".py") for f in t.files)
        assert t.licence["status"] == "cleared"


def test_install_and_start_never_fetch_weights() -> None:
    for script in ("deploy/poc.sh", "deploy/install.sh", "deploy/box-install.sh", "deploy/bootstrap.sh"):
        assert "fetch_weights" not in (ROOT / script).read_text(encoding="utf-8"), script

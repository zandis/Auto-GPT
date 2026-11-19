"""H-43: the rc1 site bundle's weights. ``tools/fetch_weights.py --embedder`` fetches and verifies ``embedder/`` (the
folder ``release check`` requires, D-998) beside the pair; the build route's b05 (``deploy/gcp/box-install-run.sh``)
passes the weights to ``make_bundle.sh --models`` for both keys; ``make_bundle.sh`` and ``tools/bundle_space.py`` read
a models folder through its links. Synthetic files and a loopback stand-in hub only: no model is downloaded, no cloud
call is made, the launcher script is not run (one of its functions is, with stand-ins)."""

from __future__ import annotations

import hashlib
import http.server
import json
import subprocess
import threading
import urllib.parse
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import yaml

from tools import bundle_space
from tools import fetch_weights as fw
from tools.pin_model import EMBED_BUILD, manifest_sha256_of_files, weight_manifest
from tools.release import embedder_problems

ROOT = Path(__file__).resolve().parents[2]
VM_SCRIPT = ROOT / "deploy" / "gcp" / "box-install-run.sh"
DRIVER = ROOT / "deploy" / "gcp" / "box-run.sh"
MAKE_BUNDLE = ROOT / "tools" / "make_bundle.sh"
JUDGE, VERIFIER = "gemma-4-26b-a4b-it-rtxpro6000", "qwen3.5-9b-rtxpro6000"
REV_J, REV_V, REV_E = "a" * 40, "b" * 40, "e" * 40

# synthetic repositories the stand-in hub serves: (repository@revision) -> {path: bytes}
REPOS: dict[str, dict[str, bytes]] = {
    f"synth/judge@{REV_J}": {"config.json": b'{"j": 1}\n', "model.safetensors": b"\x01" * 4000},
    f"synth/verifier@{REV_V}": {"config.json": b'{"v": 1}\n', "model.safetensors": b"\x02" * 3000},
    f"synth/embedder@{REV_E}": {
        "1_Pooling/config.json": b'{"pooling_mode_cls_token": true}\n',
        "config.json": b'{"e": 1}\n',
        "model.safetensors": b"\x03" * 5000,
        "tokenizer.json": b'{"synthetic": true}\n',
    },
}


def _files(repo: str) -> list[dict[str, Any]]:
    return [
        {"path": p, "bytes": len(b), "sha256": hashlib.sha256(b).hexdigest()} for p, b in sorted(REPOS[repo].items())
    ]


class Hub:
    """A loopback stand-in of the hub's ``/<owner>/<name>/resolve/<revision>/<path>``; every ask is recorded."""

    def __init__(self) -> None:
        self.asks: list[str] = []
        hub = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a: Any) -> None:
                pass

            def do_GET(self) -> None:
                parts = urllib.parse.unquote(self.path).lstrip("/").split("/")
                repo, rev, rel = "/".join(parts[:2]), parts[3], "/".join(parts[4:])
                hub.asks.append(f"{repo}/{rel}")
                body = REPOS.get(f"{repo}@{rev}", {}).get(rel)
                self.send_response(404 if body is None else 200)
                self.send_header("Content-Length", str(len(body or b"")))
                self.end_headers()
                self.wfile.write(body or b"")

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


class LoopbackTransport(fw.Transport):
    """The real transport, allowed plain http to the loopback stand-in only (the tool itself is https only)."""

    @classmethod
    def url_ok(cls, url: str) -> bool:
        u = urllib.parse.urlsplit(url)
        return u.scheme == "https" or (u.scheme == "http" and u.hostname == "127.0.0.1")


@pytest.fixture
def hub() -> Iterator[Hub]:
    h = Hub()
    yield h
    h.close()


def _checkout(tmp_path: Path, *, embed_source: bool = True) -> Path:
    """A synthetic checkout: the profile's pair and an ``e-embed-1`` row, the measured record(s), a licence register."""
    root = tmp_path / "checkout"
    (root / "models").mkdir(parents=True)
    (root / "deploy" / "measured").mkdir(parents=True)
    (root / "docs").mkdir()
    rec = {
        "servers": [
            {"model": "synth/judge", "model_files": _files(f"synth/judge@{REV_J}")},
            {"model": "synth/verifier", "model_files": _files(f"synth/verifier@{REV_V}")},
        ]
    }
    (root / "deploy" / "measured" / "rec.json").write_text(json.dumps(rec), encoding="utf-8")
    erec = {"servers": [{"model": "synth/embedder", "model_files": _files(f"synth/embedder@{REV_E}")}]}
    (root / "deploy" / "measured" / "embed.json").write_text(json.dumps(erec), encoding="utf-8")

    def row(build: str, repo: str, rev: str, source: str | None) -> dict[str, Any]:
        exp: dict[str, Any] = {"manifest_sha256": manifest_sha256_of_files(_files(f"{repo}@{rev}")), "revision": rev}
        if source:
            exp["source"] = source
        return {"build_id": build, "repository": repo, "expected": exp, "provenance": {"source": repo, "revision": rev},
                "licence": {"name": "Synthetic", "spdx": "MIT", "verified": True, "register": "model-synth"}}  # fmt: skip

    builds = [
        row(JUDGE, "synth/judge", REV_J, "deploy/measured/rec.json"),
        row(VERIFIER, "synth/verifier", REV_V, "deploy/measured/rec.json"),
        row(EMBED_BUILD, "synth/embedder", REV_E, "deploy/measured/embed.json" if embed_source else None),
    ]
    (root / "models" / "registry.yaml").write_text(yaml.safe_dump({"builds": builds}), encoding="utf-8")
    (root / "docs" / "register.csv").write_text(
        "id,licence,spdx,status,obligation,evidence\nmodel-synth,Synthetic,MIT,cleared,none,synthetic\n",
        encoding="utf-8",
    )
    return root


def _run(root: Path, hub: Hub | None, models: Path, **kw: Any) -> int:
    return fw.run(
        "rtxpro6000",
        models,
        env={"HF_ENDPOINT": hub.url} if hub else {},
        registry=root / "models" / "registry.yaml",
        register=root / "docs" / "register.csv",
        root=root,
        transport_cls=LoopbackTransport,
        free_bytes=lambda _p: 1 << 40,
        sleep=lambda _s: None,
        **kw,
    )


# ------------------------------------------------------------------------------------- D2: fetch_weights --embedder


def test_without_embedder_the_plan_is_the_pair_as_before(tmp_path: Path) -> None:
    root = _checkout(tmp_path)
    targets = fw.plan("rtxpro6000", {}, registry=root / "models/registry.yaml", register=root / "docs/register.csv",
                      root=root)  # fmt: skip
    assert {t.dest for t in targets} == {"gemma-4-26b-a4b-it-4bit", "qwen3.5-9b-4bit"}


def test_dry_run_lists_the_embedder_and_asks_nothing(
    tmp_path: Path, hub: Hub, capsys: pytest.CaptureFixture[str]
) -> None:
    root, models = _checkout(tmp_path), tmp_path / "models"
    assert _run(root, hub, models, dry_run=True, embedder=True) == 0
    out = capsys.readouterr().out
    assert "- embedder (folder, 4 file(s)" in out and f"for {EMBED_BUILD}" in out
    assert hub.asks == [] and not models.exists()


def test_the_embedder_is_fetched_verified_and_is_what_release_check_takes(tmp_path: Path, hub: Hub) -> None:
    root, models = _checkout(tmp_path), tmp_path / "models"
    assert _run(root, hub, models, embedder=True) == 0
    want = yaml.safe_load((root / "models" / "registry.yaml").read_text())["builds"][2]["expected"]["manifest_sha256"]
    assert weight_manifest(models / "embedder").sha256 == want
    assert sorted(a for a in hub.asks if a.startswith("synth/embedder/")) == sorted(
        f"synth/embedder/{p}" for p in REPOS[f"synth/embedder@{REV_E}"]
    )
    # the bundle's release check (tools/release.py embedder_problems, D-998) on a manifest of these files
    files = [{"path": f"embedder/{p.relative_to(models / 'embedder').as_posix()}",
              "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
             for p in sorted((models / "embedder").rglob("*")) if p.is_file()]  # fmt: skip
    assert embedder_problems({}, {"files": files}, root / "models" / "registry.yaml") == []
    assert _run(root, None, models, verify_only=True, embedder=True) == 0


def test_an_embedder_row_without_its_file_record_is_refused_and_nothing_is_guessed(
    tmp_path: Path, hub: Hub, capsys: pytest.CaptureFixture[str]
) -> None:
    root, models = _checkout(tmp_path, embed_source=False), tmp_path / "models"
    assert _run(root, hub, models, dry_run=True, embedder=True) == 2
    err = capsys.readouterr().err
    assert f"{EMBED_BUILD}:" in err and "expected.source" in err and "model_files" in err
    assert hub.asks == [] and not models.exists()
    assert _run(root, hub, models, dry_run=True) == 0  # the pair alone is as before


def test_the_repository_registry_either_gives_the_embedder_or_says_what_is_missing() -> None:
    """Today the e-embed-1 row holds its manifest digest and revision, not a committed per-file record (H43-01): the
    plan must say so, never invent a list. Once the record is committed, the plan must give the expected manifest."""
    try:
        targets = fw.plan("rtxpro6000", fw.resolve_env("rtxpro6000", {}), embedder=True)
    except fw.RecordError as exc:
        assert str(exc).startswith(f"{EMBED_BUILD}:") and "expected.source" in str(exc)
        return
    emb = [t for t in targets if t.dest == "embedder"]
    assert len(emb) == 1 and emb[0].builds == [EMBED_BUILD]
    assert manifest_sha256_of_files([{"path": f.path, "sha256": f.sha256} for f in emb[0].files]) == (
        emb[0].manifest_sha256
    )


def test_the_cli_takes_embedder() -> None:
    run = subprocess.run(
        [str(ROOT / ".venv" / "bin" / "python"), "-m", "tools.fetch_weights", "--help"],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )  # fmt: skip
    assert run.returncode == 0 and "--embedder" in run.stdout


# ---------------------------------------------------------------------- the models folder read through its links


def _cache_layout(tmp_path: Path) -> tuple[Path, Path]:
    """A model cache as the hub's tools write it (snapshot files are links to blobs) and a folder of links to it."""
    cache = tmp_path / "models"
    blobs = cache / "hub" / "blobs"
    snap = cache / "hub" / "snap" / REV_J
    blobs.mkdir(parents=True)
    snap.mkdir(parents=True)
    for name, body in REPOS[f"synth/judge@{REV_J}"].items():
        (blobs / hashlib.sha256(body).hexdigest()).write_bytes(body)
        (snap / name).symlink_to(f"../../blobs/{hashlib.sha256(body).hexdigest()}")
    (cache / "embedder").mkdir()
    (cache / "embedder" / "config.json").write_bytes(b'{"e": 1}\n')
    staged = tmp_path / "bundle-models"
    staged.mkdir()
    (staged / "judge").symlink_to(snap)
    (staged / "embedder").symlink_to(cache / "embedder")
    return cache, staged


def test_bundle_space_counts_the_models_through_links(tmp_path: Path) -> None:
    _cache, staged = _cache_layout(tmp_path)
    want = sum(len(b) for b in REPOS[f"synth/judge@{REV_J}"].values()) + len(b'{"e": 1}\n')
    assert bundle_space.payload_bytes([], staged, inspect=lambda _r: None) == want


def test_make_bundle_lists_the_models_through_links(tmp_path: Path) -> None:
    """make_bundle.sh's own models loop (its find line, run as written) over a folder of links."""
    text = MAKE_BUNDLE.read_text()
    assert text.count('find -L "$MODELS" -type f') == 1 and 'find "$MODELS" -type f' not in text
    _cache, staged = _cache_layout(tmp_path)
    loop = text[text.index('if [ -n "$MODELS" ]; then') :]
    loop = loop[: loop.index("\nfi\n") + 4]
    run = subprocess.run(["bash", "-c", f'set -euo pipefail; MODELS="$1"; ITEMS=()\n{loop}printf "%s\\n" "${{ITEMS[@]}}"',
                          "x", str(staged)], capture_output=True, text=True, check=False)  # fmt: skip
    assert run.returncode == 0, run.stderr
    rels = sorted(line.rsplit("=", 1)[1] for line in run.stdout.splitlines() if line.startswith("model:"))
    assert rels == ["embedder/config.json", "judge/config.json", "judge/model.safetensors"]


# ------------------------------------------------------------------------- D1: the build route's b05 passes them


def test_both_key_branches_pass_the_weights() -> None:
    text = VM_SCRIPT.read_text()
    for fn, nxt in (("d_sign() {", "d_sign_throwaway() {"), ("d_sign_throwaway() {", "b_room() {")):
        body = text[text.index(fn) : text.index(nxt)]
        assert body.count("tools/make_bundle.sh --key") == 1 and '--models "$BMODELS"' in body, fn
    sign = text[text.index("step_b_sign() {") : text.index("step_b_verify() {")]
    assert sign.index("d_bundle_models") < sign.index("d_sign_throwaway") < sign.index("d_sign\n")


def test_the_driver_names_the_embedder_list_for_a_build() -> None:
    text = DRIVER.read_text()
    build = text[text.index('elif [ "$STEPS" = build ]; then') :]
    build = build[: build.index("\nelse\n")]
    assert 'V[tb-embed-list]="${V[tb-embed-list]:-$BUCKET/r2/models/e-embed-1.sha256}"' in build


def _bundle_models(tmp_path: Path, *, embedder: bool) -> subprocess.CompletedProcess[str]:
    """d_models_put and d_bundle_models as written, with stand-ins for the helper (vm), fetch and note."""
    text = VM_SCRIPT.read_text()
    put = text[text.index("d_models_put() {") : text.index("d_models_place() {")]
    bm = text[text.index('BMODELS="$BUILD/bundle-models"') : text.index("step_b_sign() {")]
    cache, _staged = _cache_layout(tmp_path / "vm")
    if not embedder:
        (cache / "embedder" / "config.json").unlink()
    (cache / "chat-templates").mkdir()
    (cache / "chat-templates" / "t.jinja").write_text("{{ messages }}\n")
    (cache / "judge-4bit").symlink_to("hub/snap/" + REV_J)  # the flat folder models-place links (relative)
    script = (
        "set -u\n"
        f'MODELS="{cache}"; BUILD="{tmp_path / "build"}"; TB="{tmp_path}"; NOTES="{tmp_path / "notes"}"\n'
        'MODEL_LINKS="judge-4bit=hub/snap/x"; MODEL_TEMPLATE="chat-templates/t.jinja=https://x.invalid/t=0"\n'
        'EMBED_LIST_SRC=""; EMBED_URL="https://x.invalid/{path}"\n'
        'vm() { echo "vm $*" >> "$TB/vm.log"; }\nfetch() { return 1; }\n'
        'note() { printf \'%s\\t%s\\n\' "$1" "$2" >> "$NOTES"; }\n'
        f"{put}{bm}d_bundle_models\n"
    )
    return subprocess.run(["bash", "-c", script], capture_output=True, text=True, check=False)


def test_b05_lays_out_the_weights_as_compose_reads_them(tmp_path: Path) -> None:
    run = _bundle_models(tmp_path, embedder=True)
    assert run.returncode == 0, run.stdout + run.stderr
    staged = tmp_path / "build" / "bundle-models"
    assert sorted(p.name for p in staged.iterdir()) == ["chat-templates", "embedder", "judge-4bit"]
    assert (staged / "chat-templates" / "t.jinja").read_text() == "{{ messages }}\n"
    assert (staged / "judge-4bit" / "model.safetensors").read_bytes() == b"\x01" * 4000  # through both links
    assert (staged / "embedder" / "config.json").is_file()
    assert "models-place --root" in (tmp_path / "vm.log").read_text()


def test_b05_stops_without_the_embedder(tmp_path: Path) -> None:
    run = _bundle_models(tmp_path, embedder=False)
    assert run.returncode == 1 and "TB-NO-EMBEDDER" in run.stdout

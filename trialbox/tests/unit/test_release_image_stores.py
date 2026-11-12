"""OPS-004 (D-570): the release record matches a saved image against the gate record on either Docker image
store. The gates name an image by Docker's image id: on the classic store that is the config digest, on the
containerd store the digest of the image's index, which a ``docker save`` archive carries in ``index.json``. The
box rehearsal on a containerd-store host found every image "not a passing image of this record"."""

from __future__ import annotations

import datetime as dt
import io
import json
import tarfile
from pathlib import Path

import pytest

from tools import release
from tools.supply_chain import release as gates

CONFIG = "sha256:" + "c0" * 32
INDEX = "sha256:" + "1d" * 32
OTHER = "sha256:" + "ee" * 32
NOW = dt.datetime(2026, 11, 12, tzinfo=dt.UTC)

pytestmark = pytest.mark.nodb


def _archive(path: Path, *, index: list[str] | None, configs: tuple[str, ...] = (CONFIG,)) -> Path:
    manifest = [
        {"Config": f"blobs/sha256/{c.removeprefix('sha256:')}", "RepoTags": [f"trialbox-py:{n}"], "Layers": []}
        for n, c in enumerate(configs)
    ]
    members = {"manifest.json": json.dumps(manifest).encode()}
    if index is not None:
        members["index.json"] = json.dumps({"schemaVersion": 2, "manifests": [{"digest": d} for d in index]}).encode()
    with tarfile.open(path, "w") as tf:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
    return path


def _record(image_id: str) -> dict[str, object]:
    return {
        "ok": True,
        "created": NOW.isoformat(),
        "images": [{"ref": "trialbox-py:0", "ok": True, "image_id": image_id}],
    }


def test_an_archive_is_known_by_its_config_digest_and_by_its_index_digest(tmp_path: Path) -> None:
    a = _archive(tmp_path / "a.tar", index=[INDEX])
    assert release.archive_identities(a) == (CONFIG, INDEX)
    assert release.archive_identities(_archive(tmp_path / "b.tar", index=None)) == (CONFIG,)  # an older docker save
    # two images in one archive: an index digest could be the other image's, so only the config digests count
    two = _archive(tmp_path / "c.tar", index=[INDEX, OTHER], configs=(CONFIG, OTHER))
    assert release.archive_identities(two) == (CONFIG, OTHER)


@pytest.mark.parametrize("gated", [CONFIG, INDEX])
def test_the_gate_record_may_name_either(tmp_path: Path, gated: str) -> None:
    """Classic store: the gates saw the config digest. Containerd store: the index digest."""
    ids = release.archive_identities(_archive(tmp_path / "a.tar", index=[INDEX]))
    assert release.gate_problems(_record(gated), {"trialbox-py:0": ids}, now=NOW) == []


def test_an_image_the_gates_did_not_pass_is_still_refused(tmp_path: Path) -> None:
    ids = release.archive_identities(_archive(tmp_path / "a.tar", index=[INDEX]))
    problems = release.gate_problems(_record(OTHER), {"trialbox-py:0": ids}, now=NOW)
    assert problems == [f"trialbox-py:0 ({CONFIG}) is not a passing image of this record; run make release-gates"]
    assert (
        gates.bundle_problems(_record(OTHER), {"trialbox-py:0": CONFIG}, now=NOW) == problems
    )  # a plain id, as before
    assert gates.bundle_problems(_record(CONFIG), {"trialbox-py:0": ""}, now=NOW)  # no id at all


def test_the_rehearsal_stops_when_its_bundle_is_not_built() -> None:
    """`set -e` does not act in a step (it runs inside an `if`): the media step said ok with no bundle."""
    text = (Path(release.__file__).resolve().parent / "rehearse_box" / "rehearse.sh").read_text(encoding="utf-8")
    media = text[text.index("media() (") : text.index("host_image() {")]
    assert (
        '--models "$W/vendor/models" --refdata "$pack" "${args[@]}" \\\n    || { echo "the bundle was not built"; return 1; }'
        in media
    )
    assert '[ -s "$MEDIA/linux/$BUNDLE_NAME" ] || { echo "no bundle at' in media
    assert "cannot pull $i" in media


@pytest.mark.parametrize("gated", [CONFIG, INDEX])
def test_the_images_sbom_is_found_under_either_id(tmp_path: Path, gated: str) -> None:
    """The second stop of the same run: "the gate record names no SBOM for image <config digest>"."""
    a = _archive(tmp_path / "a.tar", index=[INDEX])
    entry = {"image_id": gated, "sbom": "py.cdx.json"}
    assert release.gate_entry({gated: entry}, a) is entry
    assert release.gate_entry({OTHER: entry}, a) is None

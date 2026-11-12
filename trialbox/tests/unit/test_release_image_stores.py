"""OPS-004 (D-570): the release record matches a saved image against the gate record on either Docker image
store. The gates name an image by Docker's image id: on the classic store that is the config digest, on the
containerd store the digest of the image's index, which a ``docker save`` archive carries in ``index.json`` and
as a blob. The box rehearsal on a containerd-store host found every image "not a passing image of this record".
An index digest counts only when the archive's own blobs lead from it to the image's config: a digest written
into ``index.json`` by hand, or the digest of a second image in the archive, names nothing."""

from __future__ import annotations

import datetime as dt
import hashlib
import io
import json
import tarfile
from pathlib import Path

import pytest

from tools import release
from tools.supply_chain import release as gates

NOW = dt.datetime(2026, 11, 12, tzinfo=dt.UTC)
OTHER = "sha256:" + "ee" * 32

pytestmark = pytest.mark.nodb


def _blob(doc: object) -> tuple[str, bytes]:
    data = json.dumps(doc, sort_keys=True).encode()
    return "sha256:" + hashlib.sha256(data).hexdigest(), data


class Image:
    """One image as the containerd store saves it: a config, a manifest that names it, an index that names the
    manifest (and an attestation manifest, as BuildKit adds)."""

    def __init__(self, name: str) -> None:
        self.config, self.config_blob = _blob({"architecture": "amd64", "name": name})
        self.manifest, self.manifest_blob = _blob({"config": {"digest": self.config}, "layers": []})
        attestation, self.att_blob = _blob({"config": {"digest": _blob({"attestation": name})[0]}, "layers": []})
        self.attestation = attestation
        self.index, self.index_blob = _blob({"manifests": [{"digest": self.manifest}, {"digest": attestation}]})

    def blobs(self) -> dict[str, bytes]:
        pairs = ((self.config, self.config_blob), (self.manifest, self.manifest_blob),
                 (self.attestation, self.att_blob), (self.index, self.index_blob))  # fmt: skip
        return {f"blobs/sha256/{d.removeprefix('sha256:')}": b for d, b in pairs}


def _archive(
    path: Path, images: list[tuple[Image, str | None]], *, index: list[str] | None, blobs: bool = True
) -> Path:
    manifest = [
        {
            "Config": f"blobs/sha256/{im.config.removeprefix('sha256:')}",
            "RepoTags": [tag] if tag else None,
            "Layers": [],
        }
        for im, tag in images
    ]
    members = {"manifest.json": json.dumps(manifest).encode()}
    if index is not None:
        members["index.json"] = json.dumps({"schemaVersion": 2, "manifests": [{"digest": d} for d in index]}).encode()
    if blobs:
        for im, _ in images:
            members.update(im.blobs())
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


PY = Image("trialbox-py")
OTHER_IMAGE = Image("another image, one the gates passed")


def test_an_archive_is_known_by_its_config_digest_and_by_its_index_digest(tmp_path: Path) -> None:
    a = _archive(tmp_path / "a.tar", [(PY, "trialbox-py:0")], index=[PY.index])
    assert release.archive_identities(a) == (PY.config, PY.index)
    assert release.archive_identities(_archive(tmp_path / "b.tar", [(PY, "trialbox-py:0")], index=None)) == (PY.config,)
    by_manifest = _archive(tmp_path / "c.tar", [(PY, "trialbox-py:0")], index=[PY.manifest])  # a store that lists it
    assert release.archive_identities(by_manifest) == (PY.config, PY.manifest)


@pytest.mark.parametrize("which", ["config", "index"])
def test_the_gate_record_may_name_either(tmp_path: Path, which: str) -> None:
    """Classic store: the gates saw the config digest. Containerd store: the index digest."""
    ids = release.archive_identities(_archive(tmp_path / "a.tar", [(PY, "trialbox-py:0")], index=[PY.index]))
    assert release.gate_problems(_record(getattr(PY, which)), {"trialbox-py:0": ids}, now=NOW) == []


def test_an_image_the_gates_did_not_pass_is_still_refused(tmp_path: Path) -> None:
    ids = release.archive_identities(_archive(tmp_path / "a.tar", [(PY, "trialbox-py:0")], index=[PY.index]))
    problems = release.gate_problems(_record(OTHER), {"trialbox-py:0": ids}, now=NOW)
    assert problems == [f"trialbox-py:0 ({PY.config}) is not a passing image of this record; run make release-gates"]
    assert gates.bundle_problems(_record(OTHER), {"trialbox-py:0": PY.config}, now=NOW) == problems  # a plain id
    assert gates.bundle_problems(_record(PY.config), {"trialbox-py:0": ""}, now=NOW)  # no id at all
    assert gates.bundle_problems(_record(PY.config), {"trialbox-py:0": ()}, now=NOW)


def test_review_a_second_untagged_image_does_not_lend_its_digest(tmp_path: Path) -> None:
    """The review of #363, HIGH-1: `docker save tagged untagged-id` writes one tagged entry, one untagged, and both
    index digests. The gates had passed the untagged one only; the tagged, ungated image was let through with the
    other's SBOM."""
    mix = _archive(
        tmp_path / "mix.tar", [(PY, "trialbox-py:0"), (OTHER_IMAGE, None)], index=[PY.index, OTHER_IMAGE.index]
    )
    ids = release.archive_identities(mix)
    assert ids == (PY.config,) and OTHER_IMAGE.index not in ids  # more than one image: the config digest only
    assert release.gate_problems(_record(OTHER_IMAGE.index), {"trialbox-py:0": ids}, now=NOW)
    entry = {"image_id": OTHER_IMAGE.index, "sbom": "other.cdx.json"}
    assert release.gate_entry({OTHER_IMAGE.index: entry}, mix) is None
    assert release.archive_image_count(mix) == 2  # what the build's "one image per archive" now counts


def test_review_an_index_digest_counts_only_when_the_blobs_lead_to_the_config(tmp_path: Path) -> None:
    """index.json is text: a digest written into it by hand, one whose blob is missing, and one whose blob is the
    index of another image name nothing."""
    by_hand = _archive(tmp_path / "a.tar", [(PY, "trialbox-py:0")], index=[OTHER_IMAGE.index])
    assert release.archive_identities(by_hand) == (PY.config,)
    no_blobs = _archive(tmp_path / "b.tar", [(PY, "trialbox-py:0")], index=[PY.index], blobs=False)
    assert release.archive_identities(no_blobs) == (PY.config,)
    # another image's index and blobs put beside the one tagged image: its chain ends at another config
    planted = tmp_path / "c.tar"
    _archive(planted, [(PY, "trialbox-py:0")], index=[OTHER_IMAGE.index])
    with tarfile.open(planted, "a") as tf:
        for name, data in OTHER_IMAGE.blobs().items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
    assert release.archive_identities(planted) == (PY.config,)
    # a blob whose bytes are not its name
    lying = tmp_path / "d.tar"
    _archive(lying, [(PY, "trialbox-py:0")], index=[OTHER], blobs=True)
    with tarfile.open(lying, "a") as tf:
        info = tarfile.TarInfo(f"blobs/sha256/{OTHER.removeprefix('sha256:')}")
        info.size = len(PY.index_blob)
        tf.addfile(info, io.BytesIO(PY.index_blob))
    assert release.archive_identities(lying) == (PY.config,)


@pytest.mark.parametrize("which", ["config", "index"])
def test_the_images_sbom_is_found_under_either_id(tmp_path: Path, which: str) -> None:
    """The second stop of the same run: "the gate record names no SBOM for image <config digest>"."""
    a = _archive(tmp_path / "a.tar", [(PY, "trialbox-py:0")], index=[PY.index])
    gated = getattr(PY, which)
    entry = {"image_id": gated, "sbom": "py.cdx.json"}
    assert release.gate_entry({gated: entry}, a) is entry
    assert release.gate_entry({OTHER: entry}, a) is None


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

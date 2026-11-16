"""The vendor side of the box-run rehearsal: a signed bundle of the REAL format, made with the REAL signer
(tools/sign_bundle.build: manifest, Ed25519 signature, compat.json, release.json, files/<path>) over the REAL host
tree of this checkout (tools/host_tree pack: deploy/box-install.sh and the tools it runs). What is left out: the image
tars and the release record's image digests (tools/release.py needs the images and the release gates' record: the
paid build makes them with `make images release-gates` and tools/make_bundle.sh). Run with the repo's venv python:

    mkbundle.py --key K --id ID --seq N --host HOST.tar --commit SHA --out OUT [--rehearsal] [--dirty] [--tamper]
"""

import argparse
import json
import sys
import tarfile
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path[:0] = [str(ROOT), str(ROOT / "libs")]

from tools import sign_bundle  # noqa: E402

ap = argparse.ArgumentParser()
for f in ("--key", "--id", "--host", "--commit", "--out"):
    ap.add_argument(f, required=True)
ap.add_argument("--seq", type=int, required=True)
ap.add_argument("--rehearsal", action="store_true", help="as make_bundle.sh --rehearsal (D-726)")
ap.add_argument("--dirty", action="store_true", help="as make_bundle.sh --allow-dirty (D-631)")
ap.add_argument("--tamper", action="store_true", help="one payload changed after signing (same size)")
a = ap.parse_args()
# a pinned image name and digest only: no image tar rides along (release.json and images.lock agree, as built)
IMAGES = {"standin": {"image": "trialbox-standin:0", "digest": "sha256:" + "0" * 64}}
release = {"version": a.id, "source": {"commit": a.commit, "dirty": a.dirty, "tag": None}, "images": IMAGES}
if a.rehearsal:
    release["rehearsal"] = True
with tempfile.TemporaryDirectory() as t:
    rules = Path(t) / "rules.json"
    rules.write_text('{"synthetic": true}\n')
    items = [("host", Path(a.host), "trialbox-host.tar"), ("other", rules, "rulesets/rules.json")]
    out = Path(a.out)
    sign_bundle.build(
        Path(a.key),
        a.id,
        items,
        out,
        release_seq=a.seq,
        release=release,
        images_lock={"format": "trialbox-images-lock/1", "images": IMAGES},
    )
    if a.tamper:  # the same bytes count, other content: the manifest's sha256 no longer holds
        tmp = out.with_suffix(".tmp")
        with tarfile.open(out) as src, tarfile.open(tmp, "w", format=tarfile.PAX_FORMAT) as dst:
            for m in src.getmembers():
                data = src.extractfile(m).read()  # type: ignore[union-attr]
                if m.name == "files/rulesets/rules.json":
                    data = data.replace(b"true", b"TRUE")
                import io

                dst.addfile(m, io.BytesIO(data))
        tmp.replace(out)
print(json.dumps({"bundle": a.out, "release": release}))

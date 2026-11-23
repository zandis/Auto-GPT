"""H-95 (the re-review of #1409, F1) on the rehearsal's real engine: an image archive swapped on the stick after the
pin read leaves nothing loaded, even when the engine registers it after the load client has ended.

The rehearsal job (tools/rehearse_box/rehearse.sh, step swapped-stream) runs it on the CI runner's Docker engine,
whichever image store it has. Synthetic images only: one layer of random bytes, made with ``docker import`` (no
registry, no network). Two cases, each through ``tools/trialbox/update.py``'s real ``stream_image``:

* new name: the archive the pins were read from names ``h95probe-engine:1``; the stick then holds a complete
  archive of another image named ``h95probe-db:16`` that ends well before the held-back last MiB (zeros after it);
* the pinned name: the box already holds ``h95probe-engine:1``; the swapped archive is another image under that name.

After the refusal it waits 30 s (the re-review saw the swapped image appear 2 s after the old undo and stay) and
holds that the engine is as it was before the load: no new tag, no new image id, the pinned name unmoved. It removes
its own images at the end. Exit 0 only when both cases hold.

    PYTHONPATH=libs:. python -m tools.rehearse_box.h95_probe WORK_DIR
"""

from __future__ import annotations

import hashlib
import io
import os
import subprocess
import sys
import tarfile
import time
from pathlib import Path

from tools.trialbox import update as up

MB = 1 << 20
WAIT_S = 30


def docker(*args: str) -> str:
    return subprocess.run(["docker", *args], check=True, capture_output=True, text=True, timeout=600).stdout


def make_image(work: Path, tag: str, size: int) -> Path:
    """A one-layer synthetic image under ``tag``, saved to an archive; the image itself is removed again."""
    rootfs = work / f"{tag.replace(':', '_').replace('/', '_')}.rootfs.tar"
    with tarfile.open(rootfs, "w:") as tf:
        info = tarfile.TarInfo("payload.bin")
        info.size = size
        tf.addfile(info, io.BytesIO(os.urandom(size)))
    docker("import", str(rootfs), tag)
    out = work / f"{rootfs.name.removesuffix('.rootfs.tar')}.{time.monotonic_ns()}.tar"
    docker("save", "-o", str(out), tag)
    docker("image", "rm", "-f", tag)
    rootfs.unlink()
    return out


def stick_with(work: Path, archive: Path) -> tuple[Path, up.Streamed]:
    """A stand-in stick: the archive as a payload of a tar, read where it lies (as a pack's payload is)."""
    stick = work / "stick.tar"
    with tarfile.open(stick, "w:") as tf:
        tf.add(archive, arcname="files/engine.tar")
    with tarfile.open(stick) as tf:
        m = tf.getmember("files/engine.tar")
    sha = hashlib.sha256(archive.read_bytes()).hexdigest()
    return stick, up.Streamed(stick, "engine.tar", "image", sha, m.size, m.offset_data)


def swap(p: up.Streamed, other: Path) -> None:
    data = other.read_bytes()
    assert len(data) < p.size - (2 * MB), "the swapped archive must end well before the held-back last MiB"
    with p.bundle.open("r+b") as fh:
        fh.seek(p.offset)
        fh.write(data + b"\0" * (p.size - len(data)))


def case(work: Path, name: str, swap_tag: str, preload: bool) -> bool:
    work.mkdir(parents=True, exist_ok=True)
    original = make_image(work, "h95probe-engine:1", 160 * MB)
    swapped = make_image(work, swap_tag, 96 * MB)
    if preload:
        docker("load", "-i", str(original))
    _stick, p = stick_with(work, original)
    configs, manifests = up.tar_images(p)  # the pin read, before the stick changes
    swap(p, swapped)
    before = up.image_state(up.run_cmd)
    try:
        up.stream_image(p, configs, manifests, up.run_cmd)
        print(f"FAIL {name}: the swapped archive was taken")
        return False
    except up.UpdateFailed as exc:
        print(f"    {name}: refused: {str(exc)[:300]}")
    time.sleep(WAIT_S)
    after = up.image_state(up.run_cmd)
    new_tags = {t: i for t, i in after[0].items() if before[0].get(t) != i}
    gone = {t: i for t, i in before[0].items() if t not in after[0]}
    new_ids = sorted(after[1] - before[1])
    for t in ("h95probe-engine:1", swap_tag):
        subprocess.run(["docker", "image", "rm", "-f", t], capture_output=True, check=False)
    if new_tags or gone or new_ids:
        print(f"FAIL {name}: {WAIT_S} s after the refusal the engine differs: moved or new tags {new_tags}, "
              f"tags gone {gone}, new image ids {new_ids}")  # fmt: skip
        return False
    held = before[0].get("h95probe-engine:1")
    print(f"ok: {name}: refused, and {WAIT_S} s later no new tag, no new image id, the pinned name "
          f"{'unmoved (' + held[:19] + ')' if held else 'still absent'}")  # fmt: skip
    return True


def main(argv: list[str]) -> int:
    work = Path(argv[1] if len(argv) > 1 else "h95-probe").absolute()
    store = docker("info", "-f", "{{.Driver}}").strip()
    print(f"    engine {docker('version', '-f', '{{.Server.Version}}').strip()}, store {store}")
    results = [case(work / "new-name", "a complete archive of another image (h95probe-db:16) that ends early",
                    "h95probe-db:16", preload=False),
               case(work / "pinned-name", "another image under the pinned name, the original already loaded",
                    "h95probe-engine:1", preload=True)]  # fmt: skip
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

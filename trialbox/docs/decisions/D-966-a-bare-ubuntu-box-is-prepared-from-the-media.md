# D-966 a bare Ubuntu box is prepared from the media

- **Task:** OPS-006, lane D backlog (#639, 2026-11-16; the owner's ruling to complete everything as soon as possible)
- **PR:** this branch (`agent/OPS-006-box-prepare-and-the-linux-media`)
- **Date:** 2026-11-16
- **Status:** accepted

## Decision

"One installer for hardware the site bought" needed a prepared host that nothing prepared: `box-install.sh` died
without Docker, and no script built the Linux media (deep review 2026-11-12, OPS-006). Plan v7 parks the bare Ubuntu
form behind the Windows one; this card gives it its media and its preparation step.

1. `tools/linux_media.py` reuses the Windows media's tools rather than adding a second format:
   `windows_media_debs.collect` asks apt for the packages, and `windows_media`'s helpers lay out, list and check the
   folder. The Linux set is the Windows one plus the Linux NVIDIA driver (`nvidia-driver-580-server-open`: install.sh
   wants 580.65.06 or later and the Blackwell cards need the open modules), python3-yaml, python3-cryptography,
   avahi-daemon (D-965) and openssl, from Ubuntu's `main universe restricted`.
2. `tools/windows_media_debs.py` (lane W's file, the smallest hunk) takes three keyword arguments: `packages`,
   `components` and `allow_driver`. Their defaults are the Windows media's values, so that media is unchanged.
3. `sign` writes `SHA256SUMS.sig`, a raw Ed25519 signature over `SHA256SUMS`, which openssl checks. It refuses a
   media that fails its check, and a key that is not the media's `linux/vendor_ed25519.pub`. The key file is named by
   the vendor on the signing machine, as `make_bundle.sh --key` is.
4. `deploy/box-prepare.sh <media> --pub <key given out of band>` runs as root on Ubuntu 24.04. Before it installs
   anything, it refuses:
   - another system;
   - another key;
   - a bad signature;
   - a changed byte;
   - an unlisted file (the package glob would install it).

   Then it installs the packages with `dpkg -i`, starts Docker with the nvidia runtime on a box with an NVIDIA card,
   enables cron, unpacks the host tree to `/opt/trialbox` and copies the key there; it never unpacks over a folder
   that holds something else. It prints what comes next: a reboot when the driver is not loaded yet, then
   `box-install.sh` with the media's bundle. It can be run again.
5. `box-install.sh` on a machine without Docker names this step instead of failing at `docker run`.
6. `make media-linux` runs the build step. RUNBOOK §16 and `OFFLINE-MEDIA.md` say the same.

Not here:
- the disk's unlock rule (HW-010, an owner decision);
- the run on a real bare box (T-213b);
- the actual package set of a release: `debs` runs online on the vendor's machine, and nothing is fetched or
  committed here.

## Test

`tests/unit/test_linux_media.py`:
- the package set, and the collector called with the Linux keywords;
- the Windows collector's defaults unchanged;
- the layout and sums;
- openssl verifies the signature;
- refused: a set without Docker, the toolkit or the driver; a full folder;
- check and sign refusing;
- the CLI;
- box-prepare.sh with stand-ins for dpkg, systemctl, docker and nvidia-ctk:
  - installs, re-runs, and runs without a GPU;
  - refuses another system, a changed byte, an unlisted file, another key, a bad signature and a missing `--pub`;
  - never unpacks over a foreign folder;
- box-install.sh without Docker.

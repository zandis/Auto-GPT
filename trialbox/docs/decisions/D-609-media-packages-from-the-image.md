# D-609 The media's Ubuntu packages are worked out against the image itself; the image is known by what it is

- **Task:** NEW-WIN-9, the media part, second card (`docs/plan/33-plan-v7.md` section 2.3; lane W; wave 3)
- **PR:** this branch (`agent/NEW-WIN-9-media-packages`), on top of D-605 (the media builder)
- **Date:** 2026-11-13
- **Status:** accepted. The package tool ran once for real on 2026-11-13 against Canonical's image (below). That
  the packages install on that image inside WSL2 is the installer's package step, first seen at P-0 (line 10)
- **Builds on:** D-605 (`tools/windows_media.py`), D-600 (the installer's package step: `dpkg -i` from the media,
  no Linux NVIDIA driver), D-125 (the workstation is never online)

## Context

D-605 lays the media out from files the vendor names, and says where the packages for Ubuntu go (`linux/debs`).
Nothing said which packages, and getting it wrong shows only on a workstation that cannot fetch what is missing.
The set depends on what the Ubuntu WSL image already holds. Writing the owner's commands for the first rehearsal
also showed that Canonical's file is `ubuntu-noble-wsl-amd64-24.04lts.rootfs.tar.gz`, a name neither the builder
nor the installer's `ubuntu-24.04*.tar.gz` accepts; D-605's documents named a file nobody publishes.

## Decision

1. **`tools/windows_media_debs.py --rootfs <image> --out <folder>`** works the set out against the image
   itself: it copies the image's own list of installed packages (`var/lib/dpkg/status`) and its archive keyring
   out of the tarball and asks `apt-get` what installing the installer's packages (`docker-ce`, `docker-ce-cli`,
   `containerd.io`, `docker-compose-plugin`, `nvidia-container-toolkit`, `nftables`, `cron`) on exactly that
   system would fetch. No container and no root are needed (run it as an ordinary user). It refuses an image
   that is not a whole Ubuntu 24.04 for amd64, a set that holds a Linux NVIDIA driver, an empty result, and an
   output folder that holds files.
2. **apt runs in a world made new for each run, and only what apt named reaches the output.**
   - The working folder (state, lists, cache, sources, trusted keys) is made new for every run and removed after
     it; `--work` only says where. Nothing an earlier run or anyone else left behind can reach apt.
   - apt's configuration comes by a file (`APT_CONFIG`) with `Dir::Etc` inside the working folder, and apt runs
     with an environment of four variables and the machine's proxy. This matters: apt reads the machine's own
     `/etc/apt/apt.conf.d` before it looks at its command line, so `-o` options (the first form of this card)
     came too late to keep the machine's hooks and "allow unauthenticated" settings out. Unauthenticated and
     insecure repositories are switched off in that file.
   - apt is asked first which files it would fetch (`--print-uris`); after the download exactly those names are
     copied, each of which apt fetched and checked against the signed lists in this run. A file apt did not name
     is never copied: the installer runs `dpkg -i` on every package of the media as root.
3. **This is the one media tool that goes online**, and only when the vendor runs it; it writes only where the
   vendor says. `tools/windows_media.py` still fetches nothing (its test holds that) and imports nothing from
   this tool.
4. **The repository keys are pinned.** Ubuntu's archive is checked with the image's own keyring. Docker's and
   NVIDIA's keys are fetched over HTTPS and accepted only when the key file holds exactly one primary key with
   the fingerprint written in the tool (Docker: `9DC8 5822 9FC7 DD38 854A E2D8 8D81 803C 0EBF CD88`; NVIDIA
   libnvidia-container: `C95B 321B 61E8 8C18 09C4 F759 DDCA E044 F796 ECB0`), read with `gpg --show-keys`,
   importing nothing. Every source has a key of its own (`signed-by`).
5. **The media builder knows the image by what it is**, not by its file name: the archive is read to its end (a
   copy cut short on the way is refused at the vendor's, not on the workstation), its `os-release` must say
   Ubuntu 24.04 (the file under `etc`, or `usr/lib` when `etc` holds a link, as in Canonical's image), and its
   installed packages must be amd64 (Canonical publishes the same release for arm64 under a like name). A name
   that fits the installer's pattern is kept; Canonical's gets `ubuntu-24.04.` put before it, so the installer
   finds it and the publisher's name stays readable. The installer is not changed.
6. **Recommended packages are not taken** (`--no-install-recommends`): the set is what the installer's package
   step needs. Docker's own recommendations that the image lacks are `docker-buildx-plugin`,
   `docker-ce-rootless-extras` and `pigz`; the box loads its images from the signed bundle and builds none on
   site (the installer's small GPU probe image is made with `docker import`, which uses no builder). If a later
   card builds an image on the box, `docker-buildx-plugin` joins `PACKAGES`.

**Reuse check.** apt itself does the work (its resolver, its signature checks); the tool only points it at the
image. `apt-offline` and `apt-rdepends` exist for nearby jobs: the first wants to run on the offline machine
first, the second lists dependencies without the image's state. A container of the image (`docker import`) gives
the same answer and needs a Docker daemon and root on the vendor's machine; not needed.

## What is proven here, and what is not

**Run for real, by hand (2026-11-13, this build machine, Ubuntu 24.04), twice: before and after the review's
fixes, with the same result.** Against Canonical's `ubuntu-noble-wsl-amd64-24.04lts.rootfs.tar.gz` (sha256
`2a790896...bd9934`, matching Canonical's `SHA256SUMS`) the tool accepted both repository keys by fingerprint and
fetched 16 packages, 84 MB, in about 20 seconds: Docker Engine 29.9.3 with its CLI, containerd.io and the compose
plugin, the NVIDIA Container Toolkit 1.20.2 with its three companions, nftables and seven libraries; apt reported
"0 upgraded, 16 newly installed". `cron` was already in the image. The second run gave the same 16 files, byte for
byte, and left its working folder empty. The reviewer ran it too, as root and as an unprivileged user, with the
same set, and checked every package's `Depends` and `Pre-Depends` against the image's package list and the set:
none unsatisfied, no upgrade of an image package. `tools.windows_media build` then laid out a media from that
image and those packages (stand-ins for the bundle and the WSL package) in 9 seconds and its `check` passed. The
first real run found what the stand-in images had not: in the real image `etc/os-release` is a link to
`usr/lib/os-release`; a test now builds an image that way.

Proven by tests (offline; apt-get and the network replaced; the real `apt-config`, where the machine has one,
shows that none of the machine's apt settings reach the run): which files are read from the image; the refusals,
a cut archive and an arm64 image included; the configuration file, the environment and the sources apt is given;
the fingerprint rule; that a package apt did not name, and a working folder left by an earlier run, never reach
the output.

Not proven: that `dpkg -i` of the set succeeds on the image inside WSL2 (the installer's package step; P-0 line
10). Completeness rests on apt's resolver, which worked the set out against the image's own state; no install was
run here. That the set stays right as the repositories move: the tool is run again for each release, and the
release records the set (`SHA256SUMS` of the media).

## Consequences

- The owner can build a media from a fresh checkout with the commands in `docs/handover/OFFLINE-MEDIA.md`.
- For lane D: the release target can run both tools after the bundle is signed; an offline Ubuntu patch bundle
  (`tools/apply_update.sh`) can be made the same way against the box's current package list.

# Offline media layout (D-125, D-138)

**Reader:** Aimedics, who make the media, and the box owner, who starts the installer from it.

The Windows workstation never reaches the internet, at install or after (D-125). Everything comes on one USB disk
(or the same folder copied to a local drive; a mapped network drive is not used: a window that runs as
administrator does not see another sign-in's mapped drives), made by Aimedics from a signed release. The box owner starts
`Install-TrialBox.cmd`; `windows/box-install.ps1` reads this layout (NEW-WIN-1, D-600). It checks every file it
uses against `SHA256SUMS` before it changes anything, and stops when one is missing, unlisted or damaged.

```
TRIALBOX-<version>/                      one folder per release, read-only on the disk
  README.txt                             version, date, sha256 of every file below, who built it
  SHA256SUMS                             sha256 of every file; SHA256SUMS.sig: Ed25519 by the vendor key
  Install-TrialBox.cmd                   deploy/windows/Install-TrialBox.cmd: what the box owner double-clicks
  windows/
    box-install.ps1                      deploy/windows/box-install.ps1, the installer (NEW-WIN-1)
    box-install.messages.json            its messages in en, ja and zh-TW
    wsl-setup.sh                         its steps inside WSL2
    register_keepalive.ps1               the start-at-boot task the installer registers (NEW-WIN-2)
    console-proxy.ps1                    Windows 10: keeps the console's forwarding pointed at WSL2 (NEW-WIN-10)
    key-probe.ps1                        which Windows key store the boot task can open (NEW-WIN-8; P-0 line 36)
    preflight.ps1, host_facts.ps1        deploy/windows/: the read-only checks (D-421)
    wsl/wsl.<version>.x64.msi            WSL itself, signed by Microsoft (the Store is not used); exactly one
    wsl/ubuntu-24.04*.tar.gz             the Linux root file system, imported with `wsl --import`; exactly one.
                                         Canonical's file, placed under a name that starts `ubuntu-24.04.`
    nvidia/<driver>-win11-win10-...exe   the NVIDIA Windows driver (WSL2 uses it). The installer does not run it:
                                         it stops and names this folder when the driver does not answer
  linux/
    debs/                                Docker Engine, compose plugin, nvidia-container-toolkit, nftables, cron,
                                         and their dependencies, for Ubuntu 24.04, installed with `dpkg -i`.
                                         No Linux NVIDIA driver package: the installer refuses the media if one is here
    trialbox-host.tar                    the release's host tree (`python3 -m tools.host_tree pack`): the bootstrap
                                         unpacked to /opt/trialbox; install.sh replaces it from the signed bundle
    trialbox-<version>.tar               the signed bundle of tools/make_bundle.sh (below); exactly one
    trialbox-<version>.tar.sha256
    vendor_ed25519.pub                   also given out of band; the installer shows its sha256 to compare
  measured/
    serving_config.<gpu>.json            the vendor's serving record of each tier's card (tools/tiers.py)
  docs/
    windows-owner.{en,ja,zh-TW}.md       the owner's pages: the set-up day, a normal day, when something is wrong
    desktop-use.{en,ja,zh-TW}.md         what a desktop user may run on this PC, and may not
    WINDOWS-INSTALL-CHECKLIST.md         the set-up, line by line; WINDOWS-BACKUP-RESTORE.md; the P-0 sheet
    network-sheet.{en,ja,zh-TW}.html     docs/handover/, printed for the hospital's IT (added by the release's steps)
    RUNBOOK.pdf                          (added by the release's steps)
```

**Making the media** (NEW-WIN-9, D-605, D-609). Three steps, on a Linux machine that may go online (Debian or
Ubuntu, with `apt-get` and `gpg`); nothing is fetched into the repository.

1. **Fetch what others publish** into a folder of your own, and check each against its publisher's checksum:
   - the Ubuntu 24.04 WSL image, from Canonical: `ubuntu-noble-wsl-amd64-24.04lts.rootfs.tar.gz` and `SHA256SUMS`
     at `https://cloud-images.ubuntu.com/wsl/releases/24.04/current/` (`sha256sum -c --ignore-missing SHA256SUMS`);
   - WSL itself, from Microsoft: `wsl.<version>.x64.msi` from the releases of `github.com/microsoft/WSL` (the
     installer checks Microsoft's signature on it before it runs it);
   - the NVIDIA driver for Windows for the workstation's card, from NVIDIA (the version the serving record names).
2. **Work out and fetch the Ubuntu packages** (`tools/windows_media_debs.py`, D-609): Docker Engine, the compose
   plugin, the NVIDIA Container Toolkit, nftables, cron, and every package they need that the image does not
   already hold. It asks `apt-get` against the image's own package list, in a folder made new for the run and
   with a configuration of its own; this machine's packages and apt settings are not touched. Docker's and
   NVIDIA's repository keys are accepted only with the fingerprints written in the tool. Run it as an ordinary
   user, not as root.
3. **Lay the media out and check it** (`tools/windows_media.py`, which fetches nothing):

```
python3 -m tools.windows_media_debs --rootfs ubuntu-noble-wsl-amd64-24.04lts.rootfs.tar.gz --out debs/
python3 -m tools.windows_media build --out /media/build --version <version> \
    --bundle dist/trialbox-<version>.tar --wsl-msi wsl.<v>.x64.msi \
    --rootfs ubuntu-noble-wsl-amd64-24.04lts.rootfs.tar.gz \
    --debs debs/ --vendor-pub keys/vendor_ed25519.pub --nvidia-driver <driver>.exe --measured deploy/measured
python3 -m tools.windows_media check /media/usb/TRIALBOX-<version>     # again on the disk, after the copy
```

The image is known by what it is, not by its name: a whole archive of Ubuntu 24.04 for amd64, placed on the
media under a name the installer finds. On 2026-11-13 step 2 gave 16 packages, 84 MB, against Canonical's
image of that day.

`build` refuses a wrongly named input, an image that is not Ubuntu 24.04, a Linux NVIDIA driver package among the packages, packages without Docker
Engine or the NVIDIA Container Toolkit, and a folder that already holds files. `check` names the reasons the
installer would stop that can be read without Windows: a file missing, doubled, unlisted, linked or not matching,
a script whose line ends were changed. It does not check Microsoft's signature on the WSL package (step 1 of the
installer does). `SHA256SUMS.sig`, the network sheets and the PDFs under
`docs/` are added by the release's own steps, then `SHA256SUMS` is written again with
`python3 -m tools.windows_media sums <folder>` (`check` fails until it is).

**The media for a bare Ubuntu box** (OPS-006, D-966; the parked Ubuntu form). The same `TRIALBOX-<version>/`
with only its `linux/` half, `measured/` and `docs/`; `linux/` also holds `box-prepare.sh`, and `linux/debs/` the
Linux NVIDIA driver (`nvidia-driver-580-server-open`), python3's yaml and cryptography, and avahi-daemon besides the
Windows set. `tools/linux_media.py` reuses the two tools above:

```
python3 -m tools.linux_media debs --rootfs <the Ubuntu 24.04 server image the box starts from> --out debs/
python3 -m tools.linux_media build --out dist/media --version <version> --bundle dist/trialbox-<version>.tar \
    --debs debs/ --vendor-pub keys/vendor_ed25519.pub --measured deploy/measured      # or: make media-linux
python3 -m tools.linux_media sign dist/media/TRIALBOX-<version> --key <the vendor key, on the signing machine>
python3 -m tools.linux_media check /media/usb/TRIALBOX-<version>                      # again on the disk
```

`sign` writes `SHA256SUMS.sig`, a raw Ed25519 signature `openssl` checks, because a bare Ubuntu has no
python3-cryptography yet. On the box, `sudo bash <media>/linux/box-prepare.sh <media> --pub <the key given out of
band>` checks the system, the key, the signature and every file before it installs anything (RUNBOOK §16).

**The bundle** (`trialbox-<version>.tar`, `tools/make_bundle.sh`, verified by `tools/verify_update.py`; D-125
estimated 30 GB, the sizes below make it nearer 40 GB, so plan a 128 GB disk):

| Kind | What | About |
| --- | --- | --- |
| `image` | `trialbox-py`, `trialbox-jvm` (`docker save`), Postgres, HAPI, vLLM, all digest-pinned | 12 GB |
| `model` | the pair's weights: judge Gemma 4 26B-A4B 4-bit (17 GB), verifier Qwen3.5-9B 4-bit (7.5 GB); bge-m3 (2 GB) | 27 GB, the same files for every tier |
| `ruleset` | approved rulesets (zip), imported with the approval and equivalence gates | < 10 MB |
| `host` | the host tree, `trialbox-host.tar`: the compose files, the host tools (`tools/`, `libs/`, `schemas/`) and the release's configuration (Caddyfile, `db-init`, `egress.py`, `network.sh`, `images.lock`, measured serving records), with its own `HOST-SHA256SUMS` (T-631, D-367) | < 10 MB |
| `other` | wheels of the host tools (`cryptography`, `psycopg`, `pyyaml`) for `python3 -m tools.trialbox` | < 50 MB |

Python wheels the services need are inside the images; nothing is installed from PyPI on site. An update is the
same `linux/trialbox-<version>.tar` on a new disk, applied with `tools/apply_update.sh` (backup first, rollback on
failure; RUNBOOK §5).

**The host tree on the box** (T-631, D-367). Compose files, host tools and configuration come only from the signed
bundle, and an update changes them. The copy of the release on the media is only the bootstrap that runs
`deploy/install.sh` the first time. The installer verifies the bundle, unpacks its host tree and then runs again
from the signed tree. The install folder then looks like this:

```
/opt/trialbox/
  releases/<bundle id>/        the host tree of each installed release, exactly as signed
  releases/.replaced-<time>/   files of the copied bootstrap that the signed tree replaced (kept, never deleted)
  current -> releases/<bundle id>
  tools, libs, schemas, ...    links to current/...
  deploy/                      the site's own files: .env, settings.yaml, secrets/, keys/, updates/, refdata/,
                               models/, site/, ops/, logs/, backups/, image-pins.json, pgbackrest/repo
  deploy/docker-compose.yml    ... and every other release file of deploy/: links to ../current/deploy/...
```

An update unpacks its tree to `releases/<bundle id>` and switches `current` before the restart. The restart and the
health check therefore run the new compose files. Any failure switches `current` back before the services start
again. A changed byte anywhere in the tree on the disk is refused at the signature check, and nothing is staged.
`python3 -m tools.host_tree status` names the current release and checks it against its `HOST-SHA256SUMS`. A box
whose verifier is older than manifest 1.3.0 refuses kind `host`. Install the first such release with
`deploy/install.sh`.

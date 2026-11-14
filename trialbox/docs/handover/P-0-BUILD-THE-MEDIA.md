# P-0, for the owner: from a fresh checkout to a Windows PC running the installer

**Reader:** the box owner, for the P-0 rehearsal.

One page. What you need, the commands in order, and what you do on the Windows PC. The questions P-0 answers are
on the sheet `docs/handover/P-0-windows-rehearsal.md`; this page gets you to its line 1.

**What has been run, and what has not.** Step 1 below (the Ubuntu packages) and step 2 with a stand-in bundle were
run for real on 2026-11-13 on a Linux build machine: 16 packages, 84 MB; a media that passes its check. Stage B's
bundle commands are lane D's, written by reading the rehearsal script; nobody has run them in this form (no
Docker where they were written). Nothing has run on Windows: that is what P-0 is.

## Two stages, the short one first

The two lines that decide the next card are **26a** (does WSL2 start from the boot task with nobody signed in) and
**36a** (which Windows key store that task can open). Neither needs TrialBox's own stack. So:

- **Stage A: a media with a stand-in bundle. No Docker, about half an hour.** The Windows installer goes through
  its steps 1 to 13 for real (Windows checks, BitLocker, WSL2, the Ubuntu image, the 16 packages, the card in a
  container, the boot task, the network rule) and stops at step 14, where the Linux installer refuses a bundle it
  cannot verify. That stop is expected. It answers the sheet's lines 1 to 12, Part 2, Part 3 (24, 25, **26a**,
  27a, 27b, 27d), Part 4 (28 to **36a**, 36b, 36c), Part 6 (45 to 51, 53, 56) and Part 8 (63, 64, 64a, 66).
- **Stage B: a media with a real signed bundle (placeholder models). Needs Docker; hours.** For the lines that
  need the stack up: 13 to 16, 26b, 27, 27c, Part 5 (the console from another PC), 52, 54, 55, 58, 61, 65, 67 to 70.
  **Expect step 14 to stop here too, later**: by reading the Linux installer, a card with no serving record is
  refused unless the install is started as a trial, and the model servers cannot load placeholder files. The
  Linux-side rehearsal (`make rehearse-box`) gets past this with stand-in model servers that the Windows path does
  not have. Record where it stops. Whether P-0 gets a way to finish on a rehearsal PC (a stand-in profile for the
  box installer) is open; it is named to the integrator.

Do Stage A first and send its answers back. Stage B can follow on the same PC: the installer goes on where it
stopped. One thing first, because Stage A left its stand-in key in the box and the installer refuses a media
whose key differs from the one already there (by reading `wsl-setup.sh`, step `host-tree`; not run): in an
administrator PowerShell, `wsl -d TrialBox -u root -- rm /opt/trialbox/deploy/keys/vendor_ed25519.pub`.

## What you need

| | Stage A | Stage B, in addition |
| --- | --- | --- |
| Build machine | Linux, Debian or Ubuntu (Ubuntu 24.04 is what was used), `python3` 3.12, `apt-get`, `gpg`; online; an ordinary user, not root | Docker with compose; the repository's `make venv` |
| Disk on it | 2 GB | about 40 GB (images built and saved; the bundle) |
| Time | 10 minutes plus the downloads (about 650 MB) | hours: image builds, the release gates' first database download, large image pulls |
| USB disk | 4 GB, exFAT or NTFS | 32 GB (images are about 12 GB with the model server's; placeholders are bytes) |
| Windows PC | Windows 11 Pro, Pro for Workstations, Enterprise or Education; an NVIDIA card **with its Windows driver installed**; virtualisation on in the firmware; 500 GB free on a fixed NTFS drive (less: add `-MinFreeGB <what it has>`); nothing on it that you need; a second PC on the same network for Part 5 | the same PC |

## Stage A, commands

From a fresh checkout of `master`, in `trialbox/`:

```
mkdir -p ~/p0/in ~/p0/out && cd ~/p0/in
# 1. what others publish (check Canonical's file against Canonical's list)
curl -fLO https://cloud-images.ubuntu.com/wsl/releases/24.04/current/ubuntu-noble-wsl-amd64-24.04lts.rootfs.tar.gz
curl -fLO https://cloud-images.ubuntu.com/wsl/releases/24.04/current/SHA256SUMS
sha256sum -c --ignore-missing SHA256SUMS
#    WSL itself: download wsl.<version>.x64.msi by hand from the releases page of github.com/microsoft/WSL into ~/p0/in
# 2. the stand-in bundle and key (Stage A only: not a bundle, the installer will say so at step 14)
printf 'P-0 stage A: not a bundle\n' > trialbox-p0a.tar
printf 'P-0 stage A: not a key\n' > vendor_ed25519.pub

cd <your checkout>/trialbox
# 3. the Ubuntu packages, worked out against the image (online; 16 packages, 84 MB on 2026-11-13)
PYTHONPATH=libs:. python3 -m tools.windows_media_debs --rootfs ~/p0/in/ubuntu-noble-wsl-amd64-24.04lts.rootfs.tar.gz --out ~/p0/in/debs
# 4. the media
PYTHONPATH=libs:. python3 -m tools.windows_media build --out ~/p0/out --version p0a \
    --bundle ~/p0/in/trialbox-p0a.tar --wsl-msi ~/p0/in/wsl.<version>.x64.msi \
    --rootfs ~/p0/in/ubuntu-noble-wsl-amd64-24.04lts.rootfs.tar.gz --debs ~/p0/in/debs \
    --vendor-pub ~/p0/in/vendor_ed25519.pub
# 5. copy ~/p0/out/TRIALBOX-p0a to the USB disk, then check the copy ON the disk
PYTHONPATH=libs:. python3 -m tools.windows_media check /path/to/usb/TRIALBOX-p0a
```

The last command must end `ok: nothing here would stop the installer's step 1`. It does not check Microsoft's
signature on the WSL package; the installer does, on Windows.

## Stage B, commands (lane D's; by reading, not run)

In `trialbox/`, on a Linux machine with Docker. They make a signed bundle whose two "models" are placeholder
folders (never a model), then step 4 above is run with that bundle and its real public key.

```
make venv && make images
K=$PWD/dist/p0; mkdir -p $K/models
.venv/bin/python tools/sign_bundle.py keygen --out $K/keys     # once; the .key stays with you, the .pub goes on the media
.venv/bin/python tools/refdata_fetch.py sample --out $K/refdata
for d in gemma-4-26b-a4b-it-4bit qwen3.5-9b-4bit; do mkdir -p $K/models/$d
  printf '{"architectures": ["TrialBoxRehearsalPlaceholder"], "name": "%s"}\n' $d > $K/models/$d/config.json
  printf 'placeholder for %s: not a model\n' $d > $K/models/$d/model.safetensors; done
printf 'TB_TZ=Asia/Taipei\n' > $K/.env
IMGS="trialbox-py:1.0.0 trialbox-jvm:1.0.0 trialbox-postgres:16-1 $(docker compose --project-directory $K -f deploy/docker-compose.yml config --images | sort -u | grep -v '^trialbox-' | tr '\n' ' ')"
for i in $IMGS; do docker image inspect $i >/dev/null 2>&1 || docker pull -q $i; done
make release-bundle SC_LOCAL_IMAGES=1 SC_IMAGES="$IMGS" BUNDLE_ARGS="--key $K/keys/vendor_ed25519.key --id 2026.11-p0 --release-seq 1 --out $PWD/dist/trialbox-2026.11-p0.tar --models $K/models --refdata $(ls $K/refdata/trialbox-refdata-*.tar) $(for i in $IMGS; do printf -- '--image %s ' $i; done)"
```

Then step 4 with `--version 2026.11-p0 --bundle dist/trialbox-2026.11-p0.tar --vendor-pub dist/p0/keys/vendor_ed25519.pub`,
and step 5. Lane D's notes: `dist/` is ignored by git, so the checkout stays clean (the bundle script refuses a
checkout that differs from its commit); the release gates need to download a vulnerability database on first run.
Not known: whether the image list above includes the model server's image (it sits behind a compose profile), and
so whether the media is nearer 5 GB or 13 GB.

## On the Windows PC

1. Install the NVIDIA Windows driver first, if the PC does not have it.
2. Decide about BitLocker before you start (the sheet, Part 4, "Choose first"): on a PC that must stay
   unencrypted, start the installer from an administrator PowerShell with
   `<usb>\TRIALBOX-<version>\windows\box-install.ps1 -SkipBitLocker`; otherwise double-click `Install-TrialBox.cmd`.
3. Sign in as the administrator who will own the box, plug in the USB disk, start the installer, and follow the
   sheet line by line. Write the "Record" column down as you go. Never write a recovery key down for us: only
   "shown" and "confirmed".
4. Stage A: when the window stops at step 14 with the Linux installer's message about the bundle, that is the
   expected end (the sheet's line 13). Go on with Part 2, Part 3 (lines 24, 25, 26a, 27a, 27b, 27d), Part 4,
   Part 6 and Part 8 as listed above.
5. Send back: the sheet with its Record column, and the log
   `C:\ProgramData\TrialBox\box-install\box-install.log` (it holds no secret; line 35 checks that).

The PC keeps what the installer did (WSL2 on, a `TrialBox` distribution, BitLocker if you let it, the boot task,
the Windows Update window, shutdown for administrators only). To put a rehearsal PC back: `wsl --unregister
TrialBox`, delete `<drive>\TrialBox`, `Unregister-ScheduledTask TrialBox-WSL2`, and remove the values under
`HKLM\SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate` that the log lists. The installer itself never removes
anything.

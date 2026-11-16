# P-0: the owner starts it; lane W does the rest

**Reader:** the box owner for "Your part" below; lane W for the rest, for the P-0 rehearsal.

**Your part (owner ruling D-510).** Lane W builds the media and reads what P-0 writes down; you only start it.

1. On any Windows PC, with an empty USB disk plugged in (exFAT or NTFS, 4 GB for Stage A, 32 GB for Stage B),
   download the one file `Get-TrialBox-P0.cmd` from the GitHub release lane W names, and double-click it: it fetches
   the media, checks every part and puts it on the disk. Then plug that disk into the P-0 PC (signed in as the
   administrator who will own the box). If that PC has no NVIDIA Windows driver yet, install it first.
2. Double-click `Install-TrialBox-P0.cmd` on the disk and approve Windows' prompt. The window then goes by
   itself: it restarts Windows once if WSL2 needs it and goes on after you sign in again. If BitLocker is on for
   this P-0 (your decision on the integrator's inbox), it shows a recovery key once: keep it as the window says.
   It never needs to be written down for us.
3. When the window says it is done, or has stopped, leave the USB disk plugged in, restart the PC once and do not
   sign in for ten minutes (that start is recorded too, onto the disk), then hand the USB disk back. Everything P-0 asks is in its
   `P0-RECORD` folder (no recovery key and no first-run code are ever written there).

Nothing else on this page is yours: the rest is how lane W builds the media and what the records answer.

**How the media is made (NEW-WIN-13, D-616; owner ruling D-504).** The workflow `TrialBox P-0 media`
(`.github/workflows/trialbox-p0-media.yml`, run by hand) runs `tools/p0_media.sh a` or `b` on a GitHub runner and
attaches the result to a pre-release of this repository: the media as one tar cut into parts under GitHub's 2 GiB
limit, their manifest, `get-p0-media.ps1` and `Get-TrialBox-P0.cmd` (the release's address and the script's sha256
written into it). The release's notes name what the media redistributes and each licence (Microsoft's WSL package,
MIT; Canonical's Ubuntu image; the Ubuntu packages, Docker Engine and the NVIDIA Container Toolkit among them,
Apache-2.0). The commands in "Stage A, commands" and "Stage B, commands" below are what the script runs.

**What has been run, and what has not.** Stage A's commands below were run for real on a Linux build machine, last on
2026-11-15 from a clean checkout of `master` (8a7ad118): a media of 41 files that passes its check. Microsoft's WSL
package was a stand-in there (only Windows checks its signature). Stage B's bundle commands are lane D's, written by
reading the rehearsal script; nobody has run them in this form (no Docker where they were written). Nothing has run
on Windows: that is what P-0 is. The recorder (`windows/p0-record.ps1`, NEW-WIN-12, D-615) is tested with Pester
only.

## Two stages, the short one first

The two lines that decide the next card are **26a** (does WSL2 start from the boot task with nobody signed in) and
**36a** (which Windows key store that task can open). Neither needs TrialBox's own stack. So:

- **Stage A: a media with a stand-in bundle. No Docker, about half an hour.** The Windows installer goes through
  its steps 1 to 13 for real (Windows checks, BitLocker, WSL2, the Ubuntu image, the 16 packages, the card in a
  container, the boot task, the network rule) and stops in step 14. The window then says "The TrialBox installer
  inside WSL2 stopped before the set-up was finished". By reading the Linux installer (not run), the last lines
  above it are most likely its tier check (this PC's card has no measured serving record) or its bundle check
  ("the bundle is not a valid signed TrialBox release; nothing was changed"). That stop is expected; record its
  last lines. Lines 26a and 36a need only steps 1 to 12. It answers the sheet's lines 1 to 12, Part 2, Part 3 (24, 25, **26a**,
  27a, 27b, 27d), Part 4 (28 to **36a**, 36b, 36c), Part 6 (45 to 51, 53, 56) and Part 8 (63, 64, 64a, 66).
- **Stage B: a media with a real signed bundle (placeholder models). Needs Docker; hours.** For the lines that
  need the stack up: 13 to 16, 26b, 27, 27c, Part 5 (the console from another PC), 52, 54, 55, 58, 61, 65, 67 to 70.
  **Today step 14 stops here too**, by reading: a card with no serving record is refused unless the install is
  started as a trial, and the model servers cannot load placeholder files. The Linux installer now has a
  rehearsal profile (`--rehearsal`, D-726: the box is TEST, says "rehearsal box", runs stand-in model servers, and
  takes a bundle built with `make_bundle.sh --rehearsal`). The Windows installer hands it on when started with
  `-Rehearsal` (NEW-WIN-11, D-614): Stage B is started that way, with a bundle built with `--rehearsal` (the
  commands below). By reading, not run.

Stage A comes first and its records come back. Stage B can follow on the same PC: the installer goes on where it
stopped, and replaces Stage A's host tree inside WSL2 by itself (no install has used it, and Stage B's media holds
another release), so Stage B's Linux installer and key are the ones that run.

## What lane W needs to build it

| | Stage A | Stage B, in addition |
| --- | --- | --- |
| Build machine | Linux, Debian or Ubuntu (Ubuntu 24.04 is what was used), `python3` 3.12 or later (3.13 on 2026-11-14), `apt-get`, `gpg`; online; an ordinary user, not root | Docker with compose; the repository's `make venv` |
| Disk on it | 2 GB | about 40 GB (images built and saved; the bundle) |
| Time | 10 minutes plus the downloads (about 650 MB) | hours: image builds, the release gates' first database download, large image pulls |
| USB disk | 4 GB, exFAT or NTFS | 32 GB (images are about 12 GB with the model server's; placeholders are bytes) |
| Windows PC | Windows 10 22H2 (build 19045) or Windows 11, as Pro, Pro for Workstations, Enterprise or Education; an NVIDIA card **with its Windows driver installed**; virtualisation on in the firmware; 500 GB free on a fixed NTFS drive (less: add `-MinFreeGB <what it has>`); a second PC on the same network for Part 5. Your own computer: read "On your own computer" below first | the same PC |

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
make release-bundle SC_LOCAL_IMAGES=1 SC_IMAGES="$IMGS" BUNDLE_ARGS="--rehearsal --key $K/keys/vendor_ed25519.key --id 2026.11-p0 --release-seq 1 --out $PWD/dist/trialbox-2026.11-p0.tar --models $K/models --refdata $(ls $K/refdata/trialbox-refdata-*.tar) $(for i in $IMGS; do printf -- '--image %s ' $i; done)"
```

`--rehearsal` marks the bundle as a rehearsal's (D-726): a site box refuses it, and the Windows installer must be
started with `-Rehearsal` to take it. Then step 4 with `--version 2026.11-p0 --bundle dist/trialbox-2026.11-p0.tar --vendor-pub dist/p0/keys/vendor_ed25519.pub`,
and step 5. Lane D's notes: `dist/` is ignored by git, so the checkout stays clean (the bundle script refuses a
checkout that differs from its commit); the release gates need to download a vulnerability database on first run.
Not known: whether the image list above includes the model server's image (it sits behind a compose profile), and
so whether the media is nearer 5 GB or 13 GB.

## On the Windows PC (what the owner's double-click does)

`Install-TrialBox-P0.cmd` starts `windows\box-install.ps1 -P0` as administrator. With `-P0` the installer:

- takes this P-0's choices from the media's `windows\p0.json`, written at build (`tools.windows_media build --p0`
  with `--rehearsal` for Stage B and `--skip-bitlocker` when the owner decides so); a `p0.json` it cannot read
  stops it before anything changes;
- picks the fixed NTFS drive with the most room when there are several (no `-DataDrive` to type);
- writes a record of what the sheet asks after every run, also a run that stopped, and copies the records to the
  disk's `P0-RECORD` folder; registers the task `TrialBox-P0-Record`, which writes one at each start of Windows six
  minutes in, signed in or not (sheet lines 26a and 79);
- for Stage B after Stage A on the same PC, replaces Stage A's host tree inside WSL2 by itself (`wsl-setup.sh
  host-tree`: a tree no install has used, from another release), so no command is needed between the stages.

Stage A ends with the window's stop in step 14 ("stopped before the set-up was finished"): expected (the sheet's
line 13). The records answer the sheet's lines by section (the sheet, "How lane W reads the records").

## On your own computer

**Windows 10 22H2 can take P-0** (owner ruling D-503; NEW-WIN-10, D-613). The sheet's Part 9 has its own lines:
Windows 10 has no mirrored networking for WSL2, so the console reaches other PCs through a forwarding rule that a
task keeps pointed at WSL2. On the owner's PC (G:, H: and I: have about 2 TB free; C: has 222 GB, too little for a
box) the P-0 installer picks the drive with the most room by itself. An RTX 3080 is enough for Stage A;
it is not a tier's card, so Stage B's install runs as a rehearsal box only.

P-0 can run on the computer you work on. It holds no patient data and needs none: the installer reads only the USB
disk and the one folder it makes (`<data drive>\TrialBox`, which must be new or empty), and it removes nothing.
But some of what it does is for the whole computer, not only for TrialBox. Decide on each before you start:

| What the installer does | For | If you do not want it |
| --- | --- | --- |
| BitLocker on the system drive and the data drive, each recovery key shown once and confirmed | the whole drive | start with `-SkipBitLocker` (the sheet's Part 4, "Choose first"). A drive that is already encrypted is left as it is either way; only its key is asked for |
| Hibernation off, sleep off on mains and battery (current power plan) | the computer | set them back in Settings, Power, after P-0 |
| Windows Update: installs daily at 19:00, restarts only 19:00 to 01:00, no drivers from Windows Update. A policy your IT already set is kept instead | the computer | after P-0, the values under `HKLM\SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate` that the log lists can be removed |
| Only administrators may shut the computer down; the sign-in screen no longer offers it | every account | after P-0, `secpol.msc`, Local Policies, User Rights Assignment, "Shut down the system": put back the accounts the log's line "shutdown right was:" names; Security Options, "Shutdown: Allow system to be shut down without having to log on": Enabled |
| Inbound connections to WSL set to "block", one rule lets the console's port in from your own network | every WSL distribution on the computer, not only TrialBox's | if you use other WSL distributions that others connect to, say so before P-0 |
| `%USERPROFILE%\.wslconfig` with memory, processors, no swap and mirrored networking. A `.wslconfig` you already have is kept as it is (the network lines of Part 5 will then show it) | every WSL distribution of your account | a copy of any earlier file is kept beside it (`.wslconfig.before-trialbox-<time>`) |
| A task `TrialBox-WSL2` that starts TrialBox's WSL system at every boot | the computer | `Unregister-ScheduledTask TrialBox-WSL2` |
| P-0 only: the task `TrialBox-P0-Record` (a record at each start of Windows, six minutes in, into `C:\ProgramData\TrialBox\box-install\P0-RECORD`) | the computer: one short read-only run at each start | `Unregister-ScheduledTask TrialBox-P0-Record` (lane W does it with the rest when the P-0 box is removed) |
| Windows 10 only: a port-proxy rule `0.0.0.0:443` to WSL2, a task `TrialBox-Console-Proxy` that keeps it pointed, and a Windows Firewall rule `TrialBox-Console` (port 443, your own network, private and domain networks) | the computer: nothing else can listen on port 443 | `netsh interface portproxy delete v4tov4 listenport=443 listenaddress=0.0.0.0`; `Unregister-ScheduledTask TrialBox-Console-Proxy`; `Remove-NetFirewallRule -Name TrialBox-Console` |
| Windows 10 only, if it was stopped or started on demand: the IP Helper service (`iphlpsvc`) set to start automatically and started (it is Windows' default) | the computer | `Set-Service iphlpsvc -StartupType Manual` to put it back as it was (the installer's log names what it was) |
| Windows 10 only: `localhostForwarding=false` in `.wslconfig` | every WSL distribution of your account: `localhost` on Windows no longer reaches a program inside WSL | remove the line from `.wslconfig`, then `wsl --shutdown` |
| WSL itself, and a WSL system named `TrialBox` on the data drive | your account | `wsl --unregister TrialBox` deletes it and its disk file, for good |

The undo column is by Microsoft's documentation and has not been run. Do the CGRD first look before P-0, as
agreed: P-0 restarts the computer several times, and Part 6 line 51 keeps it on over an evening's update window.

The PC keeps what the installer did; the table above says how each part is put back. The installer itself never
removes anything.

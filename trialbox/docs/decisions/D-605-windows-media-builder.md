# D-605 The offline media for Windows is built and checked by one tool

- **Task:** NEW-WIN-9, the media part (`docs/plan/33-plan-v7.md` section 2.3; lane W; wave 3)
- **PR:** this branch (`agent/NEW-WIN-9-windows-media`)
- **Date:** 2026-11-13
- **Status:** accepted. The tool and its check run here on stand-in inputs. No media built by it has been read by
  the installer on Windows: that is line 3 of the P-0 sheet
- **Builds on:** D-600 (the installer and the layout it reads), D-125 and D-138 (the offline media), D-367 (the
  host tree), D-603 and D-604 (the files the installer grew since)

## Context

`docs/handover/OFFLINE-MEDIA.md` describes the layout the Windows installer reads, and step 1 of the installer
stops on a media that is not laid out that way. Nothing made such a media. The first run on Windows (P-0) needs
one, and a media laid out by hand from the document is the kind of work that goes wrong in ways the installer
then reports to the wrong person: a second WSL package left in the folder, a script whose line ends a Windows
copy changed, a file added after `SHA256SUMS` was written, a Linux NVIDIA driver among the packages.

NEW-WIN-5 (Windows Update, drivers, power rights) was next in the queue. It was put after this card: it adds more
behaviour that only Windows can show, before the first P-0 result, while P-0 itself cannot start without a media.

## Decision

1. **`tools/windows_media.py build`** lays out `TRIALBOX-<version>/` from this source tree and from files the
   caller names: the signed bundle, the WSL package, the Ubuntu image, the folder of packages for Ubuntu, the
   vendor's public key, and (optional) the NVIDIA driver for Windows. It packs the host tree with
   `tools.host_tree.pack`, writes the launcher with Windows line ends and `wsl-setup.sh` with Unix line ends
   whatever the checkout has, writes `README.txt` and `SHA256SUMS` (forward slashes, every file).
2. **It downloads nothing.** The vendor fetches Microsoft's, Canonical's and NVIDIA's files on a machine that may,
   and names the paths. No Windows package, image or driver is in the repository; a test holds that.
3. **It refuses before it writes**: a missing or wrongly named input (the installer finds files by name), a
   version that is not a plain name, a Linux NVIDIA driver package (the same two expressions as `wsl-setup.sh`;
   a test holds them together), packages without Docker Engine or the NVIDIA Container Toolkit (the installer's
   package step stops without them), a missing installer file in the source tree, an output folder that already
   holds files. What can still fail later (a full disk, a tree that cannot be packed) fails in
   `TRIALBOX-<version>.part`, which is removed: the folder gets its name only after it passed `check`, and the
   build can be run again.
4. **`tools/windows_media.py check <folder>`** reads a media for the reasons the installer would stop that can be
   read without Windows: each file the installer wants exactly once is there exactly once (names matched without
   regard to case, as Windows matches them), every file is listed in `SHA256SUMS` and matches, nothing listed is
   missing, the two packages above are there and no Linux driver package is, the line ends are right, nothing is
   a link. `build` runs `check` on what it made. `sums` writes the list again after the release's steps added a
   file. A test reads the installer's own `Find-TbOne` lines, the files it reads from beside itself and the
   folders of the media it names, and holds the tool to them. That test catches a new file asked for in those
   forms; a need written in another form (a new check inside `wsl-setup.sh`, say) is not caught by it.
5. **What `check` does not look at**: Microsoft's signature on the WSL package (step 1 of the installer checks
   it with Windows' own means, so a media that passes here can still be stopped there), the bundle's own
   signature (`deploy/install.sh`, on the box), whether the packages install. `SHA256SUMS.sig` needs the vendor
   key, which is not on a build machine; the release's signing step adds it, and the installer does not read it
   today.
6. **Where `check` is stricter than the installer**, on purpose: every file must be listed (the installer checks
   those it uses); a listed path must match the file's name in case; `wsl-setup.sh` must have Unix line ends
   (the installer converts them itself); a link is refused.
7. **The host tree on the media is the working tree's**, packed as `tools/make_bundle.sh` packs it. A media is
   built from the checkout the bundle was built from; the tool does not check that (the signed bundle replaces
   the bootstrap tree on the box, D-367). Requiring a clean checkout, or taking the tree out of the bundle, is
   lane D's choice with `make_bundle.sh`.

**Reuse check.** Nothing fits: the layout is the installer's own, and the parts that exist are used (the host
tree by `tools.host_tree`, the bundle by `tools/make_bundle.sh`; sha256 lists in the `sha256sum` format so the
vendor can also check a copy with that tool). An ISO or installer builder (WiX, Inno Setup, `xorriso`) would add
a build dependency for a folder that is copied to a USB disk as it is.

## What is proven here, and what is not

Proven here (`tests/unit/test_windows_media.py`, stand-in inputs): the layout; the refusals; a build that fails
midway; `check` on a damaged, doubled, unlisted, missing or linked file and on names in capitals; the line ends; the tie to the installer's file patterns and to the driver rule
of `wsl-setup.sh`; the command line. The installer's step 1 on a media of this layout is tested in
`tests/windows/box-install.Tests.ps1` with PowerShell 7 on Linux.

Not proven: that a media built by this tool from the real files (about 40 GB) is taken by the installer on
Windows (P-0 line 3); how long the build and the check take at that size; that a copy to an exFAT or NTFS USB
disk keeps every file as written (run `check` on the disk itself after the copy; from Windows, by the vendor's
documentation and not run, `certutil -hashfile` gives the same sha256 for one file).

## Consequences

- The vendor builds a media with one command and checks the copy on the disk with one command.
- For lane D: `tools/make_bundle.sh` and the release target could call `tools.windows_media build` after the
  bundle is signed, so a release always leaves a media folder; not done here (their files).
- The handbook and the rewritten hand-over documents of NEW-WIN-9 are a later card.

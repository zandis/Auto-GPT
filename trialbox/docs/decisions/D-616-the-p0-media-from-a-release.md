# D-616 The P-0 media is built by a workflow and fetched from a GitHub release

- **Task:** NEW-WIN-13 (lane W), on the owner's rulings D-510 (the owner only starts P-0) and D-504 (the media by
  route (a): lane W builds it; this public repository's GitHub runners and releases cost nothing), relayed by the
  integrator on 2026-11-15
- **PR:** this branch (`agent/NEW-WIN-13-p0-media-release`), stacked on NEW-WIN-12 (D-615, #667)
- **Date:** 2026-11-15
- **Status:** accepted. Stage A ran here end to end from the cached inputs; the workflow itself has not run (it runs
  by hand, and a run publishes a release); nothing ran on Windows
- **Builds on:** D-605 (the media), D-614, D-615, D-726

## Context

The owner was to build the media on a Linux machine of his own. Under D-510 and D-504 lane W builds it and he
downloads it. A GitHub release carries files of at most 2 GiB (GitHub's documented limit); Stage A's media is about
450 MB, Stage B's 5 to 13 GB with the images, its bundle alone above the limit. Stage B also needs Docker for hours,
which a GitHub runner has.

## Decision

1. **`tools/windows_media.py parts`** writes a media that passes its own check as one tar (every file, the checksum
   list included) cut into parts of at most 1900 MiB, and a manifest: the name, size and sha256 of each part and of
   the whole.
2. **`tools/p0_media.sh a|b OUT`** builds the release files. It fetches Canonical's Ubuntu 24.04 WSL image (checked
   against Canonical's own list) and Microsoft's WSL package (pinned, 2.6.1.0) unless they are already there, works
   out the Ubuntu packages (`tools.windows_media_debs`), builds the media with `--p0` (Stage B: images, a
   `--rehearsal` bundle signed with a key made for the run, whose private half is removed when the script ends),
   cuts the parts, writes the launcher and `NOTES.md` (what is redistributed, with each licence), and checks that
   the parts join back to the manifest's sha256.
3. **The workflow `TrialBox P-0 media`** (`.github/workflows/trialbox-p0-media.yml`): run by hand only (a run
   publishes); read-only but for its one job's `contents: write`; inputs reach the shell through environment
   variables only; the tag is checked against `^p0-[a-z0-9.-]+$` before anything is built; actions pinned to
   commits; `skip_bitlocker` defaults to true until the owner decides. It makes a pre-release at the commit it built.
4. **`Get-TrialBox-P0.cmd`**, the one file the owner downloads: it fetches `get-p0-media.ps1` from the release and
   runs it only if its sha256 is the one the workflow wrote into the launcher. **`get-p0-media.ps1`** fetches the
   manifest and each part (BITS, so a cut connection resumes; a part already there and right is not fetched again),
   checks each part's size and sha256 (a damaged part is fetched once more, then it stops and removes it), picks the
   USB disk (exFAT or NTFS, since a media file can pass FAT32's 4 GB; with the room; the roomiest of several), never
   writes over a media folder already on it, and unpacks the parts in order into `tar.exe`'s standard input, so the
   joined tar is never written and the disk needs room for the media only. Names in the manifest are names, never
   paths.
5. **Licences.** The release's notes cite Microsoft's WSL package (MIT), Canonical's image and its terms, every Ubuntu
   package by name (each under its own copyright file; Docker Engine and the NVIDIA Container Toolkit, Apache-2.0)
   and, for Stage B, the bundle's per-image SBOM and licence record.

**Reuse check.** `tools.windows_media`, `tools.windows_media_debs`, `tools/make_bundle.sh` (through `make
release-bundle`) and the repository's pinned actions are used as they are; Windows' own BITS and `tar.exe` do the
fetching and unpacking. Not chosen: Actions artifacts (they need a GitHub sign-in to download and expire); a split
zip (Windows cannot open one without another program).

## What is proven here, and what is not

Proven here: Stage A run for real from the cached inputs of 2026-11-13 (one part of 449 MB; the parts unpacked
back into a media that passes its check, `p0.json` as built); Python tests: the parts no bigger than asked and
joining back whole, only a checked media cut, the part size under GitHub's limit, the workflow's rules (dispatch only,
permissions, no input inside a script, the tag checked first, actions pinned), stage A on stand-in inputs (the
release files, the launcher's three marks filled, the notes); Pester: the fetcher's disk choice, a damaged part
fetched once more and then refused, a part already there not fetched again, no disk, an existing media folder kept,
names that could leave the work folder refused, the launcher checking the script before running it.

Not proven: the workflow on GitHub (its first run, by hand, is the proof; Stage B's hours, disk room after the
clean-up, and the gates' first database download are not known); BITS, `tar.exe` from standard input and a real
USB disk on Windows (the fetcher's first run on the owner's PC); that GitHub accepts a 1900 MiB asset from `gh
release create` in one go.

## Consequences

- The owner's part of P-0 starts with one download and a double-click; `P-0-BUILD-THE-MEDIA.md` says so.
- A run of the workflow publishes a pre-release of this public repository: lane W runs it once the integrator says
  the stack of #644, #667 and this card is on `master`.

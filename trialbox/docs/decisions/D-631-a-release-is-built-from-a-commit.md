# D-631 A release bundle is built from a commit, not from a working tree

- **Task:** RELEASE-CLEAN (from lane W's review of #448 by reading, through the integrator, 2026-11-13)
- **PR:** this branch (`agent/RELEASE-CLEAN-a-release-from-a-commit`)
- **Date:** 2026-11-13
- **Status:** accepted
- **Builds on:** D-367 (the host tree rides in the signed bundle), D-340 (`release.json` names the source commit)

## Context

`tools/make_bundle.sh` packs the host tree from the checkout it runs in: every tracked file as it stands on
disk, and every untracked file that is not ignored (`tools/host_tree.py tree_files`). `release.json` names the
commit and a `dirty` flag, but the flag looked at tracked files only and nothing refused on it. So a file
somebody left in `tools/` or `deploy/`, or an edit that was never committed, rode to every box inside a signed
bundle whose record named a commit that does not hold it.

## Decision

1. `tools/make_bundle.sh` refuses to build when the checkout differs from its commit: a changed, staged or
   untracked (not ignored) file anywhere in the project folder, or no git checkout at all. It lists the files
   and builds nothing. The check comes before anything is exported.
2. `--allow-dirty "<reason>"` builds all the same, for a rehearsal or a test: the reason is printed, and
   `release.json` says `dirty: true`. The box rehearsal passes it. A release for a site is built without it.
3. `release.json`'s `dirty` now counts untracked files too, so the record agrees with what was packed.

## Consequences

- A release is reproducible from its commit: the host tree in the bundle is that commit's files.
- Not done here, a finding for the plan: the box does not look at `dirty`. A bundle built with `--allow-dirty`
  and signed with the vendor key installs on a PRODUCTION box like any other. Whether install and update should
  refuse it there is a second card.

# D-1139 The runbook follower follows the bootstrap: what "alone" means after D-996

- **Task:** lane H, card H-24 (the integrator, 2026-11-17 12:39 UTC): the follower of H-22 (D-1136) follows the new §1
  of D-996
- **Date:** 2026-11-17
- **Status:** accepted

## Context

D-1136 defined "install by the runbook alone" for the old §1. There, the one command ran `deploy/install.sh` from
`/opt/trialbox`, and the vendor key had its own step after the start. D-996 (lane D) rewrote §1:

- The one command now runs from the USB stick. It checks a signed bootstrap with `openssl` and runs it; the bootstrap
  unpacks the host tree to `/opt/trialbox` and places the key.
- The reader is told where to put what they bring: the key at `/root/vendor_ed25519.pub`, and the site's folder at
  `/root/site`, given by full path.
- `--mode stub` takes the place of `--tier` on a machine without a GPU.

D-1136's rule stands: only what the runbook tells the reader to bring, placed where it says. Its examples (the key at
step 6, `site.yaml` beside `/opt/trialbox`) no longer match §1.

## Decision

1. **The path.** The hub's convention, step 1's prerequisites, then §1's one command as written (line 32). Then
   step 4 (the mapping check in the release's image), step 6 (the key is checked, not placed: the one command placed
   it) and step 7 (the first ingest and its report, both by `docker compose --project-directory deploy`). The one
   command runs from no particular folder: it starts with `cd /media/usb`.
2. **What the follower may supply**, each recorded:
   - the stick at `/media/usb` with the four files the vendor hands over (the bundle, its `.sha256`, the bootstrap and
     its `.sig`), moved out of the vendor's own folder;
   - the vendor key at `/root/vendor_ed25519.pub`;
   - the site's folder at `/root/site`, with the box rehearsal's synthetic answers and mapping;
   - `sae_office_mailbox` (§1 names it as required);
   - the feed folder at §1's own example, `/srv/his-export`, holding the synthetic export before the one command. The
     rehearsal's value (`./site/feed-a` under `/opt/trialbox`) cannot be there before the one command, because the
     bootstrap refuses a non-empty `/opt/trialbox`;
   - an Enter at a question.
3. **`--mode stub` on a machine without a GPU** is the runbook's own rule now (§1 line 44). The follower applies it
   before the first attempt and records that it did; it is no longer a lift.
4. **`sudo`.** As root (the hub's convention), the follower drops every `sudo` that starts a command of the line, not
   only a leading one. An inner `sudo` resets the environment. On the unit machine that sent the bootstrap to the
   real `/opt/trialbox`; the test now fails if any run touches the real `/opt/trialbox`, `/root/site` or
   `/srv/his-export`.
5. **Machine stops are not verdicts.** A stop because the machine lacks what step 1 names (no TPM), or because the
   unit machine's stand-ins end, is recorded under `machine_stops`. The verdict names the first runbook stop. If
   there is none, the verdict is "no runbook stop before this machine's limit". The lift `no-tpm` stays, of kind
   machine. The lift `sidecar-name` stays as a check of D-996's sidecar; it was not needed. H-22's lifts
   `host-tree`, `vendor-key-first`, `drop-tier`, `python3` and `compose-dir` are gone.
6. **Closed findings.** `findings.json` keeps H-22's findings that D-996 removed under `closed`, with what closed each
   and how the follower sees that. They leave `findings` only because the follower no longer shows them: the text
   checks are false, and the unit and container runs do not show them. A closed finding that shows again is a new
   finding, and the test fails.
7. **The machines.**
   - The unit machine maps `/opt`, `/media`, `/root` and `/srv` into the test's folder. It points the bootstrap at its
     stand-in `/opt/trialbox` with the bootstrap's test knobs.
   - The container machine gets its own `/opt`, `/root/site` and `/srv` as mounts of folders under the work folder.
     The runbook's paths on the Docker host are links to them, because every bind mount the installer starts names a
     host path, and the bootstrap moves a folder into `/opt`, which it cannot do on a mount point. The teardown
     removes the links.

## Consequences

- When D-1066's card lands (`--mode stub` on a PRODUCTION box pins the embedder), the container run shows no
  `stub-production-embedder`, and the test fails until that finding moves to `closed`.
- The follower now needs `openssl` on the machine, as §1's step 1 says.

## Used by

`tools/runbook_install.py`, `tests/unit/test_runbook_install_follow.py`,
`docs/plan/measurements/runbook-install-2026-11-17.md` and its folder.

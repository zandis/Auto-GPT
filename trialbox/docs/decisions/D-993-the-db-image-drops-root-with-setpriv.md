# D-993 the db image drops root with setpriv, not the upstream gosu binary

- **Task:** SC-1b (lane D), part of path 1 of the 2026-12-10 lapse of the image findings; the integrator's yes on #639
- **PR:** this branch (`agent/SC-1b-the-db-image-drops-root-with-setpriv`)
- **Date:** 2026-11-17
- **Status:** accepted
- **Builds on:** D-979 (SC-1, the base digest), D-204 (the db image)

## Context

Train 68's image gate showed what the base move had cleared. 28 of trialbox-postgres's 30 allow-list entries are Go
findings (`stdlib` and `golang-org/x/sys`) in `/usr/local/bin/gosu`. That is the Go binary the upstream
`postgres:16-trixie` image ships so its entrypoint can drop root, and it is still built with Go 1.24.6 on today's
digest. No base digest clears these findings until upstream rebuilds gosu.

## Decision

1. **A shell shim takes gosu's path.** `deploy/docker/db.gosu-setpriv.sh` is copied to `/usr/local/bin/gosu`. The upstream
   entrypoint's `exec gosu postgres "$BASH_SOURCE" "$@"` is unchanged, and the Go binary is no longer in the image. The
   shim runs `setpriv --reuid=<uid> --regid=<gid> --init-groups -- "$@"`, which gives gosu's result: the user's uid, its
   primary group (or the group named), its own supplementary groups only, and nothing kept from root.
2. **Nothing is added.** `setpriv` is util-linux's, and `/usr/bin/setpriv` is already in the base: train 68's SBOM of
   the image lists it. The build fails if `setpriv` is missing or `/usr/local/bin/gosu` is not the script.
3. **The identity is tested at three levels:**
   - the unit tests run the shim for real as root and check the uid, the gid, that no other group is kept and that
     bad calls are refused;
   - the image test (`test_db_image`, TB_INTEGRATION) reads `/proc/1/status` of the db container: postgres, 999 in all
     four uid and gid slots, no group but its own;
   - the box rehearsal's `install` step checks the same on the installed box.
4. **The allow-list.** The 28 entries match nothing once the image is built this way. Their removal is an allow-list
   change: it goes with the train-ready line as an exact diff, and the integrator applies it on the train.

## Test

`tests/unit/test_db_no_gosu.py` (6 tests), the new `test_db_image` check, and the box rehearsal's `install` step.

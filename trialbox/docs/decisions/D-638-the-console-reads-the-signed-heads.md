# D-638 The console reads the signed heads: the anchor folders are mounted read-only

- **Task:** ANCHOR-MOUNT (lane C2's reading of D-562, through the integrator, 2026-11-13)
- **PR:** this branch (`agent/ANCHOR-MOUNT-the-console-reads-the-signed-heads`)
- **Date:** 2026-11-13
- **Status:** accepted
- **Builds on:** D-562 (the night signs the audit head into the anchor folders), D-394 (only the audit writer writes the audit volume)

## Context

The console's audit page verifies the chain against the signed heads of every anchor folder when
`TB_AUDIT_ANCHOR_TARGETS` is set. On an installed box it never is: the anchor folders are host paths the console
does not mount, so compose clears the name for the console (D-562). The page's Verify therefore checks the chain
against itself only; the signed heads are checked by the night and by `tools/audit_verify.py --heads`, not where the
auditor looks.

## Decision

1. **A compose file of the installer's own.** A list of host paths cannot be one line of a compose file.
   `python3 -m tools.trialbox anchors-compose` (`tools/trialbox/anchors.py`) writes
   `deploy/site/compose.anchors.yml` from `TB_AUDIT_ANCHOR_TARGETS` in `deploy/.env`; `deploy/install.sh` runs it
   and adds the file to this start and to `COMPOSE_FILE`, so every later compose command (update, secrets
   rotate) reads it. `deploy/site` is the site's own folder and survives an update. No folder set: no file, and
   an earlier one is taken away.
2. **Read-only, in a place of its own.** Each folder is a bind mount into the **console only**, `read_only: true`,
   at `/anchors/<n>/<the folder's name>`: never over a folder of the image, and the page still shows the folder's
   name. The console gets the name with the paths inside. The shipped compose file still clears the name, so a
   box without the file says "no anchor folder" on the page, not "broken".
3. **A folder that is not there stops the install** with its name. `create_host_path: false`: docker never makes
   an empty folder where the hospital's share should be mounted (the page would then read "no signed heads").
4. **What is refused:** a folder that is not a plain absolute path ('.', '..', a control character). A `$` in a
   name is written so that compose does not read a variable.
5. **Doctor, `anchor_mount`, WARN:** folders are set and the file is missing (a box installed before this
   release), not in `COMPOSE_FILE`, or written for other folders. WARN, not FAIL: the night
   (`trialbox audit-sign`) and `tools/audit_verify.py --heads` still check every head; what is missing is the
   check on the page.

Also in this card, asked by the integrator for `tools/`: when the backup drill's first step (the box ran the whole
path, `e2e_simple`) fails, the drill lists the failing checks of `e2e_simple` with their whole detail, stops, and
says where the work folder is. Before, it kept one bool and went on to wipe the folder.

## What this widens, and what it does not

- The console can now **read** the anchor folders: the signed heads and the public keys in `keys/`. Both are
  public by design (a signed head is a hash, a count, a date and a signature). It cannot write them: the mount is
  read-only, and only the host's `trialbox audit-sign` (root) writes there.
- The page trusts the public keys it finds in the anchor folders' `keys/`, as before this card (D-562 says so on
  the page). The night and doctor trust the box's own key. Not changed here.
- Whatever else lies in a folder the site names is readable by the console. The runbook says to name a folder
  that holds the signed heads only.

## Consequences

- A box installed before this release keeps working and gets the doctor line until `install.sh` runs again.
- Changing the folders means running the installer again (the doctor line says so).
- The console's user must be able to read the folder; a share only root can read shows as "not reachable" on
  the page. Not checked by doctor (it runs as another user): open.
- Not proven here: a start of the real stack with the mount (no docker daemon in this session). The merged file
  was rendered with `docker compose config`: the two mounts are on the console only, read-only.

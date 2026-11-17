# D-1131 The session's egress: the box's own rules applied by the product's script and read back

- **Task:** lane H, card H-13 (SESSION-EGRESS of D-1123 section 7)
- **PR:** this branch (`claude/lane-h-13-live-session`)
- **Date:** 2026-11-17
- **Status:** proposed
- **Builds on:** D-1123 (section 6, "the pasted text leaving the box"), T-604 and D-377 (the egress table)

## Context

The direct bring-up route (GPU hand-over 4.4) never loads the box's egress rules. Only `deploy/install.sh` does,
with `deploy/network.sh apply` (its line 733). So on the GPU VM nothing stopped a box container from opening a
connection out. A session takes pasted text, so it must prove that text cannot leave.

## Decision

1. **The product's script, called as the installer calls it.** Step `55-session-egress` of
   `deploy/gcp/box-install-run.sh` runs `deploy/network.sh apply --env deploy/.env` from the box's tree, as root.
   Nothing of the script is copied or changed. It needs PyYAML and nftables on the host; step 02 of the direct
   route installs both (`d_host_prereq`).
2. **Read back from the kernel.** `deploy/network.sh status` (the live table) goes to `box_vm.py session-egress`
   with the networks `apply` saved in its state file. The check holds only when:
   - the table `inet trialbox_egress` is loaded;
   - every network of the box sits under its "trialbox default deny";
   - no rule lets a box container open a connection out. A `tcp dport ... accept` to an outside address is such a
     rule (a model host, a mail relay, the live registry).

   What the table allows and drops is in `records/session-egress.json`.
3. **Before any link.** A table that would let text out stops the run at 55, before any account or link is made
   (`TB-SESSION-EGRESS`).
4. **Free, before any launch.** `tools/box_run.py session-check` asks the same product code
   (`deploy/egress.py allowlist`) what it would open for the session's environment and the synthetic site's answers
   (no mail relay, ClinicalTrials.gov offline). In VALIDATION it opens nothing. In DEV it opens `openrouter.ai:443`
   to the gateway: the routing table's DEV bake-off endpoint (`models/routing.yaml` `openrouter`, environments
   [DEV]). So a DEV session is refused before any cloud call (D-1132).
5. **After a container restarts.** The table is per network: the default deny covers a restarted container's new
   address. The product's refresh units (`trialbox-egress-refresh.timer`, `trialbox-egress-watch.service`) are not
   installed on the direct route. So a restart gets no new allow; that fails closed. The session needs none.

## Held by

`tests/unit/test_h13_session_egress.py`:

- the read-back against the product's own renderer (`deploy/egress.py render`): the closed table holds;
- a model host, a mail relay or the live registry is text leaving the box;
- a table not loaded, or a network outside it, is refused;
- the step calls the product's script and copies none of it.

`tests/unit/test_h13_session_driver.py` (a DEV launch refused for the egress table's way out). The rehearsal
cases: `session` (applied and read back) and `session-egress` (a table that lets the gateway out: the run stops at
55, no account, no link). Their stand-in `network.sh` renders with the real `deploy/egress.py`.

## Not verified

`deploy/network.sh apply` was not run against a real kernel or Docker here: the rehearsal's stand-in renders the
table and loads nothing. That `nft list table` prints the comments the read-back relies on is nftables' documented
behaviour, not checked on the VM.

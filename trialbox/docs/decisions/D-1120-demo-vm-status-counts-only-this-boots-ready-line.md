# D-1120 The demo VM's status counts only this boot's ready line

- **Task:** lane H, card H-9 (the demo VM's status), on the owner's request after lane G's report of 2026-11-16
  and the integrator's of 2026-11-17
- **PR:** this branch (`claude/lane-h-9-demo-vm-status`)
- **Date:** 2026-11-17
- **Status:** proposed
- **Builds on:** D-1062 (steps mode; unchanged here), D-776 (the one-time links `links` prints)

## Context

`deploy/gcp/demo-vm.sh status` read the serial console and said `boot: DEMO-VM-READY` when the last boot's lines in
it held the marker. The console's buffer outlives a stop and a start. Lane G saw `status` report ready at 23:34 UTC
on 2026-11-16 from the earlier boot's marker while the new boot was still seeding. The integrator saw the reverse on
2026-11-17: a ready VM read as not ready. `status` made one `get-serial-port-output` call without `--start` or
`--port`. Without `--start` the answer begins at the oldest byte the console still holds, and gcloud's own help
says an output too long for one answer is continued with `--start`. So the newest bytes, where the marker is, could
be missing from the one answer read.

## Decision

1. **The boot id.** Each boot (`deploy/gcp/demo-vm-boot.sh`) makes a random id: 8 bytes from `/dev/urandom`, hex.
   It is derived from nothing, so it is not a secret and reveals none. The boot prints it with the time in UTC
   (RFC 3339) on its first line (`hard stop: ... (boot <id> started <time>)`), on a refusal (`(boot <id> at <time>)`)
   and on its marker (`DEMO-VM-READY boot=<id> at=<time>`, the same for `DEMO-VM-NOT-READY`). It also writes the id
   into the codes' object, and `links` prints it (`== boot id: <id>`).
2. **Which marker counts.** `status` reads the instance's `lastStartTimestamp` and weighs the markers in this order:
   1. `status --boot-id <id>`: the markers of that boot only. No clock is read.
   2. Else the boot whose first line is stamped at or after `lastStartTimestamp` is this boot. Only markers with
      its id count, whatever their own stamps say.
   3. Else, when this boot's first line is not in the buffer (not printed yet, or dropped at the buffer's edge), a
      marker stamped at or after `lastStartTimestamp` counts.

   The latest counted marker decides. Times are compared as instants with their offsets, never as text.
3. **Clock skew.** The id is preferred to the clock. If the VM's clock runs ahead, an earlier boot's marker can
   carry a stamp after this start, but it never counts once this boot has printed its first line (rule 2). If the
   clock runs behind by more than the seed's few minutes, a fresh boot reads `not ready yet`. The operator then runs
   `links` and `status --boot-id <id>`. An id passed with `--boot-id` decides alone, so it must be the one `links`
   printed for this start.
4. **What `status` says.** For an earlier boot's marker alone: `boot: not ready yet`, with a note naming that
   boot, its stamp and this start. For a marker with no id and no stamp (an image before this decision):
   `boot: cannot tell: the image prints no boot id; ready line is older format`, never ready. An old image's refusal
   gets the same, with its lines. Without `lastStartTimestamp` and without `--boot-id`: `boot: cannot tell`. For a
   VM that is not `RUNNING`: `boot: the VM is <state>: no ready line is read`, and the serial console is not read.
   The texts of the unchanged cases (ready, not ready, refused, not ready yet) are as before.
5. **The whole buffer.** `status` reads serial port 1 (where the boot's tee and the script runner write) with
   `--start 0 --format=json`, then from each answer's `next`, until an answer is empty or `next` does not move. A
   long buffer is read to its end, and a line cut at a page's edge is whole again. The marker is read wherever it
   stands on its line, so a kernel message written after it on the same line does not hide it. The loop stops at 64
   pages, far past the 1 MB the console keeps. That cap guards against a VM that never stops writing; it does not
   cut a boot's output.
6. **Exit codes.** None is new: `status` exits 0 whatever the boot says, as before. `--boot-id` that is not 16 hex
   digits, or given with any command but `status`, exits 2 before any gcloud call.

## Test

`tests/unit/test_g1_demo_vm.py`, with its gcloud stand-in. The stand-in now answers `--start`, `--format=json`, a
page size and dropped bytes as the API does, and gives `lastStartTimestamp` with a -08:00 offset. The tests cover:

- a stale earlier boot's marker alone (not ready);
- a fresh marker of this boot (ready);
- both boots in the buffer, three orders (this boot's latest decides);
- an old image's bare marker (cannot tell);
- clock skew, ahead and behind, and `--boot-id`;
- instants, not text;
- a VM that is not `RUNNING`;
- the buffer read page by page with a page's edge inside the marker's line (one answer alone never held it);
- this boot's first line dropped at the buffer's edge;
- no `lastStartTimestamp`;
- `--boot-id` checks, the dry run, `links` printing the id;
- the boot printing a new id and an RFC 3339 time on its first line, its refusal and every marker.

## Not reproduced

The integrator's reverse case was not seen on a real VM here (no cloud call). The fix covers what the stand-in can
show: a buffer longer than one answer, a line cut at a page's edge, a marker followed by other text on its line, and
the port given explicitly. Whether the integrator's VM hit one of these is not known. If a ready VM still reads
not ready, `status --boot-id <id from links>` reads that boot's lines without any clock, and the lines it shows say
what the boot printed.

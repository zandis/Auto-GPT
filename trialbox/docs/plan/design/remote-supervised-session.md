# The remote supervised session: design note (SPEC only, no code)

- **Date:** 2026-11-28 (the owner's decision of that day: a design note now, the build after the MVP)
- **Status:** design. Nothing on the box changes. D-1036 and D-967 (no remote session for the pilot) stay in force
  until the build is approved and the site's IT has agreed to it; this note is the shape that revisit starts from.

## What it is

A person at the vendor helps a site with its box while the site's data steward watches, for a set time. The box
starts the connection; nothing can connect to the box.

## The six rules

1. **Box-initiated.** The box opens the session to one named relay endpoint. The relay never starts anything.
2. **Outbound only, no inbound port.** No listener on the box, no new published port, no VPN, no account for the
   vendor on the host. The nftables default-deny for inbound traffic is unchanged. The outbound connection leaves
   through the egress single exit (D-377) and only to the relay's address. That route exists only while a session
   is open.
3. **Off by default.** An install has no session setting, and that means off. Neither the installer nor an update
   switches it on.
4. **Switched on by the site steward for a set time.** In the console, the data steward role (and no other role)
   starts a session. The steward gives a written reason and picks a duration that a site setting caps. They
   confirm with their second factor. The session ends at the end of that time, when the steward ends it, when the
   box restarts, or when the connection drops. A dropped session does not reconnect by itself: the steward starts a
   new one.
5. **Every action audited.** The audit chain records each of these, with the steward, the remote person's name as
   the relay states it, and the time:
   - the start, with its reason, duration and endpoint;
   - each command, with its result and the size of its output;
   - the end, with why it ended.
   Event names follow the existing audit conventions and are chosen at build, with a test.
6. **Supervised.** The steward sees each command and its output in the console as it runs.

## What the remote person can do

They choose from a closed list of commands. There is no general shell. The list starts with the host tool's
read-only commands: status, the doctor, a scrubbed log tail, and the scrubbed support bundle. Every output passes
the same scrub as the support bundle (`tools.bundle_scrub`) before it leaves. No command reads a patient-level
store, shows a chart number, or writes to the box. A command that changes the box (an update, a restart) needs the
steward to confirm it, each time.

## Tests the build must bring (failing first)

- With no setting, the session cannot start, and no route to the relay exists.
- With the session on, no new port listens (checked against the box's listening sockets before and after).
- A role other than the data steward is refused. A session past its time is closed, and a closed session does not
  reopen by itself.
- A command not on the list is refused and audited. Each listed command writes its audit event before its output
  leaves.
- The scrub's refusal fixtures hold for every command's output.

## Open questions (OWNER)

1. The relay: run by the vendor, or by the site's IT? This decides who holds its keys and where its logs live.
2. Should the list ever include a write command (an update run remotely with the steward confirming), or stay
   read-only?
3. The cap on the duration (a site setting): what is the default?

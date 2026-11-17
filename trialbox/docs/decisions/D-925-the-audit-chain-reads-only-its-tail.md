# D-925 The audit chain reads only its tail: a million events a day in linear time

- **Task:** T-697 (F-12 of `docs/reviews/2026-11-11-scale-timeouts.md`), lane B2 · **PR:** `agent/T-697-audit-writer-at-a-million` · **Date:** 2026-11-17 · **Status:** accepted · **Builds on:** D-272, D-394

1. **Repair:** each append read the whole day file to look for a torn last line (`path.read_bytes()`). The repair now reads the file back from its end in steps of 64 KiB (`_line_start`), and copies the torn bytes to their evidence file in steps.
2. **The drain's start:** it read every day file whole for its last journal row. It now reads lines from the end (`lines_backward`) and stops at the first journal row.
3. **Heartbeat:** the drain touches it after each event it writes, not once a batch, so a batch of slow writes does not read as a dead writer to the health check (60 s).
4. **Measured** (1,000 appends at each size, this host):

   | Day file | Append (new) | Append (before) | Peak memory |
   | --- | --- | --- | --- |
   | 0 MB | 1.43 ms | 1.50 ms | 20 MB (before: 251 MB) |
   | 100 MB | 1.59 ms | 61.5 ms | |
   | 230 MB | 1.62 ms | 137.4 ms | |

   A million appends is about 27 minutes of a day's writing, flat. The writer's cap stays 256 MB: it held only just before, and now holds with room.
5. **Tests:** `tests/unit/test_t697_audit_at_scale.py`:
   - an append on a 100 MB day reads no day file whole, and costs what it costs on an empty one;
   - a torn or unreadable last line is cut from the tail;
   - the drain finds its last journal row from the end;
   - `lines_backward` agrees with a whole read;
   - one heartbeat per event.

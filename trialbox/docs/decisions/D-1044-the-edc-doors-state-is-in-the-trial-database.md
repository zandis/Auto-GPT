# D-1044 The EDC door's state is in the trial database: codes, held writes and event ids hold across processes

- **Task:** E-EDCB-2 (the owner's ruling D-1060, relayed by the integrator; second of four cards)
- **PR:** this branch (`agent/E-EDCB-2-edc-door-stores-in-the-db`), stacked on E-EDCB-1
- **Date:** 2026-11-17
- **Status:** proposed (merges on green CI)
- **Builds on:** D-1042, D-1043, D-1033, D-126 (the console's stores in the trial database)

## The problem

#813 kept three things where only one process could see them:
- the OIDC codes, in a dictionary;
- the writes held for a confirmation, in a dictionary;
- the ids of the EDC's events, in a JSON file under `TB_EDC_EVENT_DIR`, or the system's temp folder when that was not
  set.

So a second console process, or a restart, could take a code twice, lose a held write, or read a repeated event
again. The file was read and rewritten whole on every event.

## Decision

1. **Schema `edcdoor`** (`services/edc_backend/store.py`, one migration) holds the three in the trial database. Its
   tables:
   - `oidc_code`: the code's sha256 as key, the account, the client id and redirect it was issued for, and when it
     expires. A code is good for 120 seconds.
   - `proposal`: the actor, the tool, the EDC's project and record ids, and when it expires. A held write waits 15
     minutes.
   - `event`: the event id as primary key, its type, the EDC's project and record ids, the instrument, and when it
     occurred and was received.
2. **Single use is the database's.**
   - A code is redeemed and a held write confirmed by one `DELETE ... RETURNING`, whichever process asks first.
   - A held write is only for the person who held it.
   - Expired rows are refused, and swept when the table is next written.
   - `oidc.issue_code(username)` and `oidc.take_code(code)` keep their signatures. `issue_code` also records the
     client and the redirect it was issued for; E-EDCB-3 checks them at `/token`.
   - `tools.Proposals` keeps `hold`, `ids` and `take`.
3. **An event is taken in once, and only when its re-read finished.**
   - The insert of the id (`ON CONFLICT DO NOTHING`) and the re-read run in one transaction, and the route answers
     200 only after the commit.
   - A repeated id answers 200 with `"fresh": false` and reads nothing. That includes two deliveries racing: the
     second insert waits on the first's key.
   - A read that fails rolls the id back and answers 503, so the EDC's next delivery is taken in.
4. **No storage is 503.** With no trial database configured, or one that cannot be opened, every route that needs
   the state answers 503: the events, the tool proposal and its confirmation, `/admin/edc`, and the OIDC authorize
   and token routes. The temp-folder fallback is removed. `TB_EDC_EVENT_DIR` now holds only the study map.
5. **No patient data.** No column holds a field value or a name.
   - `oidc_code`'s account is a staff account (erasure: staff; record inventory O-01).
   - `proposal` and `event` hold the EDC's project and record ids. Erasure keeps them as part of the trial record
     (OD-8). Record inventory: the new row O-14.
6. `docs/data/13` describes the event route on these terms, and says it is for the owner's EDC only, not a REDCap
   Data Entry Trigger receiver (D-1033).

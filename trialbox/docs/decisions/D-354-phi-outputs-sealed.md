# D-354 Uploads and outputs sealed at rest under an object key wrapped by the KEK

- **Task:** T-210c (wave 2 of TB-PLAN-06, `docs/plan/28-master-plan-v6.md` §6.2.5)
- **PR:** this branch (`agent/T-210c-phi-outputs-kek`)
- **Date:** 2026-11-11
- **Status:** accepted
- **Closes:** CR-041 (last third: `phi` outputs and uploads in clear); T-210 acceptance 3 of TB-ASSESS-01 (no
  plaintext `phi` file on disk after a run)

## Context

D-347 put the site keys under a KEK. The patient data the jobs write was still plain on the objects volume: the
mailed or console-uploaded charts and protocols (`attachments/`), the `phi` spreadsheets, sheets and records
(`outputs/`), and the TWPAS bundles (`twpas/`). Whoever copies the volume reads them.

## Decision

1. **Where.** Encryption sits in the object store (`libs/tb_common/objstore.py`), the one writer and reader of those
   files, so every writer (orchestrator `publish`, mail intake, console uploads, the compiler, review parsing) and
   every reader (mail attachments, console downloads, the parser) is covered without a change at each call site.
2. **What.** Every object of the buckets `attachments`, `outputs` and `twpas` is sealed, not only the ones tagged
   `phi`: the store does not know the tag, and an aggregate output encrypted too costs nothing. `rulesets` and `lake`
   stay plain (public criteria; the lake is T-206's).
3. **Format.** `TBSEAL1\0` + 12-byte nonce + AES-256-GCM. The associated data binds the object key
   (`<bucket>/<path>`), so a file moved to another key or changed is refused. The temporary file of a write holds the
   sealed bytes, never plaintext.
4. **The key.** `objects.key` (32 random bytes) lives in the secrets folder only wrapped under the KEK
   (`objects.key.wrapped`, D-347 format); a plain copy is refused. It is in `kek.PROTECTED`, so `custody`, `doctor`
   (`key_custody`), `wrap` and `rotate-kek` handle it; `custody` lists it only once it exists.
5. **The seal file.** `python -m tools.keys seal-objects` makes the key, writes `<objects>/.sealed.json` (format,
   the key's fingerprint, the buckets) and then converts every plain object in place, each checked before the
   rename. The seal file is on the shared volume, so every service sees it: with it present a service that cannot
   open the key (no secrets folder, KEK not unsealed, another key) refuses to write or read. Without it the store
   stays plain (demo, tests, boxes before T-210c). `seal-objects --check` exits 1 when the store is not sealed or a
   file is still plain. Services never make the key.
6. **Reads.** Sealed and plain objects are told apart by the magic, so objects from before the seal still read until
   `seal-objects` converts them.

## Consequences

- Every service that touches the objects volume (orchestrator, mail gateway, console, doc parser, criteria compiler)
  needs the secrets folder and the unsealed KEK once a store is sealed. The compose wiring of both into those
  containers is not in this change (D-347 left it too); until it lands a box is sealed only where they are wired.
- The backup format does not change: sealed objects are backed up as they are and need the KEK and `objects.key`.
- Rotating `objects.key` (re-sealing every object) has no command yet.

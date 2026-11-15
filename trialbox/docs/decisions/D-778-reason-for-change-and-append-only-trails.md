# D-778 A saved value changes only with a reason; the trails of steps, acknowledgements and calls are append-only

- **Task:** NEW-LIFE-9 / LIFE-011 (D-364 said it was not closed); the code-complete sprint, item 2 · **Date:** 2026-11-15
- **Reason for change:** a form save that changes a value already saved is refused field by field (`reason`) until a reason is given (console entry page, its API twin, the data core's `PUT`/`POST` routes); the reason is kept in `history.reason` and in the chain's `data.entry` event, which also names each changed field with the sha256 of its old and new value (never the values). A first entry needs none.
- **Undo:** a lifecycle step is undone only with a reason (`life.why.undo_reason`), kept as the new step's note and in the chain's `life.step` event; the console's undo form asks for it (`required`).
- **Append-only:** `subject_step`, `ae_ack` and `deviation_call` join `history` under EDC-009's triggers (D-582): `UPDATE` and `DELETE` are refused and the service role may only insert. No code path changed these rows.
- **Held by:** `tests/console/test_reason_for_change_and_append_only_trails.py`; pinned tests that changed a saved value or undid a step without a reason now give one (`test_entry_pages`, `test_datacore_capture`, `test_lifecycle`, `test_close_only_an_empty_study`), a deliberate change.

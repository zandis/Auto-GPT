# D-922 A run whose answer says it ended has given back the run gate

- **Task:** NEW-B-56 (train 62's red, `test_adapter_run_process.py`), lane B2 · **PR:** `agent/NEW-B-56-adapter-failed-run-releases-first` · **Date:** 2026-11-16 · **Status:** accepted · **Builds on:** D-663, T-723

1. The adapter's run thread wrote the run's end ("failed", "done", "refused") into the answer `GET /run/<id>` reads, and only then gave back the run gate (`_running`). A caller that read "failed" and posted the next night at once could meet a 409 with no run id.
2. The end is now made in a copy and shown only after the gate is given back. This holds in both run modes (`process`, `thread`) and for a steward's publish (`/publish`), whose steps are still shown as they go.
3. So an answer that says a run ended always means a new run is accepted. No caller waits, retries or sleeps for it.
4. The record on disk is written as before (the run's process, or the thread's last write); only the order of the in-memory answer against the gate changes.
5. Tests: `tests/unit/test_adapter_run_process.py`. A gate that records the answers at its release reads "running" in both modes; it read "failed" on the parent. Each POST that must start a run asserts 202 and shows the body when it does not.

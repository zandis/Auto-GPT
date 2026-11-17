# D-879 An account notice leaves the box (NOTICE-ACCOUNT)

- **Task:** a defect found while planning T-715 refuse mode for the notices, lane C2. D-719 tells an account's holder and its PIs when someone else set a factor of the account; the console sends it as a notice of kind `ACCOUNT`, which the orchestrator's `POST /notices` refused (422: only N1, N2, BG and HEALTH), so no account notice ever left the box and the console's best effort recorded each as not sent. · **Date:** 2026-11-17
- **Decision:** the orchestrator accepts the kind `ACCOUNT`. Like every notice it is an aggregate mail to hospital addresses only (an outside address is refused, 400), sent once per recipients, subject and day, and audited `notice.sent`; an unknown kind is still refused.
- **Left:** the notices move to refuse mode (T-715) on the integrator's answer about their service principals.
- **Held by:** `tests/unit/test_an_account_notice_leaves_the_box.py` (a real orchestrator in PRODUCTION with per-service tokens and the console's signed header; failing output on the previous code kept: `notice-fail.txt`).

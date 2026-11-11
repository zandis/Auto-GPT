# 9. Privacy documents and the incident plan

*T-318, D-411. Closes OPS-041 and the incident-plan part of CR-096; the filing part of REG-007 and REG-009.*

For the hospital's privacy office. Each document is a draft per site; the hospital keeps its own filled copy, and a
copy that names people never comes back to this repository.

| Document | File |
| --- | --- |
| Incident plan: severity S1 to S4, roles, the notification clocks, the six cases, the first-hour list, templates in ja and zh-TW, the tabletop script | `docs/plan/sites/incident-response.md` |
| Record of processing (classes D0 to D4, stores, who reads what, retention) | `docs/plan/sites/privacy/record-of-processing.md` |
| Data-protection impact assessment | `docs/plan/sites/privacy/dpia.md` |
| Legal-basis memo: an empty slot, filed once counsel signs (D-311 B26) | `docs/plan/sites/privacy/legal-basis-memo.md` |
| IRB pack: protocol text, data-flow figure, questions, screening-log columns | `docs/plan/sites/privacy/irb-pack.md` |
| Opt-out notice for the full scope, ja and zh-TW | `docs/plan/sites/privacy/opt-out-notice.md` |
| The one-pager, rendered from the site's settings | `python -m tools.onepager --settings deploy/settings.yaml --lang ja` |
| APPI and PDPA mapping | `docs/plan/sites/privacy/appi-pdpa-mapping.md` |
| Data destruction (NIST SP 800-88) | `docs/plan/sites/privacy/data-destruction.md` |

The index of all of them is `docs/plan/sites/privacy/index.md`. Tests: `tests/unit/test_privacy_docs.py` and
`tests/unit/test_onepager.py`.

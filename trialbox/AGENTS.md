# Notes for coding assistants

Before changing the EDC connection, read
[docs/data/14-edc-integration-handoff.md](docs/data/14-edc-integration-handoff.md). It says what
`chang-fu-kuo/trialbox-edc` already provides, which parts of `services/edc_backend/` already match, and the one
gap still open (authorization codes kept only in memory). The connector itself is
[docs/data/13-redcap-and-the-edc-backend.md](docs/data/13-redcap-and-the-edc-backend.md). Leave the demo unchanged
when `TB_EDC_BACKEND` is unset.

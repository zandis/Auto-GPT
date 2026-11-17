# Notes for coding assistants

Before changing the EDC connection, read
[docs/data/14-edc-integration-handoff.md](docs/data/14-edc-integration-handoff.md). It says what the owner's EDC
(`trialbox-edc`) provides and which parts of `services/edc_backend/` match it. The connector itself is
[docs/data/13-redcap-and-the-edc-backend.md](docs/data/13-redcap-and-the-edc-backend.md). Leave the demo unchanged
when `TB_EDC_BACKEND` is unset.

The firewall (D-1060): the connector is written only from what is in this repository and the EDC behaviour its tests
and fixtures record. Never read, clone, write to or comment on the EDC's repository; send a question about it to the
integrator.

#!/bin/sh
# TrialBox container egress allowlist (SPEC §2, §10.1): default deny for every TrialBox container network, allow only
# mail-gateway -> SMTP/IMAP, criteria-compiler -> cloud LLM (when set) / ClinicalTrials.gov (TB_CTGOV_MODE=live),
# orchestrator -> NHI TWPAS (when set). Rendered by deploy/egress.py (python3 standard library) into nftables.
#
#   deploy/network.sh print|apply|flush|status [--env deploy/.env] [--project trialbox]
#
# Run `apply` after `docker compose up` and after any container restart (addresses change); a systemd path/timer
# unit for this is in docs/RUNBOOK.md.
set -eu
exec python3 "$(dirname "$0")/egress.py" "$@"

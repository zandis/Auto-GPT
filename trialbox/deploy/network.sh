#!/bin/sh
# TrialBox container egress allowlist (SPEC §2, §10.1): default deny for every TrialBox container network, allow only
# mail-gateway -> SMTP/IMAP, criteria-compiler -> cloud LLM (when set) / ClinicalTrials.gov (TB_CTGOV_MODE=live),
# orchestrator -> NHI TWPAS (when set). Rendered by deploy/egress.py (python3 standard library) into nftables.
#
#   deploy/network.sh print|apply|flush|status|save|restore [--env deploy/.env] [--project trialbox] [--state FILE]
#
# `apply` loads the table for the running stack and writes the state file (default
# /var/lib/trialbox/egress-state.json); `restore` loads the closed table from it with no allow rule. The systemd units
# in deploy/systemd (D-377, enabled by install.sh) run `restore` at boot before Docker, `apply` after the stack is up,
# and `apply --if-changed` every two minutes, since a restarted container gets a new address.
set -eu
exec python3 "$(dirname "$0")/egress.py" "$@"

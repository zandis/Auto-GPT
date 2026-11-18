#!/bin/sh
# GPU profile from the machine and the card name (D-95, D-124), shared by install.sh and its tests.
#
#   sh deploy/gpu_profile.sh                      # this machine: uname -m and nvidia-smi's first card
#   sh deploy/gpu_profile.sh <arch> "<card name>" [<MIG mode>]  # for a given machine (tests)
#
# Prints one word:
#   shared-quota  a card with MIG enabled (CGMH's shared B200, the owner's B200): the judge and the verifier each
#               on its own MIG instance (two instances, D-211, D-409), serving values from the record measured on
#               those instances. install.sh refuses it: a shared host runs deploy/platform (Kubernetes) or
#               docker-compose.shared-quota.yml
#   b200-no-mig   a B200 (or GB200) with MIG off: TrialBox serves on a B200 only as two MIG instances, never on the
#               whole card or a time-slice (LLM-011, LLM-027); install.sh refuses it and says to enable MIG
#   rtxpro6000  RTX PRO 6000 (96 GB): judge and verifier both resident, 32k context, no swap
#   gb10        DGX Spark class (aarch64, 128 GB unified): the same pair resident, 16k context. An aarch64 host whose
#               card name is unreadable stays gb10, as before
#   arm64-dgpu  UNMEASURED: an aarch64 host with a discrete card that is not a GB10 (an IGX Orin developer kit with an
#               RTX A6000, root review 24): no profile, no compose overlay, no serving record; install.sh and the
#               one-command PoC refuse it in GPU mode. Its stub mode (no model) is unaffected
#   rtx5090     one 32 GB card (RTX 5090, RTX PRO 4500): the same pair with the sleep swap, 8k context
#   rtx4090     a 24 GB card: the judge alone, note answers never exclude
#   default     any other card: the base llm-service only
# The RTX PRO 6000 is matched before the 32 GB cards: its name also contains "RTX PRO". MIG is read first: with MIG
# on, nvidia-smi reports the parent card's name.
set -eu
if [ $# -ge 2 ]; then
  arch="$1"; name="$2"; mig="${3:-}"
else
  arch="$(uname -m)"
  name="$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -1 || true)"
  mig="$(nvidia-smi --query-gpu=mig.mode.current --format=csv,noheader 2>/dev/null | head -1 || true)"
fi
case "$mig" in
  Enabled|enabled) echo shared-quota; exit 0 ;;
esac
case "$arch:$name" in
  *B200*)                   echo b200-no-mig ;;   # before the arm64 rule: a GB200 is arm64 and not a GB10
  aarch64:|arm64:|aarch64:*GB10*|arm64:*GB10*)  echo gb10 ;;
  aarch64:*|arm64:*)        echo arm64-dgpu ;;   # before the name rules: no x86 profile's record holds on Arm
  *"RTX PRO 6000"*)         echo rtxpro6000 ;;
  *5090*|*"RTX PRO 4500"*)  echo rtx5090 ;;
  *4090*|*3090*)            echo rtx4090 ;;
  *)                        echo default ;;
esac

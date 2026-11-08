#!/bin/sh
# GPU profile from the machine and the card name (D-95, D-124), shared by install.sh and its tests.
#
#   sh deploy/gpu_profile.sh                      # this machine: uname -m and nvidia-smi's first card
#   sh deploy/gpu_profile.sh <arch> "<card name>" # for a given machine (tests)
#
# Prints one word:
#   rtxpro6000  RTX PRO 6000 (96 GB): judge and verifier both resident, 32k context, no swap
#   gb10        DGX Spark class (aarch64, 128 GB unified): the same pair resident, 16k context
#   rtx5090     one 32 GB card (RTX 5090, RTX PRO 4500): the same pair with the sleep swap, 8k context
#   rtx4090     a 24 GB card: the judge alone, note answers never exclude
#   default     any other card: the base llm-service only
# The RTX PRO 6000 is matched before the 32 GB cards: its name also contains "RTX PRO".
set -eu
if [ $# -ge 2 ]; then
  arch="$1"; name="$2"
else
  arch="$(uname -m)"
  name="$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -1 || true)"
fi
case "$arch:$name" in
  aarch64:*|arm64:*)        echo gb10 ;;
  *"RTX PRO 6000"*)         echo rtxpro6000 ;;
  *5090*|*"RTX PRO 4500"*)  echo rtx5090 ;;
  *4090*|*3090*)            echo rtx4090 ;;
  *)                        echo default ;;
esac

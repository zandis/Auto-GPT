#!/bin/sh
# GPU profile from the machine and the card name (D-95, D-124), shared by install.sh and its tests.
#
#   sh deploy/gpu_profile.sh                      # this machine: uname -m and nvidia-smi's first card
#   sh deploy/gpu_profile.sh <arch> "<card name>" [<MIG mode>] [<MemTotal kB>]  # for a given machine (tests)
#   sh deploy/gpu_profile.sh memory-class [<MemTotal kB>]  # gb10 or gb10-64 for this host's memory (or the one given)
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
#               card name is unreadable (empty, "[N/A]", "Unknown", or nvidia-smi's error text) stays gb10, as before
#   gb10-64     REFUSED (card 10E-5, D-1335): that same host with MemTotal under 96 GiB, the 64 GB Spark class. The
#               128 GB profile's caps do not fit it and nothing of this class is measured, so it has no profile, no
#               overlay and no record; install.sh, the one-command PoC, the tier check and the box plan refuse its GPU
#               mode. The memory is /proc/meminfo's MemTotal in kB, compared in kB (no rounding). Unknown memory (a
#               given machine with no fourth argument, an unreadable meminfo) stays gb10, as before
#   arm64-dgpu  UNMEASURED: an aarch64 host with a discrete card that is not a GB10 (an IGX Orin developer kit with an
#               RTX A6000, root review 24): no profile, no compose overlay, no serving record; install.sh and the
#               one-command PoC refuse it in GPU mode. Its stub mode (no model) is unaffected
#   rtx5090     one 32 GB card (RTX 5090, RTX PRO 4500): the same pair with the sleep swap, 8k context
#   rtx4090     a 24 GB card: the judge alone, note answers never exclude
#   default     any other card: the base llm-service only
# The RTX PRO 6000 is matched before the 32 GB cards: its name also contains "RTX PRO". MIG is read first: with MIG
# on, nvidia-smi reports the parent card's name.
set -eu
SMALL_KIB=100663296   # 96 GiB in kB: below it a GB10 host is the 64 GB class (the 128 GB Spark reports far above)
host_kib() { awk '/^MemTotal:/ {print $2; exit}' /proc/meminfo 2>/dev/null || true; }
# the class of a GB10 host by its memory; an empty or non-numeric figure is unknown and stays gb10
memory_class() {
  case "$1" in ''|*[!0-9]*) echo gb10; return ;; esac
  if [ "$1" -lt "$SMALL_KIB" ]; then echo gb10-64; else echo gb10; fi
}
if [ "${1:-}" = memory-class ]; then
  if [ $# -ge 2 ] && [ -n "$2" ]; then memory_class "$2"; else memory_class "$(host_kib)"; fi
  exit 0
fi
if [ $# -ge 2 ]; then
  arch="$1"; name="$2"; mig="${3:-}"; kib="${4:-}"
else
  arch="$(uname -m)"
  name="$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -1 || true)"
  mig="$(nvidia-smi --query-gpu=mig.mode.current --format=csv,noheader 2>/dev/null | head -1 || true)"
  kib="$(host_kib)"
fi
case "$mig" in
  Enabled|enabled) echo shared-quota; exit 0 ;;
esac
# an unreadable name is no name: nvidia-smi's placeholders and its error text on stdout (review 24)
case "$name" in
  *"[N/A]"*|*"[Unknown"*|Unknown|*"NVIDIA-SMI has failed"*|*"No devices were found"*) name="" ;;
esac
case "$arch:$name" in
  *B200*)                   echo b200-no-mig ;;   # before the arm64 rule: a GB200 is arm64 and not a GB10
  aarch64:|arm64:|aarch64:*GB10*|arm64:*GB10*)  memory_class "$kib" ;;
  aarch64:*|arm64:*)        echo arm64-dgpu ;;   # before the name rules: no x86 profile's record holds on Arm
  *"RTX PRO 6000"*)         echo rtxpro6000 ;;
  *5090*|*"RTX PRO 4500"*)  echo rtx5090 ;;
  *4090*|*3090*)            echo rtx4090 ;;
  *)                        echo default ;;
esac

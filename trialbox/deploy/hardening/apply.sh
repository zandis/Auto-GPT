#!/bin/sh
# The host baseline (T-634, D-408; OPS-052): the input firewall and SSH. Run as root on the box; install.sh runs it.
#
#   deploy/hardening/apply.sh [--conf deploy/site/hardening.conf] [--dry-run] [--ssh-off-over-ssh] [all|firewall|ssh|render]
#
# firewall: the nftables table inet trialbox_input, written to /etc/trialbox/input.nft and loaded at every boot by
#   trialbox-input.service (before the network). Input policy drop: loopback, replies, ICMP that IP needs, DHCP
#   replies, and the Docker bridges are let in; 443 only from CLINIC_RANGES; 22 only from IT_RANGES when SSH=it;
#   with MDNS=on (a box named <name>.local, OPS-005) mDNS, UDP 5353, from CLINIC_RANGES only.
#   Port 443 is published by Docker, so it never reaches the input hook: a prerouting chain (before Docker's DNAT)
#   drops 443 to this host from any other source. Forwarded container traffic stays the egress table's (network.sh).
# ssh: SSH=off stops and disables the service; SSH=it writes /etc/ssh/sshd_config.d/50-trialbox.conf (keys only, no
#   root, no forwarding), checks it with `sshd -t` and reloads.
#   H-70: SSH=off run from an SSH session would lock that session out. apply.sh then refuses and changes nothing,
#   unless --ssh-off-over-ssh (or TB_SSH_OFF_OVER_SSH=yes in the environment, for install.sh) says to go ahead.
# render: print the firewall ruleset and change nothing.
# deploy/check_host.sh checks both. Nothing here touches the egress table, the disk or the keys.
set -eu
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
. "$HERE/lib.sh"
CONF="$ROOT/deploy/site/hardening.conf"; WHAT=all
while [ $# -gt 0 ]; do
  case "$1" in
    --conf) CONF="$2"; shift ;;
    --dry-run) DRY=1 ;;
    --ssh-off-over-ssh) OVER_SSH=yes ;;
    all|firewall|ssh|render) WHAT="$1" ;;
    -h|--help) sed -n 2,18p "$0"; exit 0 ;;
    *) echo "apply.sh: unknown option $1" >&2; exit 2 ;;
  esac
  shift
done
CLINIC_RANGES=""; IT_RANGES=""; SSH=off; MDNS=off
hb_load_conf "$CONF"

# H-70: is this run inside an SSH session? sudo drops SSH_CONNECTION and SSH_TTY, so the parent chain is walked too
# (an sshd process above this one). It reads $HR/proc: the tests stand a process tree in under TB_HOST_ROOT.
on_ssh() {
  [ -n "${SSH_CONNECTION:-}${SSH_TTY:-}" ] && return 0
  pid=self; n=0
  while [ "$n" -lt 64 ] && [ -r "$HR/proc/$pid/status" ]; do
    name=$(sed -n 's/^Name:[[:space:]]*//p' "$HR/proc/$pid/status")
    case "$name" in sshd|sshd-*) return 0 ;; esac
    pid=$(sed -n 's/^PPid:[[:space:]]*//p' "$HR/proc/$pid/status")
    case "$pid" in ''|0|*[!0-9]*) return 1 ;; esac
    n=$((n + 1))
  done
  return 1
}
if [ "$SSH" = off ] && [ "$WHAT" != render ] && [ "${OVER_SSH:-${TB_SSH_OFF_OVER_SSH:-}}" != yes ] && on_ssh; then
  hb_die "SSH=off would stop sshd and close port 22 under this SSH session, locking it out; nothing was changed. Run it from the box's console, or add --ssh-off-over-ssh (install.sh: TB_SSH_OFF_OVER_SSH=yes) to do it anyway"
fi

# a range is digits, dots, colons, hex and one slash: anything else is refused before it reaches nft
check_ranges() {
  for r in $2; do
    case "$r" in
      *[!0-9A-Fa-f.:/]*|"") hb_die "$1: '$r' is not an address range" ;;
    esac
  done
}
v4() { for r in $1; do case "$r" in *:*) ;; *) printf '%s, ' "$r" ;; esac; done | sed 's/, $//'; }
v6() { for r in $1; do case "$r" in *:*) printf '%s, ' "$r" ;; esac; done | sed 's/, $//'; }

render() {
  [ -n "$CLINIC_RANGES" ] || hb_die "CLINIC_RANGES is empty in $CONF: 443 would answer nobody"
  check_ranges CLINIC_RANGES "$CLINIC_RANGES"
  case "$SSH" in
    off) ;;
    it) [ -n "$IT_RANGES" ] || hb_die "SSH=it needs IT_RANGES"; check_ranges IT_RANGES "$IT_RANGES" ;;
    *) hb_die "SSH must be off or it, not '$SSH'" ;;
  esac
  case "$MDNS" in on|off) ;; *) hb_die "MDNS must be on or off, not '$MDNS'" ;; esac
  c4=$(v4 "$CLINIC_RANGES"); c6=$(v6 "$CLINIC_RANGES"); i4=$(v4 "$IT_RANGES"); i6=$(v6 "$IT_RANGES")
  echo "# TrialBox input firewall (deploy/hardening/apply.sh; T-634, D-408). Generated: do not edit; change"
  echo "# deploy/site/hardening.conf and run apply.sh again."
  echo "table inet trialbox_input"
  echo "delete table inet trialbox_input"
  echo "table inet trialbox_input {"
  for set in clinic_v4:ipv4_addr:"$c4" clinic_v6:ipv6_addr:"$c6" it_v4:ipv4_addr:"$i4" it_v6:ipv6_addr:"$i6"; do
    name=${set%%:*}; rest=${set#*:}; type=${rest%%:*}; elems=${rest#*:}
    if [ -n "$elems" ]; then
      echo "  set $name { type $type; flags interval; elements = { $elems }; }"
    else
      echo "  set $name { type $type; flags interval; }"
    fi
  done
  echo "  chain published {"
  echo "    type filter hook prerouting priority -150; policy accept;"
  echo "    iif \"lo\" accept"
  echo "    fib daddr type local tcp dport 443 ip saddr @clinic_v4 accept"
  echo "    fib daddr type local tcp dport 443 ip6 saddr @clinic_v6 accept"
  echo "    fib daddr type local tcp dport 443 counter drop"
  echo "  }"
  echo "  chain input {"
  echo "    type filter hook input priority 0; policy drop;"
  echo "    iif \"lo\" accept"
  echo "    ct state established,related accept"
  echo "    ct state invalid drop"
  echo "    iifname \"docker0\" accept"
  echo "    iifname \"br-*\" accept"
  echo "    ip protocol icmp icmp type { echo-request, destination-unreachable, time-exceeded, parameter-problem } accept"
  echo "    ip6 nexthdr icmpv6 icmpv6 type { echo-request, destination-unreachable, packet-too-big, time-exceeded, parameter-problem, nd-router-advert, nd-neighbor-solicit, nd-neighbor-advert } accept"
  echo "    udp sport 67 udp dport 68 accept"
  echo "    udp sport 547 udp dport 546 accept"
  echo "    tcp dport 443 ip saddr @clinic_v4 accept"
  echo "    tcp dport 443 ip6 saddr @clinic_v6 accept"
  if [ "$MDNS" = on ]; then  # OPS-005: the box's .local name answers the clinic's computers, nobody else
    echo "    udp dport 5353 ip saddr @clinic_v4 accept"
    echo "    udp dport 5353 ip6 saddr @clinic_v6 accept"
  fi
  if [ "$SSH" = it ]; then
    echo "    tcp dport 22 ip saddr @it_v4 accept"
    echo "    tcp dport 22 ip6 saddr @it_v6 accept"
  fi
  echo "    counter drop"
  echo "  }"
  echo "}"
}

firewall() {
  rules=$(render) || exit 1
  hb_say "input firewall: 443 from $CLINIC_RANGES; SSH $SSH${IT_RANGES:+ ($IT_RANGES)}"
  printf '%s\n' "$rules" | hb_write "$HR/etc/trialbox/input.nft" 600
  hb_run nft -c -f "$HR/etc/trialbox/input.nft"
  hb_run nft -f "$HR/etc/trialbox/input.nft"
  # the unit loads the same file at every boot, before the network comes up
  sed "s#@TB_ROOT@#$ROOT#g" "$HERE/trialbox-input.service" | hb_write "$HR/etc/systemd/system/trialbox-input.service" 644
  if command -v systemctl >/dev/null 2>&1; then
    hb_run systemctl daemon-reload
    hb_run systemctl enable trialbox-input.service
  fi
}

ssh_baseline() {
  case "$SSH" in
    off)
      hb_say "SSH off: the service is stopped and disabled"
      if command -v systemctl >/dev/null 2>&1; then
        hb_run systemctl disable --now ssh.service ssh.socket 2>/dev/null || true
      fi
      ;;
    it)
      hb_say "SSH from $IT_RANGES only: keys only, no root login, no forwarding"
      hb_write "$HR/etc/ssh/sshd_config.d/50-trialbox.conf" 644 <"$HERE/sshd/50-trialbox.conf"
      if [ "$DRY" != 1 ] && command -v sshd >/dev/null 2>&1; then
        sshd -t || hb_die "sshd -t refused the configuration (above); fix it before the session ends"
      fi
      command -v systemctl >/dev/null 2>&1 && hb_run systemctl reload ssh.service 2>/dev/null || true
      ;;
    *) hb_die "SSH must be off or it, not '$SSH'" ;;
  esac
}

case "$WHAT" in
  render) render ;;
  firewall) firewall ;;
  ssh) ssh_baseline ;;
  all) firewall; ssh_baseline ;;
esac

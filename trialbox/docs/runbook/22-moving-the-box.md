# RUNBOOK §22 part: moving the box to another address

*T-635 (OPS-074). Another room, another network, or a new host name.*

**Drill (T-213b):** `test_runbook_22_moving_the_box` (Docker drill: change the host name and address by these steps;
`check-tls` passes on the new name, the network sheet is written again, the console answers on the new name).

1. **Plan with hospital IT:** the new address, the host name (DNS), the firewall rule for 443 from the clinic PCs, the
   route to the feed, the mail server and the backup share. If the name changes, a new certificate (§12).
2. **Before the move:** a backup by hand, checked (`backup-status`). Stop the stack (`systemctl stop trialbox`) and shut
   the host down. A TPM-sealed KEK stays with the box: move the whole box, never the disks alone.
3. **After the move:** start the host. If the name changed, set `TB_TLS_HOSTNAME` (and the certificate files) in
   `deploy/.env`, run `python -m console.cli check-tls`, then `docker compose up -d --wait`.
4. Write the network sheet again (Operations page, or `tools/network_sheet.py`) and give it to hospital IT.
5. `trialbox doctor --env-file deploy/.env`: no FAIL (the backup target and the clock are reached from the new
   network).
6. Sign in from a clinic PC on the new name; the next morning, check the morning mail.

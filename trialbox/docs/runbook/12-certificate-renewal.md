# RUNBOOK §12 part: certificate renewal

**Reader:** hospital IT, or the box owner where the box makes its own certificate.

*T-635 (OPS-074). The console is served on 443 by Caddy (§12).*

**Drill (T-213b):** `test_runbook_12_certificate_renewal` (in process, with certificates made for the test:
a certificate that ends in 20 days gives the 30-day warning of step 1; step 2 puts the new certificate and key
in the same files; step 3 passes, and fails on a key that is not the certificate's, a wrong name and a date not
valid today). Steps 4 and 5 need the running box and are not rehearsed by a test.

**Internal CA** (`TB_TLS_MODE` not `hospital`). Caddy renews its own server certificate by itself; nothing to do. The
root certificate on the staff PCs lasts for years; when Caddy makes a new root (the `caddy-data` volume was lost),
hospital IT must push the new root to the PCs again (§12, TLS step 3).

**The hospital's certificate** (`TB_TLS_MODE=hospital`).

1. `python -m console.cli check-tls` warns 30 days before the end. Ask hospital IT for the new certificate then: it
   must carry the same name (`TB_TLS_HOSTNAME`).
2. Put the new certificate (with its chain) and key in the files `TB_TLS_CERT_FILE` and `TB_TLS_KEY_FILE` name (key:
   0600, root). Keep the old files until step 4 passes.
3. `python -m console.cli check-tls` (a key that is not the certificate's, a wrong name or a date not valid today
   fails).
4. `docker compose up -d --force-recreate caddy`. Open the console from a clinic PC: no warning; the browser shows
   the new end date.
5. Delete the old key file. If the old key may have been copied, ask hospital IT to revoke the old certificate.

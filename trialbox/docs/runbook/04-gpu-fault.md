# RUNBOOK §4 part: GPU fault

**Reader:** Aimedics, with the box owner at the box.

*T-635 (OPS-074). Signs: `selftest.failed` in the audit, a run fails with "the model did not answer", the model
server restarts again and again, `nvidia-smi` errors.*

**Drill (T-213b):** `test_runbook_04_gpu_fault` (Docker drill: the model server is stopped; the night's model jobs do
not start; a screening run fails with "the model did not answer"; after the restart the canary passes).

**What users see.** Notes cannot be judged while the models are down. A screening run fails with "the model did not
answer" and its rows say "not checked (system busy)"; the verifier never stands in for the judge (D-276; plan Q-16).
Model jobs of the night wait for the pair canary and do not start while it fails (§2).

1. **Look:** `nvidia-smi` on the host (driver loaded, the card seen, memory, errors). `docker compose ps` (is
   a model service restarting?). Inside the network: `curl -s http://gateway:8020/v1/serving/status` (§10).
2. **Restart the stopped services:** `docker compose up -d --wait`. The watchdog may already have restarted a model
   service; the audit shows it (`ops.watchdog.restart`, D-360).
3. **Reboot once** if `nvidia-smi` fails: `systemctl stop trialbox`, reboot, then check `nvidia-smi` again. Never
   update or reinstall the driver to fix it (§24: the driver is held).
4. **Run the canary:** `sudo python3 -m tools.trialbox selftest` on the box (the compose files of `deploy/.env`; no `make` needed), or "Run now" on the admin Models tile. Either is the gate's result: a pass lets note answers exclude again at once and the next night runs as usual; tell users the alert is over. "not run" means a model did not answer yet: wait a minute and run it again.
5. **Still failing:** a P2 ticket (§21) with `nvidia-smi -q` and the gateway log (no patient data). A dead card is a
   hardware replacement (§22, "Replacing hardware").

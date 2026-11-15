# TrialBox: the one page for hospital IT

**Reader:** hospital IT. The box owner sets the box up and runs it; IT is asked for the three things below only
(T-735, D-729). The full port table is the [network sheet](network-sheet.en.md).

## 1. The address

- One fixed address for the box on the hospital network (a reservation in DHCP is enough).
- One name in the hospital's DNS for that address. The owner writes it as `TB_TLS_HOSTNAME`; staff open
  `https://<that name>` in a browser.
- The certificate: the box makes its own for that name, or IT gives one from the hospital's CA (RUNBOOK §12).

## 2. The data connection

- A read-only folder or share with the export the box reads each night (the hospital's own feed, or the EDC's
  export). The box never writes there.
- For a backup copy off the box: a share the box may write to (NFS 2049 or SMB 445), or an outside disk the owner
  plugs in. Either one; the owner chooses.
- Optional: the hospital's mail relay (SMTP) for the morning notices, and the domain controller (LDAPS 636) for
  sign-in with the hospital account. The box works without both.

## 3. The firewall line

- **In:** TCP 443 to the box, from the clinic PCs' network. Nothing else on the box is reachable.
- **Out:** nothing. The box needs no internet: updates come on signed media, and the list of trials comes in each
  update. Only if the hospital chooses live ClinicalTrials.gov at the install: TCP 443 to `clinicaltrials.gov`.
- The box's clock: UDP 123 to the hospital's time server.

Questions about the box go to the box owner first; the owner reaches Aimedics (RUNBOOK §7).

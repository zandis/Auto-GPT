# TrialBox: the one page for hospital IT (a box its supplier prepared)

**Reader:** hospital IT. The box arrives prepared by its supplier and its owner sets it up from the console; IT is asked for the 6 things below. The full port table is the [network sheet](network-sheet.en.md).

Made from the box's own check list (`libs/tb_common/preflight.py`) by `tools/it_one_page.py` (10K-18, D-1378); do not edit it by hand. The box checks each item itself (`doctor --preflight`, RUNBOOK §1) and shows it red or amber, with the words below, until it is done.

## What IT is asked for

### Network

- **Box name and certificate**: Ask hospital IT to add the box's name to the hospital DNS, pointing at the box's address, and, for a hospital certificate, to issue one that names it.
- **Clock and time server**: Ask hospital IT to let the box reach the hospital's time server (NTP) and give its address to the box's supplier; wait until the clock is synchronised.
- **Mail relay**: Ask hospital IT for the mail relay's name and port, and to accept mail from the box.

### Storage

- **Backup share**: Choose a backup place off the box (a second disk or the hospital's share) and ask hospital IT to give the box write access to it.
- **Audit record share**: Ask hospital IT for a write-once (WORM) share off the box: the box may add a file there, but no one on the box, its administrator (root) included, may change or delete a file once written.

### Hospital data

- **Hospital data feed**: Ask hospital IT to put the export in the folder the box reads and to let the box read it; the line shows how many files the box found.

## What the supplier prepared

The box checks these too; nothing is asked of IT. A red line here is the supplier's to fix.

- Free disk space
- Key protection (TPM; disk unlock with Tang)
- Graphics card against the tier record

## The address and the firewall line

- One fixed address for the box (a reservation in DHCP is enough) and one name for it in the hospital's DNS: the owner writes it as `TB_TLS_HOSTNAME`, and staff open `https://<that name>`.
- **In:** TCP 443 to the box, from the clinic PCs' network. Nothing else on the box is reachable.
- **Out:** no internet: updates come on signed media, and the list of trials comes in each update. Only if the hospital chooses live ClinicalTrials.gov at the install: TCP 443 to `clinicaltrials.gov`.
- **Inside the hospital:** UDP 123 to the time server; NFS 2049 or SMB 445 to the backup and audit shares; the mail relay's port, when one is named.

Questions about the box go to the box owner first; the owner reaches the box's supplier (RUNBOOK §7).

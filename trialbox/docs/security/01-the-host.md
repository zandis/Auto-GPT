# 1. The host

- **Disk.** Install Ubuntu on **LUKS2** ("Use an entire disk" and "Encrypt the LVM group"). Every store of PHI is on
  it: lake, FHIR store, objects, pid map, audit.
- **Unlock with the TPM**, so the box restarts alone but the disk is useless elsewhere:

  ```sh
  systemd-cryptenroll --tpm2-device=auto --tpm2-pcrs=7 /dev/<luks-partition>   # bound to Secure Boot state
  # /etc/crypttab: <name> UUID=<uuid> none tpm2-device=auto
  update-initramfs -u
  ```

  The LUKS recovery passphrase goes in the hospital's sealed-envelope procedure, never on the box.
- **Swap off** so PHI never pages to disk (`swapoff -a`, remove it from `/etc/fstab`, mask `swap.target`). The host
  check fails while swap is on.
- **GB10:** driver 580.142 exactly, held; the vLLM image pinned by digest.
- **Windows:** the box runs in WSL2. BitLocker, WSL swap and key custody (DPAPI/TPM) are post-platform work (D-125,
  D-128).

# Data destruction (データ消去手順 / 資料銷毀程序)

| Field | Value |
| --- | --- |
| Document ID | TB-PRV-08 |
| Version | 0.1 (2026-11-11, T-318, D-411) |
| Standard | NIST SP 800-88 Rev. 1, Guidelines for Media Sanitization (Clear, Purge, Destroy) |
| Scope | study-level lists and files when a study closes; removable media; a disk taken out of service. Closing a whole site and decommissioning the box is T-628 (RUNBOOK §20), which uses §3 of this page for its disks. |
| Who | the data steward decides; hospital IT does the media steps; the site administrator records |

## 1. When a study closes

| Step | What | How | Record |
| --- | --- | --- | --- |
| 1 | the PI confirms the study is closed and which records the law or the sponsor requires to be kept | the study's state set to closed (R-27) | audit `study.settings` |
| 2 | keep the essential records | the screening log, consent and enrolment records, EDC trail (R-03, R-05, R-07, R-08) stay for their retention; they are pseudonymous | none |
| 3 | delete the study's working lists | candidate lists, summaries and job outputs of the study are deleted by the retention job when `outputs_days` passes; the steward may delete earlier from the study's page | every deletion audited with the object's sha256 (SECURITY §6) |
| 4 | delete copies outside the box | files people downloaded (the export ledger lists them, `python3 -m tools.trialbox exports`) are deleted by their holders; each holder confirms to the steward | the steward's list, kept at the hospital |
| 5 | Taiwan: 人體研究法 Art. 19 | material not de-linked is destroyed after the study unless the participant agreed otherwise | as step 3 |

## 2. Removable media and printouts

| Item | Method (NIST SP 800-88) | Who |
| --- | --- | --- |
| a USB stick that carried a support bundle (no patient data) | Clear (overwrite) or reuse | site administrator |
| a USB stick or disk that carried patient data | Purge (cryptographic erase if encrypted, else a vendor secure-erase command), or Destroy | hospital IT |
| printed lists | cross-cut shredding in the hospital's confidential waste | the holder |

## 3. A disk taken out of service

1. The disk never leaves the hospital before it is purged (RUNBOOK §21, §22 "Replacing hardware").
2. Self-encrypting or encrypted disk: **Purge** by cryptographic erase (destroy the key), then a secure-erase command.
3. Other SSD or NVMe: **Purge** with the drive's sanitize command (`nvme sanitize`, ATA `SANITIZE`); verify with a read
   of a sample of blocks.
4. A disk that cannot be purged (failed, unreadable): **Destroy** (shred or disintegrate) by the hospital's certified
   contractor.
5. Hospital IT writes the certificate of §4. Aimedics gets only the outcome line (date, method, serial number's last
   four characters), never the disk.

## 4. Certificate of sanitization

```text
Certificate of sanitization (NIST SP 800-88 Rev. 1, Appendix G)
Site: ____________          Date: YYYY-MM-DD
Media type and maker: ____________   Serial: ____________
Data classes held: D_       Reason: study closed / disk replaced / decommission
Method: Clear / Purge (cryptographic erase / sanitize command) / Destroy
Tool and version: ____________
Verification: ____________ (sample read, tool report)
Done by (role): ____________   Checked by (role): ____________
Kept by: the hospital's privacy office
```

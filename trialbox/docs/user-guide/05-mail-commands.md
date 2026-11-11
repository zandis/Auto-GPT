# 5. Mail commands

The box also answers mail. The subject is the command; the result comes back by mail. Patient-level files go only to
the study's internal list, as an encrypted 7z, with the password in a second mail.

| Command | Example | Result |
| --- | --- | --- |
| FEAS | `FEAS GZQO lookback=36` (attach the protocol the first time) | feasibility PDF and XLSX |
| SCREEN | `SCREEN GZQO version=1.0.0` | encrypted candidate workbook and a summary PDF |
| CASE | `CASE GZQO mrn=10000001 lang=zh-TW` with the chart attached | eligibility sheet per criterion with quotes |
| CONSENT | `CONSENT GZQO lang=en,ja,zh-TW` with the approved consent form | a draft plain-language guide (§6) |
| RELEASE | `RELEASE <job id> [drop=I03] [keep=I07]` | releases a checked consent guide |
| NAV, SUBMIT | `NAV RA-BIO dept=RHEU`; `SUBMIT ONC-OSI pid=… bundle=<NAV job>` | Taiwan NHI lists, drafts and TWPAS bundles; the claim (dry run by default) |
| COHORT | `COHORT GOUT-COH` | alliance table and report; `COHORT MERGE` at the alliance root |
| FEEDBACK | `FEEDBACK GZQO` with `screen_feedback.csv` | stored for calibration |
| STATUS, CANCEL | `STATUS <job id>` | the job's state, or cancels it |

A console button is the same call as its mail line, with the same permissions and audit.

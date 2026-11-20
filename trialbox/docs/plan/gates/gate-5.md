# Gate 5: what it guarantees, what calls it, what is still in the ratchet

For a named model purpose, `tb_common.output_gate.prepare_output` builds a fresh payload from permitted fields, checks their types and masks clinical text with the installed note and name recognisers. If analysis is unavailable or a value cannot be released, the gate withholds the payload and audits a fixed purpose and reason. Pattern coverage is limited to the identifiers the recognisers detect.

The screening cascade, both note judges, uploaded chart reader, site fact extraction, registry matcher, EDC prefill and note embeddings pass model text through the gate. The gateway client, direct model client, gateway dispatch and on-box proxy also check the outgoing request. Tests observe the arguments or wire bodies in English, Traditional Chinese and Japanese.

The CI inventory searches Python under `libs/` and `services/`, plus the support writer in `tools/`. The search covered model methods and HTTP endpoints, logger arguments and tracebacks, SMTP and mail clients, file routes, response headers, job artifacts and archive writes. The ratchet records individual calls, including wrappers whose checks happen downstream. Next come structured logs, count-based aggregate files and release of mail and downloads, then support archives and study and rule-set packages.

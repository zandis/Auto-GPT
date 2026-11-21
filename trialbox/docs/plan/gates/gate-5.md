# Gate 5: what it guarantees, what calls it, what is still in the ratchet

For a named model purpose, `tb_common.output_gate.prepare_output` builds a fresh payload from permitted fields, checks their types and masks clinical text with the installed note and name recognisers. If analysis is unavailable or a value cannot be released, the gate withholds the payload and audits a fixed purpose and reason. Pattern coverage is limited to the identifiers the recognisers detect.

The screening cascade, both note judges, uploaded chart reader, site fact extraction, registry matcher, EDC prefill and note embeddings pass model text through the gate. The gateway client, direct model client, gateway dispatch and on-box proxy also check the outgoing request. Tests observe the arguments or wire bodies in English, Traditional Chinese and Japanese.

The CI inventory searches Python under `libs/` and `services/`, plus the support writer in `tools/`. The search covered model methods and HTTP endpoints, logger arguments and tracebacks, SMTP and mail clients, file routes, response headers, job artifacts and archive writes. The ratchet records individual calls, including wrappers whose checks happen downstream. Next come structured logs, count-based aggregate files and release of mail and downloads, then support archives and study and rule-set packages.

## Open for later slices

The mail release slice owns `services/mail_gateway/gateway.py` at `Gateway._attempt`. The inventory lists its transport call. An authorized sender can label a free-text body `aggregate` and include a patient name. Build the external message from approved aggregate data before transport, including subject and attachments.

## Indexed note identifiers

The vector store keys embeddings by the SHA of the stored chunk. The gate checks the full note before splitting it. If the full guard would change text produced by the stored mask version, indexing refuses the note with `output_identifier_refused`. Ranking treats incompatible stored chunks as stale. Decide the new mask version and how to rebuild or retire old embeddings before enabling those notes.

The read-only model proxy sends fixed refusal codes to the gateway using the configured model credential. The gateway acknowledges the event after its audit writer accepts it. If that write or the receipt fails, the proxy withholds the request and returns 503. The proxy requires the site's settings for its MRN rule.

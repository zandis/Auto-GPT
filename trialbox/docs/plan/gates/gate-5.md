# Gate 5: what may leave the box, what calls the gate, what is still open

`tb_common.output_gate.prepare_output` is the one function for every exit. For a model purpose it builds a fresh payload from permitted fields, checks their types and masks clinical text with the installed note and name recognisers. It then withholds a text if any identifier survives in what the recognisers left, or in any encoded form of the original: percent, base64, quoted-printable, HTML entities, backslash escapes. It also withholds a text that holds a pseudonym, which the recognisers never mask. If analysis is unavailable or a value cannot be released, the gate withholds the payload and audits a fixed purpose and reason.

For the other exits (`EXITS`: mail, download, the support bundle, export) the gate reads the bytes as a receiver could. It opens gzip, zip, tar, PDF and MIME. It decodes every layer of percent, base64 (also inside JSON), quoted-printable with soft breaks, entities with and without `;`, and `\x` and `\u` escapes. It removes zero-width characters and soft hyphens, and folds full-width forms. It refuses the bytes if a name, chart number, phone number, e-mail address after its label, national identifier or pseudonym survives in any of them. A name counts with no label: after a word for the patient, a Japanese family name with its given name, or an English name before an age and sex. What it releases is a `Released`, which only the gate makes. An exit turns it back into bytes with `leave`, which refuses anything else, including a `Released` whose bytes were swapped.

## The exits and how each goes through the gate

| Exit | Road in the cross-path test | Through the gate |
| --- | --- | --- |
| Model | `model` | `prepare_output(<purpose>, "model", ...)` at every model call; a test keeps every model call behind the gateway |
| Mail | `mail_send`, `mail_reply` | `Gateway._prepare` reads the message and each password mail as they will leave; the transport sends only what `leave` returned. A refused send is held as `failed` for a person; nothing leaves. A reply that would quote an identifier is replaced by the generic reply, which quotes nothing. |
| Support bundle | `support_bundle` | Not yet: lane H's files; the change asked for is below |
| Download | `download_enrolment_report` | Not yet: the change asked for is below |
| Export | `export_sponsor_pack` | Not yet: lane K's file; the change asked for is below |

## The cross-path test

`tests/unit/test_gate5_cross_path.py` plants four synthetic people (`tests/gate5_people.py`), one identifier and one encoding class at a time, in every exit. The people have names in Japanese, Traditional Chinese and English, and a romanised name with macrons. Each has a chart number, a phone number, an e-mail address, a national identifier and a pseudonym. The encoding classes are those the two reviews of #1314 list, plus a name after its label. The judge (`tests/gate5_kit.py`) reads what left as a receiver could, with code written apart from the gate's. The invariants are these: no planted identifier, name part or 12 digits of a pseudonym survives; a refusal leaves nothing; a text with no identifier leaves; what leaves is what the gate released. `test_every_exit_site_has_a_road` reads the output-sink inventory and fails for an exit site with no road. `tools/gate5_planted.py` applies the planted mistakes of `tools/gate5_planted.json` to a scratch copy and compares every finding line with the unmutated run.

The test is red where the product is red: the bundle, the enrolment report and the sponsor pack leave every planted identifier, and dozens of exit sites have no road yet. The model and mail roads are green.

## Open for later slices

The inventory still lists the mail transport calls in `Gateway._attempt`, `Gateway._after_main` and `Gateway._reply`. The scan does not follow the gate in `Gateway._prepare` and `Gateway._reply_message`, so the calls stay listed as a tripwire. Mail no longer trusts the `aggregate` tag: the body, subject and attachments are read whatever the tag says.

Changes asked of other lanes, each a body change only:

- **Support bundle (lane H), `tools/support_bundle.py`.** In `_build`, after `b.seal()`, pass every member through `prepare_output("bundle_member", "support", {"name": name, "text": text})`; leave out and list a member the gate refuses. In `_write_tar`, write `leave(prepare_output(...), "support")` in place of `members[name].encode("utf-8")`. In `_logs_part`, when the read reached its limit, drop the cut last line before the scrub.
- **Sponsor pack (lane K), `services/console/app.py` `build_sponsor_pack`.** Return `leave(prepare_output("aggregate_file", "export", {"name": "sponsor_pack.zip", "bytes": buf.getvalue()}), "export")`; the route answers a refusal with 422.
- **Enrolment report (owner to be named), `services/orchestrator/lifecycle_api.py` `report_files`.** Return the CSV and the XLSX as released by `prepare_output("aggregate_file", "download", ...)` and `leave`; the route answers a refusal with 422.
- **The other console downloads (lane K)** and the test-profile mail sender `HttpBackend.send_test_mail`: the same pattern per route.

The sink ratchet's ceiling is the table as first added on this branch. Master's H-71 moved six bundle sites, and the ceiling counts them as growth, so `test_remaining_output_sinks_match_the_inventory` waits for a ruling.

## Indexed note identifiers

The vector store keys embeddings by the SHA of the stored chunk. The gate checks the full note before splitting it. If the full guard would change text produced by the stored mask version, indexing refuses the note with `output_identifier_refused`. Ranking treats incompatible stored chunks as stale. Decide the new mask version and how to rebuild or retire old embeddings before enabling those notes.

The read-only model proxy sends fixed refusal codes to the gateway using the configured model credential. The gateway acknowledges the event after its audit writer accepts it. If that write or the receipt fails, the proxy withholds the request and returns 503. The proxy requires the site's settings for its MRN rule.

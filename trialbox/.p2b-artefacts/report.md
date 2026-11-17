# Box run: TB-BOX-RUN-COMPLETE: every step ran; the parts say which test rules passed

## What it ran

- mode: `"production"`
- not_a_release: `false`
- commit: `null`
- bundle_id: `null`
- release_seq: `null`
- signature_sha256: `null`
- signing_key_id: `null`
- bundle_sha256: `null`
- image_digests: `{"llm-service": ["sha256:befccf0e7e4089aa23926bb6f887a85c0d46c2a99e6de5c5ffdf5cb7957c5b34"], "llm-verifier": ["sha256:befccf0e7e4089aa23926bb6f887a85c0d46c2a99e6de5c5ffdf5cb7957c5b34"]}`
- weight_manifests: `[{"build_id": "gemma-4-26b-a4b-it-rtxpro6000", "manifest_sha256": "5e5bef7a61feffc04e388886d2f1996dbffd1fa10b1722e2fa2a832c39e28a76", "revision": "a19cfe00be84568a6867111c9a68c9c44fdcffe6"}, {"build_id": "qwen3.5-9b-rtxpro6000", "manifest_sha256": "869b525324626a867331f26126a5605aeb10ae40e9dfbc14fee`
- chat_template_sha256: `"ae53464bf3be25802b3a5b37def7fd89667067d7577049b3b2d74c4d8de4c6d4"`
- served_prompts: `[{"id": "assist", "version": 2, "sha256": "ffd1a30ee30b6e515e52aa657fd5219a4b8173f663db4a02cbac20c3d2d6fb44"}, {"id": "chart_facts", "version": 2, "sha256": "30b19ce6a92ef982de2f49c09c9c7c1ff67c0f5bd511168a413dd36ee8d4d5d5"}, {"id": "classify_intent", "version": 3, "sha256": "6b9ec1c30611d39e3ed2990`
- environment: `"VALIDATION"`
- served_prompts_in_environment: `["assist@2", "chart_facts@2", "classify_intent@3", "concept_map@2", "consent_explain@2", "consent_translate@2", "consent_verify@2", "crf_prefill@2", "draft_doc@2", "ie_locate@2", "ir_extract@4", "judge@5", "profile_summary@2"]`
- embedder_in_screen: `"not the hash stand-in in screen_cascade (#589 or later): the embed service"`
- tripwire: `"set by the declared setting TB_GATEWAY_PHI_TRIPWIRE=off"`
- limits: `{"after": {"authserv": "mx.hospa.test", "jobs_per_sender_per_day": "0", "mail_per_recipient_per_day": "0", "rate_limit_per_sender_per_day": 20, "rate_limits_per_day": {}}, "before": {"authserv": "mx.hospa.test", "jobs_per_sender_per_day": "0", "mail_per_recipient_per_day": "0", "rate_limit_per_sende`

## R2 build

- FAIL every build step done
- FAIL signature verified and the release record is one PRODUCTION takes
- FAIL the key file was gone after signing

## Public accuracy on the installed box (scores: acc-score, outside the box)

- PASS the box routes the compile and the screen in its environment (judge, verifier, compiler): `[{"role": "judge", "class": "D3", "route": "patient", "builds": [{"alias": "j-workhorse", "build": "gemma-4-26b-a4b-it-rtxpro6000", "routes": true}, {"alias": "v-verifier", "build": "qwen3.5-9b-rtxpro6000", "routes": true}], "routes": true}, {"role": "extract_criteria", "class": "D1", "route": "protocol", "builds": [{"alias": "j-workhorse", "build": "gemma-4-26b-a4b-it-rtxpro6000", "routes": true}`
- PASS jmed: every protocol compiled, approved and screened (compiled only: a compile-only set); protocols in flight: 1 at most of 1: `{"counts": {"patients_answered": 594, "protocols": 2, "refused_by_tripwire": 0, "screened": 2}, "streams": 1, "in_flight_max": 1, "refused_by_tripwire": 0, "uploaded": true, "score": {"answer_key": {"key": "v2", "what": "B1-B3 of the P1b review: B1 birth date the visit minus the stated age in its unit; B2 placed age lines keep their unit and a bound the protocol states is not written again; B3 JME`
- PASS tcga: every protocol compiled, approved and screened (compiled only: a compile-only set); protocols in flight: 1 at most of 1: `{"counts": {"patients_answered": 500, "protocols": 1, "refused_by_tripwire": 0, "screened": 1}, "streams": 1, "in_flight_max": 1, "refused_by_tripwire": 0, "uploaded": true, "score": {"answer_key": {"key": "v2", "what": "B1-B3 of the P1b review: B1 birth date the visit minus the stated age in its unit; B2 placed age lines keep their unit and a bound the protocol states is not written again; B3 JME`
- FAIL sigir: every protocol compiled, approved and screened (compiled only: a compile-only set); protocols in flight: 3 at most of 3: `{"counts": {"failed": 3, "patients_answered": 102, "protocols": 104, "refused_by_tripwire": 0, "screened": 101}, "streams": 3, "in_flight_max": 3, "refused_by_tripwire": 0, "uploaded": true, "score": {"answer_key": {"key": "v2", "what": "B1-B3 of the P1b review: B1 birth date the visit minus the stated age in its unit; B2 placed age lines keep their unit and a bound the protocol states is not writ`

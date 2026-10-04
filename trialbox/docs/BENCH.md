# Bench results (SPEC §11.3) — development host

`tools/bench.py` (D-80) runs the real code path of each job and projects linearly to the §11.3 size.

**This host is not the reference box.** The reference is x86 with one 32 GB GPU; this host is x86_64 with 4 vCPU,
16 GB RAM (15 usable), about 12 GB of free disk and **no GPU**. The LLM is the deterministic stub, so judge,
ir_extract and draft_doc latency is **not measured**. The ingest run shared the CPU with an emulated arm64 image
build, so its time is pessimistic.

| job | §11.3 size / target | measured here | time | projected to the §11.3 size | within target |
| --- | --- | --- | --- | --- | --- |
| Ingest | 50k patients / night, ≤ 2 h | 15,000 patients (CSV → mapping → NDJSON → lake, HL7 validator on the 1 % sample) | 299 s | 16.6 min | yes¹ |
| FEAS | 300k × 36 month-ends × 25 criteria, ≤ 30 min | 30,000 patients × 36 × 23 (in memory) | 25 s | 4.5 min | yes |
| FEAS | (same) | 100,200 patients × 36 × 23 (lake memory capped at 6 GB, spilling) | 215 s | 11.7 min² | yes |
| SCREEN | 1,000 × 25 CQL + 300 × 5 note, ≤ 3 h | 600 patients × 18 CQL criteria (36 expressions) on HAPI `$evaluate`, 8 concurrent | 28.7 s | 1.1 min (CQL share)³ | yes³ |
| MICROBATCH | 100 × 5 time-sensitive, ≤ 10 min | 365 patients re-evaluated (pool + first-Monday incident scope) | 5.3 s | < 0.1 min³ | yes³ |
| NAV | 500 × 15 + 50 drafts + 50 bundles, ≤ 1 h | RA-BIO + ONC-OSI: 162 patients, 17 drafts, 13 TWPAS bundles, HL7 validator (two IG loads) | 96.5 s | 6.2 min³ | yes³ |
| Compile | 25-criterion protocol incl. equivalence, ≤ 20 min | GZQO: 23 criteria → CQL (translator) + SQL, equivalence on 200 patients on HAPI | 21.5 s | 0.4 min³ | yes³ |

¹ fhir-store load not included (it runs alongside the lake rebuild in production). **Memory:** ingest holds the batch
in memory, about 4.9 GB RSS at 15k patients. A 50k batch was killed by the 15 GB host. The 128 GB reference box
fits it; smaller hosts ingest in `--since` deltas (D-80).
² 300k patients could not run here: DuckDB's spill exceeds the free disk. The cap that prevents an OOM kill
(`TB_LAKE_MEMORY_LIMIT`, default 40 % of RAM) is in the lake. At 40 % of 128 GB the reference box keeps 300k in
memory, closer to the 30k rate.
³ Deterministic share only. Measure the LLM share on the reference box:
`python tools/bench.py --tasks screen,microbatch,nav,compile --llm-url http://llm-service:8000/v1 --llm-model <name>`.

Every deterministic share is far inside its target. The go-live bench must still be repeated on the reference
hardware with the real models, as §11.3 requires.

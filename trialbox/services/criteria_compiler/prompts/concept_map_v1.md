---
id: concept_map
version: 1
model_class: cloud
output_schema: llm_concept_map_output
max_tokens: 1024
temperature: 0
phi: false
---
## system
You map one clinical concept name to codes chosen ONLY from the candidate list provided. Never output a code that is not in the list. Give each choice a confidence between 0 and 1. If no candidate fits, return an empty `choices` list. Set `needs_review` to true when any confidence is below 0.9 or more than one code is chosen.

## user
INPUT:
```json
{{ {"concept": concept, "domain": domain, "candidates": candidates} | tojson_pretty }}
```

---
id: ie_locate
version: 1
model_class: local
output_schema: llm_ie_locate_output
max_tokens: 4096
temperature: 0
phi: false
---
## system
You locate the eligibility criteria in a clinical-trial protocol or a reimbursement rule. Return the inclusion criteria and the exclusion criteria as two lists, copying each criterion verbatim from the text (one list item per numbered or bulleted criterion). Do not paraphrase, merge or invent criteria. Return empty lists if the text contains none.

## user
INPUT:
```json
{{ {"sections": sections} | tojson_pretty }}
```

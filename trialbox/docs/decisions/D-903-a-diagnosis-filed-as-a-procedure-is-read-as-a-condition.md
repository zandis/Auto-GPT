# D-903 A diagnosis filed as a procedure is read as a condition

- **Task:** red of lane G's accuracy run (#639, 2026-11-15, tcga), item 4; **Date:** 2026-11-15; **Status:** reserved
- **Decision:** the compiler's post-process re-files a concept the model put under `procedure` whose name names a diagnosis (carcinoma, cancer, tumour, lymphoma, disease, syndrome, ...-itis; がん, 癌, 腫瘍, 病, 炎) and no operation (-ectomy, -otomy, resection, surgery, biopsy, transplant, imaging, therapy; 手術, 切除, 術) under `condition`: its value set is mapped as a condition and its atoms read the diagnoses. The criterion is flagged `domain_refiled` and `needs_review`, and the compile warning names the concept. A real procedure stays a procedure.
- **Not here:** breast cancer (C50) is not in the terminology's synonyms either; adding it changes the terminology release RA-JAK is pinned to (the question of the diabetes grouper on #639). Until then the list is empty and reads unknown (D-796).
- **Test:** `tests/unit/test_diagnosis_filed_as_procedure.py`.

-- Taiwan SQL-view door: export code pairs from a versioned vocabulary, never drug names.
-- Load the reference columns with tw_reference.drug_pairs before joining.
SELECT DISTINCT n.nhino AS source_code, 'ATC' AS target_vocabulary,
       n.atc AS target_code
FROM vocab.nhi_drug n
JOIN vocab.concept a ON a.vocabulary_id = 'ATC' AND a.concept_code = n.atc
WHERE a.invalid_reason IS NULL
UNION
SELECT DISTINCT n.nhino AS source_code, 'RxNorm' AS target_vocabulary,
       rx.concept_code AS target_code
FROM vocab.nhi_drug n
JOIN vocab.concept a ON a.vocabulary_id = 'ATC' AND a.concept_code = n.atc
JOIN vocab.concept_relationship r ON r.concept_id_1 = a.concept_id
JOIN vocab.concept rx ON rx.concept_id = r.concept_id_2
WHERE a.invalid_reason IS NULL
  AND r.relationship_id = 'ATC - RxNorm' AND r.invalid_reason IS NULL
  AND rx.standard_concept = 'S' AND rx.vocabulary_id = 'RxNorm'
  AND rx.invalid_reason IS NULL;

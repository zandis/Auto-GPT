-- Taiwan SQL-view door: compact code pairs, scoped to codes required by the site.
SELECT DISTINCT c1.vocabulary_id AS source_vocabulary,
       upper(replace(c1.concept_code, '.', '')) AS source_code,
       c2.vocabulary_id AS target_vocabulary, c2.concept_code AS target_code
FROM vocab.concept c1
JOIN vocab.concept_relationship r ON r.concept_id_1 = c1.concept_id
JOIN vocab.concept c2 ON c2.concept_id = r.concept_id_2
WHERE c1.vocabulary_id IN ('ICD9CM', 'ICD10CM')
  AND c1.invalid_reason IS NULL
  AND r.relationship_id = 'Maps to' AND r.invalid_reason IS NULL
  AND c2.standard_concept = 'S' AND c2.vocabulary_id = 'SNOMED'
  AND c2.invalid_reason IS NULL;

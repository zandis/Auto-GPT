// TrialBox stand-in for NHI's published TWPAS pre-check library (fictional; same role, SPEC §9.5).
// Evaluated by fhir-store CR against the application bundle only (Library/$evaluate with data=<Bundle>,
// useServerData=false), context = the bundle's Patient.
library TWPAS_Precheck_OSI version '1.0.0'

using FHIR version '4.0.1'

include FHIRHelpers version '4.0.1' called FHIRHelpers

context Patient

define "Claims":
  [Claim]

define "Diagnosis Codes":
  flatten ("Claims" C return flatten (C.diagnosis D return (D.diagnosis as FHIR.CodeableConcept).coding.code.value))

define "Has NSCLC Diagnosis":
  exists ("Diagnosis Codes" X where StartsWith(X, 'C34'))

define "EGFR Positive":
  exists ([Observation] O
    where exists (O.code.coding C where C.code.value = '69548-6')
      and exists (O.interpretation I where exists (I.coding K where K.code.value = 'POS')))

define "Weight And Height":
  exists ("Claims" C where exists (C.supportingInfo S where exists (S.category.coding K where K.code.value = 'weight')))
    and exists ("Claims" C where exists (C.supportingInfo S where exists (S.category.coding K where K.code.value = 'height')))

define "Requests Osimertinib":
  exists ([MedicationRequest] M
    where exists (((M.medication as FHIR.CodeableConcept).coding) K where K.code.value in { 'BC26968100', 'BC26969100' }))

define "Issues":
  (List<System.String>{
    if "Has NSCLC Diagnosis" then null else '申請診斷非非小細胞肺癌（ICD-10-CM C34）',
    if "EGFR Positive" then null else '缺 EGFR 基因突變陽性報告',
    if "Weight And Height" then null else '缺體重或身高',
    if "Requests Osimertinib" then null else '申請品項非 osimertinib'
  }) X where X is not null

define "Passed":
  "Has NSCLC Diagnosis" and "EGFR Positive" and "Weight And Height" and "Requests Osimertinib"

/* TB_Common: TrialBox shared CQL helpers. Rendered from libs/tb_common/derived.py constants (do not edit the
   generated .cql). Semantics mirror the DuckDB SQL templates (DECISIONS D-17). */
library TB_Common version '1.0.0'

using FHIR version '4.0.1'

include FHIRHelpers version '4.0.1' called FHIRHelpers

/* local calendar date of an Observation (effectiveDateTime) */
define function "ObsDate"(O FHIR.Observation):
  date from FHIRHelpers.ToDateTime(O.effective as FHIR.dateTime)

/* numeric value of an Observation (null unless valueQuantity) */
define function "ObsValue"(O FHIR.Observation):
  FHIRHelpers.ToQuantity(O.value as FHIR.Quantity).value

/* first coding code of a valueCodeableConcept (null otherwise) */
define function "ObsCode"(O FHIR.Observation):
  First((O.value as FHIR.CodeableConcept).coding).code.value

define function "CompValue"(C FHIR.Observation.Component):
  FHIRHelpers.ToQuantity(C.value as FHIR.Quantity).value

/* most recent observation; ties broken by resource id (same as SQL ORDER BY effective, id) */
define function "LatestObs"(obs List<FHIR.Observation>):
  Last(obs O sort by (effective as FHIR.dateTime).value asc, id.value asc)

define function "LatestValue"(obs List<FHIR.Observation>):
  "ObsValue"("LatestObs"(obs))

define function "IsFemale"(P FHIR.Patient):
  if P.gender.value in { 'male', 'female' } then P.gender.value = 'female' else null

define function "BMI"(weightKg System.Decimal, heightCm System.Decimal):
  weightKg / Power(heightCm / 100.0, 2.0)

/* the recorded unit of an Observation, spelled as the conversion table spells it (D-149) */
/* "Swap" is Combine(Split(..)), not ReplaceMatches: in CQL engine 5.4.0 (HAPI FHIR 8.12) ReplaceMatches returns
   its input in quotes when the pattern does not match, so no unit was ever recognised (D-321); Split of '' is no
   list, so '' stays '' (no unit) */
define function "Swap"(s System.String, a System.String, b System.String):
  if s is null or s = '' then s else Combine(Split(s, a), b)

define function "UnitOf"(O FHIR.Observation):
  Lower("Swap"("Swap"("Swap"(Coalesce((O.value as FHIR.Quantity).code.value,
    (O.value as FHIR.Quantity).unit.value, ''), ' ', ''), 'µ', 'u'), 'μ', 'u'))

/* x when it is inside the item's scale, else null (D-189: a 0-10 global holding 40 is not a 40) */
define function "InScale"(x System.Decimal, lo System.Decimal, hi System.Decimal):
  if x is null then null else if x >= lo and x <= hi then x else null

/* the unit of a Quantity as two spellings of it compare equal (tb_common.labunit.key, D-275) */
define function "UnitKey"(Q FHIR.Quantity):
  "Swap"("Swap"("Swap"("Swap"("Swap"("Swap"("Swap"("Swap"("Swap"(Lower(Coalesce(
    if Q.code.value = '' then null else Q.code.value, Q.unit.value, '')),
    '[', ''), ']', ''), '{', ''), '}', ''), '_', ''), ' ', ''), 'µ', 'u'), 'μ', 'u'), '^', '*')

/* a component in the unit its formula expects; null when the recorded unit is not allowed (D-149) */
define function "Conv_creatinine"(O FHIR.Observation):
  if O is null then null
  else case "UnitOf"(O)
    when 'mg/dl' then "ObsValue"(O) * 1.0
    when 'umol/l' then "ObsValue"(O) * 0.01131222
    else null end
define function "Conv_crp"(O FHIR.Observation):
  if O is null then null
  else case "UnitOf"(O)
    when 'mg/dl' then "ObsValue"(O) * 10.0
    when 'mg/l' then "ObsValue"(O) * 1.0
    when 'ug/ml' then "ObsValue"(O) * 1.0
    else null end
define function "Conv_esr"(O FHIR.Observation):
  if O is null then null
  else case "UnitOf"(O)
    when 'mm/(1.h)' then "ObsValue"(O) * 1.0
    when 'mm/1h' then "ObsValue"(O) * 1.0
    when 'mm/h' then "ObsValue"(O) * 1.0
    when 'mm/hr' then "ObsValue"(O) * 1.0
    else null end
define function "Conv_evga"(O FHIR.Observation):
  if O is null then null
  else "InScale"(case "UnitOf"(O)
    when '' then "ObsValue"(O) * 1.0
    when '1' then "ObsValue"(O) * 1.0
    when 'cm' then "ObsValue"(O) * 1.0
    when 'mm' then "ObsValue"(O) * 0.1
    when '{score}' then "ObsValue"(O) * 1.0
    else null end, 0.0, 10.0)
define function "Conv_height"(O FHIR.Observation):
  if O is null then null
  else case "UnitOf"(O)
    when '[in_i]' then "ObsValue"(O) * 2.54
    when 'cm' then "ObsValue"(O) * 1.0
    when 'in' then "ObsValue"(O) * 2.54
    when 'm' then "ObsValue"(O) * 100.0
    when 'mm' then "ObsValue"(O) * 0.1
    else null end
define function "Conv_ptga10"(O FHIR.Observation):
  if O is null then null
  else "InScale"(case "UnitOf"(O)
    when '' then "ObsValue"(O) * 1.0
    when '1' then "ObsValue"(O) * 1.0
    when 'cm' then "ObsValue"(O) * 1.0
    when 'mm' then "ObsValue"(O) * 0.1
    when '{score}' then "ObsValue"(O) * 1.0
    else null end, 0.0, 10.0)
define function "Conv_weight"(O FHIR.Observation):
  if O is null then null
  else case "UnitOf"(O)
    when '[lb_av]' then "ObsValue"(O) * 0.45359237
    when 'g' then "ObsValue"(O) * 0.001
    when 'kg' then "ObsValue"(O) * 1.0
    when 'lb' then "ObsValue"(O) * 0.45359237
    else null end
define function "Conv_basdai_q1"(O FHIR.Observation):
  if O is null then null
  else if "UnitOf"(O) in { '', '1', '{#}', '{count}', '{joints}', '{score}' } then "ObsValue"(O) else null
define function "Conv_basdai_q2"(O FHIR.Observation):
  if O is null then null
  else if "UnitOf"(O) in { '', '1', '{#}', '{count}', '{joints}', '{score}' } then "ObsValue"(O) else null
define function "Conv_basdai_q3"(O FHIR.Observation):
  if O is null then null
  else if "UnitOf"(O) in { '', '1', '{#}', '{count}', '{joints}', '{score}' } then "ObsValue"(O) else null
define function "Conv_basdai_q4"(O FHIR.Observation):
  if O is null then null
  else if "UnitOf"(O) in { '', '1', '{#}', '{count}', '{joints}', '{score}' } then "ObsValue"(O) else null
define function "Conv_basdai_q5"(O FHIR.Observation):
  if O is null then null
  else if "UnitOf"(O) in { '', '1', '{#}', '{count}', '{joints}', '{score}' } then "ObsValue"(O) else null
define function "Conv_basdai_q6"(O FHIR.Observation):
  if O is null then null
  else if "UnitOf"(O) in { '', '1', '{#}', '{count}', '{joints}', '{score}' } then "ObsValue"(O) else null
define function "Conv_ptga"(O FHIR.Observation):
  if O is null then null
  else if "UnitOf"(O) in { '', 'mm' } then "ObsValue"(O) else null
define function "Conv_sjc28"(O FHIR.Observation):
  if O is null then null
  else if "UnitOf"(O) in { '', '1', '{#}', '{count}', '{joints}', '{score}' } then "ObsValue"(O) else null
define function "Conv_tjc28"(O FHIR.Observation):
  if O is null then null
  else if "UnitOf"(O) in { '', '1', '{#}', '{count}', '{joints}', '{score}' } then "ObsValue"(O) else null

/* the same visit: X within the given days of the anchor component's row (D-149) */
define function "SameVisit"(X FHIR.Observation, A FHIR.Observation, maxDays System.Integer):
  if A is null then false
  else Abs((difference in days between "ObsDate"(A) and "ObsDate"(X))) <= maxDays

/* CKD-EPI 2021, race-free; adults only: no value under 18 (D-442) */
define function "EGFR2021"(scr System.Decimal, age System.Integer, female System.Boolean):
  if scr is null or age is null or age < 18 or female is null then null
  else 142.0 * Power(Min({ scr / (if female then 0.7 else 0.9), 1.0 }),
                         if female then -0.241 else -0.302)
       * Power(Max({ scr / (if female then 0.7 else 0.9), 1.0 }), -1.2)
       * Power(0.9938, age)
       * (if female then 1.012 else 1.0)

/* JSN 2009 (Japanese Society of Nephrology; D-149) */
define function "EGFRJSN"(scr System.Decimal, age System.Integer, female System.Boolean):
  if scr is null or scr <= 0 or age is null or age < 18 or female is null then null
  else 194.0 * Power(scr, -1.094) * Power(age, -0.287) * (if female then 0.739 else 1.0)

/* DAS28-ESR if the visit has an ESR row (its value in mm/h, null when its unit does not fit or it is 0), else
   DAS28-CRP (CRP mg/L) */
define function "DAS28"(tjc System.Decimal, sjc System.Decimal, ptga System.Decimal, hasEsr System.Boolean, esr System.Decimal, crp System.Decimal):
  if tjc is null or sjc is null or ptga is null then null
  else if hasEsr then
    if esr is null or esr <= 0 then null
    else 0.56 * Power(tjc, 0.5) + 0.28 * Power(sjc, 0.5) + 0.7 * Ln(esr) + 0.014 * ptga
  else if crp is not null then
    0.56 * Power(tjc, 0.5) + 0.28 * Power(sjc, 0.5) + 0.36 * Ln(crp + 1.0) + 0.014 * ptga + 0.96
  else null

define function "BASDAI"(q1 System.Decimal, q2 System.Decimal, q3 System.Decimal, q4 System.Decimal, q5 System.Decimal, q6 System.Decimal):
  (q1 + q2 + q3 + q4 + (q5 + q6) / 2.0) / 5.0

define function "ASDAS"(back System.Decimal, stiff System.Decimal, ptga System.Decimal, periph System.Decimal, crp System.Decimal):
  0.12 * back + 0.06 * stiff + 0.11 * (ptga / 10.0) + 0.07 * periph + 0.58 * Ln(crp + 1.0)

/* CDAI = TJC28 + SJC28 + PtGA (0-10) + EvGA (0-10) (D-189; catalogue cdai.yaml) */
define function "CDAI"(tjc System.Decimal, sjc System.Decimal, ptga System.Decimal, evga System.Decimal):
  tjc + sjc + ptga + evga

/* SDAI = CDAI + CRP in mg/dL; crp arrives in mg/L from Conv_crp (D-189; catalogue sdai.yaml) */
define function "SDAI"(tjc System.Decimal, sjc System.Decimal, ptga System.Decimal, evga System.Decimal, crp System.Decimal):
  tjc + sjc + ptga + evga + crp / 10.0

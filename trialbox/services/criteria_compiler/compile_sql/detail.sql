LEFT JOIN LATERAL (SELECT (SELECT struct_pack(${fields})
FROM ${table} m JOIN tb_record r ON r.record_id = m.${table}_id
AND r.cdm_table = ${table_literal} JOIN tb_id_map p ON p.id_kind = 'person'
AND p.omop_id = m.person_id WHERE p.source_id = ${row}.pid AND ${key}
AND r.status IN ('coded', 'confirmed', 'signed', 'derived')) AS detail) d ON TRUE

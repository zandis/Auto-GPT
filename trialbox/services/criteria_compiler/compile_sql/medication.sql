SELECT b.pid, b.index_date, x.mid AS oid, ${start} AS effective, (${predicate}) AS row_match,
FALSE AS unit_bad, (${uncertain}) AS undated FROM base b JOIN medication x ON x.pid = b.pid
${detail} WHERE (${match}) AND ((${within}) OR ${start} IS NULL)

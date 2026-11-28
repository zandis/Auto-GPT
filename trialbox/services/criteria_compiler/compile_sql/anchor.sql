, (SELECT a.${column} FROM criterion_anchors a WHERE a.ruleset = ${ruleset}
AND a.pid = p.pid AND a.index_date = i.index_date) AS ${column}

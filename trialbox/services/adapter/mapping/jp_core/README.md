# JP Core mapping (template)

Sites in Japan copy `../tw_core/demo_his.yaml`, switch `meta.profile` URLs to JP Core 1.2.x
(`http://jpfhir.jp/fhir/core/StructureDefinition/JP_*`), and map SS-MIX2 / HIS tables through the same
expression language (see `services/adapter/mapping/engine.py`). The `ssmix2` source reader is a v1.1 item
(DECISIONS D-28); `csv` and `cgrd_sql` work unchanged for Japanese HIS exports.

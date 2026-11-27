# shellcheck shell=bash
# The shell journeys of the e2e-box gate (sourced by run.sh after lib.sh). Each step is a row of metrics/steps.csv.
# A change to the box as installed is made only through deviate() (a DEVIATION row, G5), and only after the step it
# unblocks failed on the box as installed, so the failure is in the results first.
PW=$HERE/pw.sh
FEED=/var/tmp/feed
SRC=/opt/trialbox/deploy/site/sample
MAP=/opt/trialbox/deploy/site/mapping/tw_core/box_site.yaml

j_accounts() { # the IT/admin journey: the first administrator, one account per role, the second-person rule
  local J=ROLE-admin spec u rc
  step $J "first administrator: install password + enrolment code, authenticator, own password" timeout 300 "$PW" acct.js first-admin
  for spec in "crc1 coordinator hospital -" "lpi1 investigator hospital -" "subi1 investigator hospital -" \
    "pi1 investigator hospital -" "smo1 coordinator smo $RS" "cra1 cro cro $RS" "view1 viewer hospital $RS" "stw1 steward hospital -"; do
    read -r u role aff studies <<< "$spec"
    step $J "add account $u ($role, $aff)" timeout 300 "$PW" acct.js add "$u" "$role" "$aff" "$studies" "$u@hospa.test"
  done
  for u in crc1 lpi1 subi1 pi1 smo1 stw1; do step "ROLE-$u" "enrol: code + own password + authenticator" timeout 300 "$PW" acct.js enrol $u; done
  for u in cra1 view1; do step "ROLE-$u" "first sign-in with the one-time password" timeout 300 "$PW" acct.js login $u; done
  timeout 300 "$PW" acct.js add dpo1 privacy hospital - dpo1@hospa.test > "$EV/add-dpo1.txt" 2>&1
  rc=$?
  rec $J "a privacy account after the steward exists waits for a second person" "$([ $rc = 3 ] && echo PASS || echo FAIL)" 0 "rc=$rc (3 = requested)"
  step $J "the steward confirms the privacy account" timeout 300 "$PW" acct.js confirm dpo1 stw1
  step ROLE-dpo1 "enrol: code + own password + authenticator" timeout 300 "$PW" acct.js enrol dpo1
  step $J "users list (console.cli list-users)" vm "sudo docker exec trialbox-console-1 python -m console.cli list-users"
}

mapcheck() {
  vm "sudo docker run --rm --network none --user 0:0 -v /opt/trialbox/deploy/site/mapping:/app/deploy/site/mapping:ro -v $FEED:/export:ro trialbox-py:1.0.0 python tools/mapping_check.py --mapping deploy/site/mapping/tw_core/box_site.yaml --source csv --path /export > /tmp/mc.txt 2>&1; rc=\$?; tail -n 4 /tmp/mc.txt; exit \$rc"
}
declare_tables() { # P-09: the demo_his tables of the synthetic feed, declared in the site mapping
  vm "sudo cp -n $MAP $MAP.e2e-orig && sudo tee -a $MAP > /dev/null" << 'YY'
tables:
  patient: {source: patient, key: mrn, identity: {name: name, national_id: id_no}}
  practitioner: {source: practitioner, key: staff_id}
  encounter: {source: encounter, key: enc_no, delta: updated_at}
  appointment: {source: appointment, key: appt_no}
  diagnosis: {source: diagnosis, key: diag_no, delta: updated_at}
  lab: {source: lab, key: lab_no, delta: updated_at}
  vital: {source: vital, key: vital_no, delta: updated_at}
  medication: {source: medication, key: rx_no, delta: updated_at}
  procedure: {source: procedure, key: proc_no, delta: updated_at}
  report: {source: report, key: rpt_no, delta: updated_at}
  note: {source: note, key: note_no, delta: updated_at}
  claim: {source: claim, key: claim_no, delta: updated_at}
  registry: {source: registry, key: mrn}
YY
}
night() { # snapshot [extra args] : one night of the adapter
  vm "$DC exec -T adapter python -m adapter.cli run --source csv --snapshot $1 ${2:-} > /var/tmp/e2e-night-$1.log 2>&1; rc=\$?; tail -n 6 /var/tmp/e2e-night-$1.log | cut -c1-300; exit \$rc"
}
report() { # snapshot : the night's report and gate
  vm "$DC exec -T adapter python3 - $1" << 'PY'
import json, sys
for f in [f'/data/lake/ndjson/{sys.argv[1]}/ingest_report.json', f'/data/lake/gates/{sys.argv[1]}.json']:
    try:
        d = json.load(open(f))
    except Exception as e:
        print(f, 'unreadable', e)
        continue
    keep = {k: d[k] for k in d if k in ('passed', 'state', 'outcome', 'errors', 'reasons', 'counts', 'validation',
                                        'validator_errors', 'error_rate', 'resources', 'conditions')}
    print(f, json.dumps(keep, ensure_ascii=False)[:1500])
PY
}
counts() {
  psql_wf "select 'omop.person='||(select count(*) from omop.person)||' visit='||(select count(*) from omop.visit_occurrence)||' cond='||(select count(*) from omop.condition_occurrence)||' meas='||(select count(*) from omop.measurement)||' drug='||(select count(*) from omop.drug_exposure)||' note='||(select count(*) from omop.note)"
  vm "sudo docker exec trialbox-db-1 psql -U hapi -d hapi -Atc \"select 'fhir: '||string_agg(res_type||'='||n, ' ') from (select res_type, count(*) n from hfj_resource where res_deleted_at is null group by 1 order by 2 desc limit 12) t\"; $DC exec -T adapter sh -c 'echo CURRENT=\$(cat /data/lake/CURRENT 2>/dev/null)'"
}
feed() { # folder on the VM : its files become the source folder's (in place: the adapter's bind mount keeps the folder)
  vm "sudo find $SRC -mindepth 1 -delete; sudo cp -a $1/. $SRC/; sudo chmod -R a+rX $SRC; ls $SRC | wc -l"
}
totals() { # folder on the VM : the source system's control totals of a clean drop
  vm "sudo python3 - $1" << 'PY'
import csv, json, os, sys
d = sys.argv[1]; out = {}
for f in sorted(os.listdir(d)):
    if f.endswith('.csv'):
        rows = list(csv.DictReader(open(os.path.join(d, f), encoding='utf-8')))
        pc = 'mrn' if rows and 'mrn' in rows[0] else None
        out[f[:-4]] = {'rows': len(rows), 'distinct_patients': len({r[pc] for r in rows if r[pc].strip()}) if pc else None,
                       'max_delta': None, 'patient_column': pc, 'delta_column': None}
json.dump({'tables': out}, open(os.path.join(d, 'control_totals.json'), 'w'), indent=1, sort_keys=True)
print({k: v['rows'] for k, v in out.items()})
PY
}
raise_adapter_cap() { envset TB_MEM_ADAPTER 12g && vm "$DC up -d adapter"; }
smtp_to_sink() { envset SMTP_HOST mail-sink && envset SMTP_PORT 587 && envset SMTP_STARTTLS false && vm "$DC up -d mail-gateway"; }
current() { vm "$DC exec -T adapter cat /data/lake/CURRENT 2> /dev/null" | tr -d '[:space:]'; }
held() { # journey step snapshot log : the night ends non-zero AND the lake's CURRENT has not moved
  local c0 c1 rc
  c0=$(current)
  night "$3" > "$EV/$4.txt" 2>&1
  rc=$?
  c1=$(current)
  rec "$1" "$2" "$([ $rc != 0 ] && [ -n "$c0" ] && [ "$c0" = "$c1" ] && echo PASS || echo FAIL)" 0 "rc=$rc CURRENT $c0 -> $c1 $(tail -c 160 "$EV/$4.txt")"
}
oomed() { vm "sudo docker inspect -f '{{.State.OOMKilled}} {{.RestartCount}}' trialbox-adapter-1; sudo dmesg | grep -c 'Memory cgroup out of memory' || true"; }

j_nights() { # the patient data flow at the declared size: full, delta, cut (with and without totals), shrunken
  local J=DATA-night d1 d2 d3 d4 d5
  d1=$(day -6) d2=$(day -5) d3=$(day -4) d4=$(day -3) d5=$(day -2) # one date per night (identity: -1, disk full: 0)
  if ! step $J "mapping check of the installed site mapping (runbook 01 step 4)" mapcheck; then
    deviate P09-mapping "the feed's 13 tables declared in the site mapping (the installed box_site.yaml maps none)" declare_tables
    step $J "mapping check after declaring the tables" mapcheck
  fi
  step $J "restart the adapter (its mapping and source mount)" vm "$DC restart adapter > /dev/null 2>&1; for i in \$(seq 1 30); do sudo docker inspect -f '{{.State.Health.Status}}' trialbox-adapter-1 | grep -q '^healthy' && break; sleep 5; done; sudo docker inspect -f '{{.State.Health.Status}}' trialbox-adapter-1"
  step $J "memory caps as installed for the declared size" vm "sudo grep -E '^(TB_SITE_PATIENTS|TB_MEM_[A-Z]+)=' /opt/trialbox/deploy/.env"
  step $J "counts before any night" counts
  step $J "N1 source totals written (clean drop)" totals $FEED
  step $J "N1 feed in place" feed $FEED
  if ! step $J "N1 full night under the installed caps" night "$d1"; then
    step $J "N1 adapter memory kill? (OOMKilled restarts; kernel oom lines)" oomed
    if oomed | grep -q '^true\|^[1-9]'; then
      deviate P02-cap "TB_MEM_ADAPTER=12g (the installed cap was not enough for the declared size)" raise_adapter_cap
      waitfor 30 vm "sudo docker inspect -f '{{.State.Health.Status}}' trialbox-adapter-1 | grep -q '^healthy'"
      step $J "N1 full night again under the raised cap" night "$d1"
    fi
  fi
  step $J "N1 report and gate" report "$d1"
  step $J "N1 counts after" counts
  step $J "N2 delta night (--since 2026-09-01)" night "$d2" "--since 2026-09-01"
  step $J "N2 report and gate" report "$d2"
  step $J "N2 counts after" counts
  vm "sudo rm -rf /var/tmp/feedcut; sudo cp -a $FEED /var/tmp/feedcut; f=/var/tmp/feedcut/encounter.csv; s=\$(stat -c %s \$f); sudo truncate -s \$((s/2+7)) \$f" > /dev/null
  step $J "N3 feed cut mid-row (encounter.csv at half), totals of the clean drop kept" feed /var/tmp/feedcut
  held $J "N3 cut night is not published (held or refused; CURRENT unchanged)" "$d3" n3
  step $J "N3 report and gate" report "$d3"
  step $J "N3 counts after" counts
  vm "sudo rm -f /var/tmp/feedcut/control_totals.json" > /dev/null
  step $J "N3b feed cut mid-row, no control totals" feed /var/tmp/feedcut
  held $J "N3b cut night without totals is not published (CURRENT unchanged)" "$d4" n3b
  step $J "N3b counts after" counts
  vm "sudo rm -rf /var/tmp/feedheld; sudo mkdir -p /var/tmp/feedheld; sudo python3 - $FEED /var/tmp/feedheld" > "$EV/held-prep.txt" 2>&1 << 'PY'
import csv, os, sys
src, dst = sys.argv[1], sys.argv[2]
keep = {row['mrn'] for i, row in enumerate(csv.DictReader(open(f'{src}/patient.csv', encoding='utf-8'))) if i % 10 == 0}
for f in os.listdir(src):
    if f.endswith('.csv'):
        r = csv.DictReader(open(f'{src}/{f}', encoding='utf-8'))
        w = csv.DictWriter(open(f'{dst}/{f}', 'w', encoding='utf-8', newline=''), fieldnames=r.fieldnames); w.writeheader()
        w.writerows(row for row in r if 'mrn' not in row or row['mrn'] in keep)
print(len(keep))
PY
  step $J "N4 feed with a tenth of the patients" feed /var/tmp/feedheld
  held $J "N4 shrunken night is held, not published (CURRENT unchanged)" "$d5" n4
  step $J "N4 counts after" counts
  step $J "full feed back in place" feed $FEED
  step $J "night_runs.json (how long the nights took)" vm "$DC exec -T adapter cat /data/lake/night_runs.json | head -c 1500"
}

j_data_extra() { # identity hold (H34-06), terminology update, log retention, the audit head
  local J=DATA-identity
  vm "sudo rm -rf /var/tmp/feedid; sudo cp -a $FEED /var/tmp/feedid; sudo rm -f /var/tmp/feedid/control_totals.json; sudo python3 -" > "$EV/identity-prep.txt" 2>&1 << 'PY'
import csv
p = '/var/tmp/feedid/patient.csv'
rows = list(csv.DictReader(open(p, encoding='utf-8'))); f = list(rows[0])
a, b = dict(rows[10]), dict(rows[11]); b['mrn'] = a['mrn']  # a second person under the first person's chart number
b['sex'] = 'F' if a['sex'] == 'M' else 'M'; b['birth_date'] = '1951-02-03'
rows.insert(12, b)
w = csv.DictWriter(open(p, 'w', encoding='utf-8', newline=''), fieldnames=f); w.writeheader(); w.writerows(rows)
print('planted: one chart number on two people (row 12)')
PY
  step $J "feed with one chart number on two people" feed /var/tmp/feedid
  held $J "H34-06: two people under one chart number are held or refused, never merged (CURRENT unchanged)" "$(day -1)" n5
  vm "sudo grep -oE 'duplicate[^\"]{0,80}|identity[^\"]{0,80}|\"passed\": (true|false)|held[^\"]{0,60}' /var/tmp/e2e-night-$(day -1).log | sort | uniq -c | head -12" > "$EV/n5-why.txt" 2>&1
  step $J "full feed back in place" feed $FEED
  J=DATA-terminology
  step $J "terminology update (deploy/terminology-update.sh)" vm 'cd /opt/trialbox && sudo deploy/terminology-update.sh > /var/tmp/e2e-term.txt 2>&1; rc=$?; tail -n 6 /var/tmp/e2e-term.txt | cut -c1-200; exit $rc'
  step $J "vocabulary releases recorded" psql_wf "select count(*)||' releases; concepts '||(select count(*) from omop.concept) from omop.tb_vocab_release"
  J=DATA-retention
  step $J "log retention (trialbox logs daily)" vm 'cd /opt/trialbox && sudo trialbox logs daily 2>&1 | tail -n 6'
  step $J "audit head signing (trialbox audit-sign)" vm 'cd /opt/trialbox && sudo trialbox audit-sign 2>&1 | tail -n 6'
  step $J "backup status (the hourly check)" vm 'cd /opt/trialbox && sudo trialbox backup-status --json 2>&1 | tail -c 600'
}

models_to_host() { # the judge and the verifier forwarded to the host's served pair; the box's key set to the pair's
  local cf
  vm "sudo tee /opt/trialbox/deploy/site/modelproxy.py > /dev/null" < "$HERE/modelproxy.py"
  vm "sudo tee /opt/trialbox/deploy/site/e2e-models.yml > /dev/null" << YY
services:
  llm-service: {entrypoint: ["python", "/proxy/proxy.py", "http://10.0.2.2:$E2E_JUDGE_PORT"], volumes: ["./site/modelproxy.py:/proxy/proxy.py:ro"], networks: [hostroute]}
  llm-verifier: {entrypoint: ["python", "/proxy/proxy.py", "http://10.0.2.2:$E2E_VERIFIER_PORT"], volumes: ["./site/modelproxy.py:/proxy/proxy.py:ro"], networks: [hostroute]}
networks:
  hostroute: {}
YY
  cf=$(vm "sudo sed -n 's/^COMPOSE_FILE=//p' /opt/trialbox/deploy/.env | tail -1")
  envset COMPOSE_FILE "${cf:+$cf:}site/e2e-models.yml"
  # the key goes on stdin, never on a command line or in a log
  sed -n 's/^VLLM_API_KEY=//p' "$E2E_MODELS_ENV" | vm "set -e; f=/opt/trialbox/deploy/secrets/model/vllm.env; sudo test -f \$f; k=\$(cat); [ -n \"\$k\" ]; sudo sed -i '/^VLLM_API_KEY=/d' \$f; printf 'VLLM_API_KEY=%s\n' \"\$k\" | sudo tee -a \$f > /dev/null; sudo chmod 600 \$f" || return 1
  vm "$DC up -d --wait --force-recreate llm-service llm-verifier gateway 2>&1 | tail -n 3"
}

j_ops() { # support bundle and its synthetic-identifier check, doctor (both forms), selftest, exports, mail
  local J=OPS-support rc
  step $J "support bundle (trialbox support-bundle)" vm 'sudo rm -rf /var/tmp/sb; sudo mkdir -p /var/tmp/sb; cd /opt/trialbox && sudo trialbox support-bundle --out /var/tmp/sb 2>&1 | tail -n 3 && ls /var/tmp/sb'
  step $J "support bundle: the box's own exit scan" vm 'f=$(ls /var/tmp/sb/* | head -1); cd /opt/trialbox && sudo python3 -m tools.data_scan --exits "$f" 2>&1 | tail -n 5'
  vm "sudo python3 - $FEED/patient.csv" > "$EV/sb-ids.txt" 2>&1 << 'PY'
import csv, glob, sys, tarfile, zipfile
rows = list(csv.DictReader(open(sys.argv[1], encoding='utf-8')))[:2000]
needles = {v for r in rows for k, v in r.items() if k in ('mrn', 'name', 'id_no', 'phone') and v and len(v) >= 4}
f = glob.glob('/var/tmp/sb/*')[0]; hits = set(); n = 0
def scan(name, data):
    global n; n += 1; t = data.decode('utf-8', 'ignore')
    hits.update((name, x[:2] + '…') for x in needles if x in t)
if tarfile.is_tarfile(f):
    with tarfile.open(f) as tf:
        for m in tf.getmembers():
            if m.isfile(): scan(m.name, tf.extractfile(m).read())
elif zipfile.is_zipfile(f):
    with zipfile.ZipFile(f) as z:
        for m in z.namelist(): scan(m, z.read(m))
print('members', n, 'needles', len(needles), 'hits', len(hits), sorted(hits)[:5])
raise SystemExit(1 if hits else 0)
PY
  rc=$?
  rec $J "support bundle holds none of 2,000 synthetic patients' MRN/name/id/phone" "$([ $rc = 0 ] && echo PASS || echo FAIL)" 0 "$(tail -c 200 "$EV/sb-ids.txt")"
  J=OPS-doctor
  step $J "trialbox doctor (installed wrapper)" vm 'sudo trialbox doctor > /var/tmp/e2e-doctor.txt 2>&1; rc=$?; echo "rc=$rc PASS=$(grep -c "^PASS" /var/tmp/e2e-doctor.txt) WARN=$(grep -c "^WARN" /var/tmp/e2e-doctor.txt) FAIL=$(grep -c "^FAIL" /var/tmp/e2e-doctor.txt)"; grep "^FAIL" /var/tmp/e2e-doctor.txt | cut -c1-150; exit $rc'
  vm 'sudo cat /var/tmp/e2e-doctor.txt' > "$EV/doctor-installed.txt" 2>&1
  step $J "doctor --env-file deploy/.env (runbook form)" vm 'cd /opt/trialbox && sudo python3 -m tools.trialbox doctor --env-file deploy/.env > /var/tmp/e2e-doctor-env.txt 2>&1; rc=$?; echo "rc=$rc PASS=$(grep -c "^PASS" /var/tmp/e2e-doctor-env.txt) WARN=$(grep -c "^WARN" /var/tmp/e2e-doctor-env.txt) FAIL=$(grep -c "^FAIL" /var/tmp/e2e-doctor-env.txt)"; grep "^FAIL" /var/tmp/e2e-doctor-env.txt | cut -c1-150; exit $rc'
  vm 'sudo cat /var/tmp/e2e-doctor-env.txt' > "$EV/doctor-envfile.txt" 2>&1
  if vm 'cd /opt/trialbox && sudo python3 -m tools.trialbox doctor --help' 2> /dev/null | grep -q -- --strict; then
    step $J "doctor --strict (G2: every readiness item is a FAIL in PRODUCTION)" vm 'cd /opt/trialbox && sudo python3 -m tools.trialbox doctor --strict --env-file deploy/.env > /var/tmp/e2e-doctor-strict.txt 2>&1; rc=$?; grep -cE "^(FAIL|WARN)" /var/tmp/e2e-doctor-strict.txt; tail -n 3 /var/tmp/e2e-doctor-strict.txt | cut -c1-150; exit $rc'
  else
    skip $J "doctor --strict" "this release's doctor has no --strict (G2 not built)"
  fi
  step $J "selftest (pair canary) on the box as installed" vm 'cd /opt/trialbox && sudo timeout 900 trialbox selftest > /var/tmp/e2e-selftest.txt 2>&1; rc=$?; tail -n 5 /var/tmp/e2e-selftest.txt | cut -c1-200; exit $rc'
  vm 'sudo cat /var/tmp/e2e-selftest.txt' > "$EV/selftest-installed.txt" 2>&1
  if [ -n "${E2E_MODELS_ENV:-}" ]; then
    deviate models "COMPOSE_FILE += site/e2e-models.yml (modelproxy.py), vllm.env: the judge and the verifier forwarded to the host's served pair, the box's model key set to the pair's" models_to_host
    step $J "selftest (pair canary) on the served pair" vm 'cd /opt/trialbox && sudo timeout 900 trialbox selftest > /var/tmp/e2e-selftest.txt 2>&1; rc=$?; tail -n 5 /var/tmp/e2e-selftest.txt | cut -c1-200; exit $rc'
    vm 'sudo cat /var/tmp/e2e-selftest.txt' > "$EV/selftest.txt" 2>&1
  else
    skip $J "served models" "no host model pair given (E2E_MODELS_ENV): the box keeps its stand-ins"
  fi
  J=OPS-exports
  step $J "export ledger (trialbox exports)" vm 'cd /opt/trialbox && sudo trialbox exports 2>&1 | tail -n 8'
  step $J "mail outbox status (trialbox mail status)" vm 'cd /opt/trialbox && sudo trialbox mail status 2>&1 | tail -n 8'
  step $J "decommission plan (changes nothing)" vm 'cd /opt/trialbox && sudo trialbox decommission-plan 2>&1 | tail -n 6'
  J=MAIL
  if ! step $J "the install left a mail relay (SMTP_HOST set)" vm "sudo grep -qE '^SMTP_HOST=.' /opt/trialbox/deploy/.env"; then
    deviate P10-smtp "SMTP_HOST=mail-sink, SMTP_PORT=587, SMTP_STARTTLS=false (the rehearsal's sink; the install asks for no relay)" smtp_to_sink
  fi
}

j_walk() { # every GET route as every role against the design table, then every reachable page in three languages
  local U=admin=admin,crc=crc1,pi=pi1,lpi=lpi1,smo=smo1,cra=cra1,viewer=view1,steward=stw1,privacy=dpo1
  local P=rs=$RS,ruleset=$RS,fmt=xlsx T t0
  python3 "$HERE/actions.py" walk-gen "$HERE/../console/data/role_route_matrix.md" $U $P > "$EV/walk-actions.json"
  t0=$(date +%s)
  "$PW" journey.js < "$EV/walk-actions.json" > "$EV/walk.jsonl" 2> "$EV/walk.err"
  T=$(python3 "$HERE/actions.py" walk-cmp "$HERE/../console/data/role_route_matrix.md" $U "$EV/walk.jsonl" "$M/walk.csv" "$EV/walk-actions.json")
  rec ROLE-walk "every GET route as every role vs the design table" "$(echo "$T" | grep -qE 'LEAK|ERROR|DENY|SIGNIN|NORESULT' || [ "$T" = '{}' ] && echo FAIL || echo PASS)" $(($(date +%s) - t0)) "$T"
  python3 "$HERE/actions.py" lang-gen "$M/walk.csv" $P > "$EV/lang-actions.json"
  t0=$(date +%s)
  "$PW" journey.js < "$EV/lang-actions.json" > "$EV/lang.jsonl" 2> "$EV/lang.err"
  T=$(python3 "$HERE/actions.py" lang-sum "$EV/lang.jsonl" "$M/lang.csv")
  rec LANG-scan "zh-TW/en/ja x desktop/phone on every reachable page" "$(echo "$T" | grep -qE '"(raw_key_pages|overflow_pages|wrong_lang_pages|errors)": [1-9]|"pages": 0' && echo FAIL || echo PASS)" $(($(date +%s) - t0)) "$T"
}

redcap_egress() { # RULINGS Q2: the bench's host on the box's own egress table, through the product's documented way
  local hp cur
  hp=$(python3 -c 'import sys, urllib.parse as u; p = u.urlparse(sys.argv[1]); assert p.scheme == "https" and p.hostname; print(f"{p.hostname}:{p.port or 443}")' "$E2E_REDCAP_URL") || return 1
  cur=$(vm "sudo sed -n 's/^EGRESS_EXTRA=//p' /opt/trialbox/deploy/.env | tail -1")
  envset EGRESS_EXTRA "${cur:+$cur,}orchestrator=$hp" || return 1
  vm "cd /opt/trialbox && sudo deploy/network.sh apply --env deploy/.env 2>&1 | tail -n 3 && $DC up -d orchestrator 2>&1 | tail -n 2"
}

edc_pass() { # journey-name label : the EDC actions with the subject from the people journey; the token from a 0600 file
  python3 "$HERE/actions.py" journey edc "$(today)" "" "" "$1" > "$EV/$2-actions.json"
  VARS=$(python3 -c 'import json, sys; t = open(sys.argv[1]).read().strip(); d = json.loads(t) if t else {}; d.update(rcurl=sys.argv[2], today=sys.argv[3], secret_rc=open(sys.argv[4]).read().strip()); print(json.dumps(d))' \
    "$EV/people.vars.json" "$E2E_REDCAP_URL" "$(today)" "$E2E_REDCAP_TOKEN_FILE") jrun "$EV/$2-actions.json" "$2"
}

j_edc() {
  if [ -z "${E2E_REDCAP_URL:-}" ] || [ ! -s "${E2E_REDCAP_TOKEN_FILE:-}" ]; then
    skip EDC-redcap "EDC pre-fill, write-back, read-back" "no REDCap bench given (E2E_REDCAP_URL, E2E_REDCAP_TOKEN_FILE)"
    return
  fi
  edc_pass EDC-redcap-installed edc-installed
  deviate redcap-egress "EGRESS_EXTRA += orchestrator=<the REDCap bench's host:port>, then deploy/network.sh apply (RULINGS Q2)" redcap_egress
  edc_pass EDC-redcap edc
}

j_backup() { # runbook 05: keygen, one encrypted backup to a share, check, verify, the restore drill
  local J=OPS-backup T='cd /opt/trialbox && sudo python3 -m tools.trialbox' F
  if ! step $J "backup key made at install (RULINGS Q1)" vm "sudo test -e /opt/trialbox/deploy/secrets/backup.pub"; then
    deviate P01-keygen "backup.pub made by hand (trialbox backup-keygen, runbook 05): the install made no backup key" \
      vm "sudo mkdir -p /root/envelope && sudo chmod 700 /root/envelope && $T backup-keygen --private /root/envelope/backup.key --public deploy/secrets/backup.pub 2>&1 | tail -n 3 && sudo test -e /opt/trialbox/deploy/secrets/backup.pub"
  fi
  step $J "backup to the share (/srv/e2e-share)" vm "sudo mkdir -p /srv/e2e-share; $T backup --to /srv/e2e-share > /var/tmp/e2e-backup.txt 2>&1; rc=\$?; tail -n 4 /var/tmp/e2e-backup.txt | cut -c1-200; exit \$rc"
  F=$(vm 'ls -t /srv/e2e-share/* 2>/dev/null | head -1')
  if [ -z "$F" ]; then
    rec OPS-restore "restore from a backup" FAIL 0 "no backup was made (see OPS-backup)"
    return
  fi
  step $J "backup-check (no key)" vm "$T backup-check $F 2>&1 | tail -c 500"
  step $J "backup-verify (with the private key)" vm "$T backup-verify $F --key /root/envelope/backup.key 2>&1 | tail -n 4 | cut -c1-250"
  step OPS-restore "restore-drill into scratch databases" vm "$T restore-drill $F --key /root/envelope/backup.key > /var/tmp/e2e-drill.txt 2>&1; rc=\$?; tail -n 6 /var/tmp/e2e-drill.txt | cut -c1-250; exit \$rc"
}

same_state() { # journey step before : PASS when users, delegation, persons and FHIR patients are as before
  local now
  now=$(state | tr '\n' ' ')
  rec "$1" "$2" "$(python3 -c 'import re, sys; k = lambda s: {m[0]: m[1] for m in re.findall(r"(users|delegation|persons|fhir_patients)=(\d+)", s)}; a, b = k(sys.argv[1]), k(sys.argv[2]); print("PASS" if len(a) == 4 and a == b else "FAIL")' "$3" "$now")" 0 "before: $3 | after: $now"
}
state() {
  psql_wf "select 'users='||(select count(*) from auth.users)||' jobs='||(select count(*) from orch.jobs)||' delegation='||(select count(*) from team.delegation)||' persons='||(select count(*) from omop.person)||' audit='||(select count(*) from audit.journal)"
  vm "sudo docker exec trialbox-db-1 psql -U hapi -d hapi -Atc \"select 'fhir_patients='||count(*) from hfj_resource where res_type='Patient' and res_deleted_at is null\"; readlink /opt/trialbox/current; sudo grep -E '^(TB_MEM_ADAPTER|SMTP_HOST)=' /opt/trialbox/deploy/.env | tr '\n' ' '"
}
attach_next() { # hot-plug the next bundle's media and mount the new disk (the one virtio disk not yet mounted)
  "$CTL" attach "$NAME" "$NEXT_IMG" > /dev/null
  sleep 6
  vm 'sudo bash -s' << 'SH'
d=$(lsblk -dn -o NAME,MOUNTPOINT | awk '$1 ~ /^vd/ && $2 == "" {print $1}' | tail -n 1)
mkdir -p /mnt/media-next && mount -o ro,noload "/dev/$d" /mnt/media-next && ls /mnt/media-next
SH
}
cur_ok() { vm "readlink /opt/trialbox/current | grep -q -- '$1'" && healthy; }

j_update() { # the next bundle (media hot-plugged), then the documented downgrade back to the installed one
  local J=OPS-update id1 id2 before
  if [ -z "${NEXT_IMG:-}" ] || [ ! -e "$NEXT_IMG.ready" ]; then
    skip $J "update to the next bundle, downgrade back" "no next bundle's media given (NEXT_IMG and NEXT_IMG.ready)"
    return
  fi
  id1=$(basename "$BUNDLE" .tar)
  id1=${id1#trialbox-}
  id2=$(cat "$NEXT_IMG.ready")
  [[ $id2 =~ ^[A-Za-z0-9._-]+$ ]] || { rec $J "next bundle id" FAIL 0 "not a plain id in $NEXT_IMG.ready"; return; }
  before=$(state | tr '\n' ' ')
  rec $J "state before the update" PASS 0 "$before"
  step $J "next bundle's media attached and mounted read-only" attach_next
  step $J "update (apply_update.sh)" vm "sudo bash -c 'cd /opt/trialbox && tools/apply_update.sh /mnt/media-next/trialbox-$id2.tar > /var/tmp/e2e-upd.log 2>&1; rc=\$?; tail -n 3 /var/tmp/e2e-upd.log | cut -c1-200; exit \$rc'"
  step $J "the next release current and all healthy" waitfor 60 cur_ok "$id2"
  same_state $J "state after the update: the same users, delegation, persons and FHIR patients" "$before"
  step $J "accounts still sign in after the update (crc1)" timeout 300 "$PW" acct.js login crc1
  J=OPS-downgrade
  step $J "downgrade back (--allow-downgrade REASON)" vm "sudo bash -c 'cd /opt/trialbox && tools/apply_update.sh /mnt/media/trialbox-$id1.tar --allow-downgrade \"e2e: back after the update journey\" > /var/tmp/e2e-dg.log 2>&1; rc=\$?; tail -n 3 /var/tmp/e2e-dg.log | cut -c1-200; exit \$rc'"
  step $J "the installed release current and all healthy" waitfor 60 cur_ok "releases/$id1\$"
  same_state $J "state after the downgrade: the same users, delegation, persons and FHIR patients" "$before"
  step $J "accounts sign in after the downgrade (lpi1)" timeout 300 "$PW" acct.js login lpi1
  step $J "audit: update events" psql_wf "select event||'='||count(*) from audit.journal where event like 'update.%' group by event"
}

j_hard_days() { # model down, time zone and clock skew, disk full, power cut in the middle of a night
  local J=OPS-model-down rc d
  step $J "stop the judge and the verifier" vm 'sudo docker stop trialbox-llm-service-1 trialbox-llm-verifier-1 | tr "\n" " "'
  python3 "$HERE/actions.py" journey model-down "$(today)" > "$EV/model-down-actions.json"
  jrun "$EV/model-down-actions.json" model-down
  step $J "start the models again" vm 'sudo docker start trialbox-llm-service-1 trialbox-llm-verifier-1 | tr "\n" " "'
  step $J "healthy again" waitfor 30 healthy
  J=OPS-clock
  step $J "time zone changed (site zone -> UTC)" vm 'sudo timedatectl set-timezone UTC && date'
  step $J "doctor after the zone change" vm 'cd /opt/trialbox && sudo python3 -m tools.trialbox doctor --env-file deploy/.env > /var/tmp/e2e-doc-tz.txt 2>&1; grep -iE "^(FAIL|WARN).*(time|zone|tz|clock)" /var/tmp/e2e-doc-tz.txt | cut -c1-160; exit 0'
  step $J "sign-in under the new zone (pi1)" timeout 300 "$PW" acct.js login pi1
  step $J "clock 10 minutes ahead (no time sync)" vm 'sudo timedatectl set-ntp false 2>/dev/null; sudo date -s "+10 minutes" && date'
  timeout 300 "$PW" acct.js login subi1 > "$EV/clock-login.txt" 2>&1
  rc=$?
  rec $J "sign-in with a 10-minute clock skew is refused at the authenticator step" "$([ $rc != 0 ] && grep -q 'after totp -> /login/totp' "$EV/clock-login.txt" && echo PASS || echo FAIL)" 0 "rc=$rc $(tail -c 200 "$EV/clock-login.txt")"
  step $J "doctor names the skew" vm 'cd /opt/trialbox && sudo python3 -m tools.trialbox doctor --env-file deploy/.env > /var/tmp/e2e-doc-skew.txt 2>&1; grep -iE "(clock|ntp|skew|sync)" /var/tmp/e2e-doc-skew.txt | cut -c1-160 | head -5'
  step $J "clock and zone back" vm "sudo date -s '@$(date +%s)' > /dev/null; sudo timedatectl set-timezone $SITE_TZ; sudo timedatectl set-ntp true 2>/dev/null; date"
  step $J "sign-in works again (subi1)" timeout 300 "$PW" acct.js login subi1
  J=OPS-disk-full
  step $J "fill the docker disk to 100% (fallocate)" vm 'a=$(df --output=avail -B1 /var/lib/docker | tail -1); sudo fallocate -l $((a-4096)) /var/lib/docker/e2e-fill; df -h /var/lib/docker | tail -1'
  step $J "doctor on a full disk" vm 'cd /opt/trialbox && sudo python3 -m tools.trialbox doctor --env-file deploy/.env > /var/tmp/e2e-doc-full.txt 2>&1; grep -iE "^(FAIL|WARN).*(disk|space|full|free)" /var/tmp/e2e-doc-full.txt | cut -c1-160 | head -4; exit 0'
  python3 "$HERE/actions.py" journey disk-full "$(today)" > "$EV/disk-full-actions.json"
  jrun "$EV/disk-full-actions.json" disk-full
  d=$(today)
  held $J "a night on a full disk fails cleanly (CURRENT unchanged)" "$d" night-diskfull
  step $J "free the disk" vm 'sudo rm -f /var/lib/docker/e2e-fill; df -h /var/lib/docker | tail -1'
  step $J "containers healthy after the disk is freed" waitfor 30 healthy
  J=OPS-power-cut
  vm "$DC exec -T adapter sh -c 'nohup python -m adapter.cli run --source csv --snapshot $d > /tmp/pc.log 2>&1 &'" > /dev/null 2>&1
  sleep 150
  step $J "power cut 150 s into a night (qemu killed)" "$CTL" stop "$NAME" --kill
  step $J "power back on" "$CTL" start "$NAME"
  step $J "ssh back" waitfor 60 vm true
  step $J "unseal after the boot (runbook 22)" unseal
  step $J "containers healthy after the power cut" waitfor 90 healthy
  step $J "lake CURRENT intact; the cut night recorded" vm "$DC exec -T adapter sh -c 'cat /data/lake/CURRENT; echo; python3 -c \"import json; d = json.load(open(\\\"/data/lake/night_runs.json\\\")); print([(n[\\\"snapshot\\\"], n.get(\\\"finished\\\")) for n in d[\\\"nights\\\"]][-4:])\"'"
  step $J "FHIR store answers after the power cut" vm "sudo docker exec trialbox-db-1 psql -U hapi -d hapi -Atc \"select 'fhir_patients='||count(*) from hfj_resource where res_type='Patient' and res_deleted_at is null\""
  step $J "doctor after the power cut" vm 'cd /opt/trialbox && sudo python3 -m tools.trialbox doctor --env-file deploy/.env > /var/tmp/e2e-doc-pc.txt 2>&1; echo "rc=$? FAIL=$(grep -c ^FAIL /var/tmp/e2e-doc-pc.txt)"; grep ^FAIL /var/tmp/e2e-doc-pc.txt | cut -c1-150; exit 0'
  step $J "the cut night run again ends" night "$d"
}

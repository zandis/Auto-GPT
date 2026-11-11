# RUNBOOK §11 section: qualify a model pair (D-313)

A model pair is fit to screen patients on a card only when `trialbox eval qualify` has written a `passed` record for
that card's profile. G1b runs through this command. It costs nothing by itself: it calls the models already serving.

## Before the run

1. The pair is serving behind the box's gateway (in TEST: the pins are candidates until promoted), and the weights
   are the release `models/registry.yaml` expects (`expected`: manifest sha256 and revision of each build).
2. The working tree is clean at the commit you want to qualify.
3. Have these at hand:
   - the two weight folders (for the licence file check);
   - the model servers' log files, for example `docker logs <server> > /tmp/judge.log 2>&1`;
   - the gateway's audit folder;
   - the result files of the three evidence steps, each written at the same commit: N-12 (`tools/trec_ct_eval.py`),
     `tools/public_e2e.py` and `tools/goldens.py --check`. Each must hold `passed` (or `ok`) and the git HEAD.
4. The medtxt items need `python -m tools.medtxt_eval fetch` once.

## The run

    python -m tools.trialbox eval qualify --profile rtxpro6000 --gateway-url http://127.0.0.1:8010/v1 \
        --audit-dir /data/audit --server-log /tmp/judge.log --server-log /tmp/verifier.log \
        --model-dir judge=<judge weights> --model-dir verifier=<verifier weights> \
        --evidence n12=<file> --evidence public_e2e=<file> --evidence goldens=<file> --operator <name>

The command prints each step as it ends and writes the record to `eval/qualification/`. Exit 0 means `passed`.
Exit 1 means `failed`; the record's `failed_steps` and each step's `reason` say why. Exit 2 is a usage error.

## After the run

- Check the record: `python -m tools.qualify --check <record> --profile <profile> --environment PRODUCTION`.
- Promote each build of the pair (D-358): `python -m tools.pin_model --promote <build> --record <record>`. It refuses
  a record that does not qualify PRODUCTION or that qualified other weights than the pinned ones. Then restart the
  gateway in PRODUCTION. Before the promotion a PRODUCTION gateway refuses the pair with `champion_unqualified` (or
  `no_eligible_build` for a candidate); run the qualification with the box's gateway in TEST (its calls are D0).
- Commit the record with the pull request that pins the pair.
- A failed record is evidence too: keep it, fix the cause, run again.

## In CI and on a laptop

`python -m tools.trialbox eval qualify --profile ci --stub` runs every step against the stub through an in-process
gateway. It needs no GPU and no network, and its record can never qualify a PRODUCTION champion.

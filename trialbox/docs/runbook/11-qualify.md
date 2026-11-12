# RUNBOOK §11 section: qualify a model pair (D-313)

A model pair is fit to screen patients on a card only when `trialbox eval qualify` has written a `passed` record for
that card's profile. G1b runs through this command. It costs nothing by itself: it calls the models already serving.

## Before the run

1. The pair is serving behind the box's gateway (in TEST: the pins are candidates until promoted), and the weights
   are the release `models/registry.yaml` expects (`expected`: manifest sha256 and revision of each build). The judge
   runs with `--chat-template` on the pinned template (`weights.chat_template` in the site pin, D-392); the serving
   record taken on the box names its sha256 (`chat_template_sha256`).
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
- **A record for a site (HW-003, D-569).** Copy a record taken with real weights on the vendor's card into
  `deploy/qualification/<profile>/` in the release. On a box the install then promotes the pinned pair when the
  record qualified exactly its weights, the model server image of `deploy/images.lock` and the judge's chat
  template (`python -m tools.pin_model --promote-shipped <profile>`), restarts the gateway and runs the canary
  (`python3 -m tools.trialbox selftest`). A passed canary is confirmed (`--confirm-shipped <profile>`) and the
  orchestrator is restarted; a failed one puts the pair back to `candidate` (`--demote-pair <profile>`) and the
  install ends with a FAIL line. An interrupted install runs the canary again the next time. Without a matching record the install ends
  with a FAIL line that says which difference it found, and this section is the way forward on the box.
- A failed record is evidence too: keep it, fix the cause, run again.

## In CI and on a laptop

`python -m tools.trialbox eval qualify --profile ci --stub` runs every step against the stub through an in-process
gateway. It needs no GPU and no network, and its record can never qualify a PRODUCTION champion.

## G1b on the owner's B200 (T-114, D-428)

G1b qualifies the pair in the `shared-quota` profile on the owner's own B200, not on a cloud VM: no `gcloud`, no
rental, no network on the host. The owner or the named operator (Q-12) runs one script there. The host is not
CGMH's: the record says so, carries the host fingerprint, and `doctor --platform` compares it at IQ (RSK-52).

On a development machine, at the commit to qualify:

    python -m tools.b200_qualify build --out /media/usb/tb-b200.tar.gz \
        --image vllm=<docker save tarball of the release vLLM image> \
        --weights <judge build>=<weight folder> --weights <verifier build>=<weight folder>

It writes the bundle and `tb-b200.tar.gz.sha256`. Send the sha256 by another channel (mail, chat), not on the stick.

On the B200, as root, with the site's `.env` (images, model key, `JUDGE_MODEL_DIR`, `VERIFIER_MODEL_DIR`) and a file
of extra `eval qualify` arguments, one per line (`--audit-dir`, `--model-dir`, `--evidence`, as in "The run" above):

    sudo tools/b200_qualify.sh --bundle tb-b200.tar.gz --sha256 <hex> --operator <name> \
        --env-file site.env --qualify-args qualify.args --out /var/tmp/tb-g1b

The script checks the bundle (sha256, then every file against `MANIFEST.json`), loads the images, writes the host
fingerprint, then runs the two layouts of `eval/qualification/b200-layouts.json` (the smallest that fits the pair,
and one larger). For each it asks before it partitions GPU 0 (`--yes` skips the question; anything else on the card
stops), starts the pair on its two MIG instances, captures the serving record and stamps it with the layout's
fingerprint, runs `eval qualify --profile shared-quota`, and stops the pair. MIG stays on with the last layout;
`nvidia-smi -i 0 -mig 0` turns it off.

Send back `g1b-results.tar.gz` only (no weights, images or keys). Check the record and commit it with
`docs/plan/measurements/b200-g1b/` (the record, `G1b.md`, both serving records):

    python -m tools.b200_qualify check g1b-record.json

Exit 0 means `passed`: both layouts measured and qualified, from a bundle built at a commit. A record from stand-ins
(`TB_B200_STANDIN=1`, the tests) is `standin` and never passes.

At CGMH, `doctor --platform` runs `host_match`: it compares the serving record's fingerprint with this host (the GPU
node's labels, or `TB_PLATFORM_HOST_FINGERPRINT`, a file from `python3 -m tools.b200_qualify fingerprint --out
<file>` on the host). Any difference (driver, CUDA, MIG layout, vLLM image digest and the rest) is a WARN that names
each field: re-measure on the site's partition before PQ.

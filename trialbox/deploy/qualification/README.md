# Shipped qualification records (D-569)

One folder per hardware profile: `deploy/qualification/<profile>/<record>.json`. A record is what
`python -m tools.trialbox eval qualify --profile <profile>` wrote on the vendor's card of that type, with real
weights (`qualifies_production: true`). This folder is in the bundle's host tree, so the records reach a box with
the release and are covered by the bundle's signature.

At install, `python -m tools.pin_model --promote-shipped <profile>` promotes the pinned pair from `candidate` to
`champion` when one record here:

- passes `python -m tools.qualify --check <record> --profile <profile> --environment PRODUCTION`;
- names both builds of the pair and qualified exactly the pinned weight manifests;
- was taken with the model server image `deploy/images.lock` names (`steps.serving_record.detail.model_server_image`);
- was taken with the chat template in the judge's pin (`steps.serving_record.detail.chat_template_sha256`).

`deploy/install.sh` then runs the canary on the box (`python3 -m tools.trialbox selftest`). When it fails the pair
is put back to `candidate` (`python -m tools.pin_model --demote-pair <profile>`).

No record is here yet. The first one comes from the run with real weights on the cloud card (lane G): copy the
record from `eval/qualification/` into `<profile>/` in the pull request that ships it. Synthetic data only: a record
holds counts, hashes and versions, never a note.

#!/usr/bin/env bash
# The one build of the box's database image, trialbox-postgres:16-1 (deploy/docker/db.Dockerfile, pinned in
# deploy/images.lock; D-204, D-371). Two callers, so the command cannot drift between them (root review 24, card 24-2):
#   make images              passes its platform and release labels:  deploy/build_db_image.sh $(PLATFORM_ARG) $(OCI_LABELS)
#   deploy/poc.sh            the one-command start, when the image is missing or TB_POC_BUILD=1 (no make, no Maven needed)
# Arguments are passed to `docker build` as they are. Behind a TLS-intercepting proxy the same two settings as every
# other image build apply, read from the environment: HTTPS_PROXY (build on the host network, the proxy handed to apt)
# and TB_EXTRA_CA (the proxy's CA PEM, given to apt as a build secret; see db.Dockerfile's header). Nothing else is
# fetched here: the base comes by its pinned digest and apt fetches only the held package versions of the lock.
set -euo pipefail
cd "$(dirname "$0")/.."
extra=()
if [ -n "${HTTPS_PROXY:-}" ]; then
  extra+=(--network host --build-arg "HTTPS_PROXY=$HTTPS_PROXY" --build-arg "https_proxy=$HTTPS_PROXY")
fi
if [ -n "${TB_EXTRA_CA:-}" ]; then
  extra+=(--secret "id=extra_ca,src=$TB_EXTRA_CA")
fi
exec docker build "$@" ${extra[@]+"${extra[@]}"} -f deploy/docker/db.Dockerfile -t trialbox-postgres:16-1 deploy/docker

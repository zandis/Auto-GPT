# D-622 One dated entry may accept every finding of one package in one third-party image

- **Task:** VLLM-HEADERS (the owner's ruling of 2026-11-12, given in the build session)
- **PR:** this branch (`agent/VLLM-HEADERS-one-package-entry`)
- **Date:** 2026-11-12
- **Status:** accepted
- **Builds on:** D-186 (the allow-list: a finding is accepted only by a written, dated entry), D-340 (dated
  per-image entries for the third-party images)

## Context

The pinned model server image, `vllm/vllm-openai` v0.32.0, carries Ubuntu's kernel headers package
`linux-libc-dev 6.8.0-147.147`. The headers are build-time files; no kernel of that image runs on a box. Every
time the vulnerability database gains kernel findings the gate fails on them: on 2026-11-12 a fresh database
added 135 ids at once and the image gates of the merge train went red on both platforms, with every image of
ours passing. The allow-list already held 257 entries for this one package in this one image, one per id, all
with the same reason.

## Decision

The owner's ruling of 2026-11-12, given in the build session: one dated entry covering any id of that package in
that image, with the reason of the existing entries, review 2026-12-10; the rule to be narrow and built test
first.

1. **The form.** A vulnerability entry with `id: "*"` accepts every finding of the package it names in the image
   it names. It must name one package and one image; the image must be a third-party image of
   `deploy/images.lock`, by its full repository name; it is never an image of ours. It has a reason and a review
   date like every entry, and when the date has passed the gates fail on the findings again.
2. **How it matches.** Only the pinned image: the scanned image must be that repository (in any registry; not a
   longer path that ends the same way) at the digest `deploy/images.lock` pins for it. Another digest, a local
   image under that name with no digest, another image that carries the same package and the lock's own gate
   are not covered; nor is another package of the same image. A finding the scanner could not grade or name is
   never accepted by such an entry.
3. **No dead entries.** An entry for one id of a package in an image that an entry for every id covers is
   refused, so the list does not keep both.
4. **The shipped list.** One such entry: `linux-libc-dev` in `vllm/vllm-openai`, review 2026-12-10. The 257
   per-id entries for the same package and image are removed.

## Consequences

- The 135 ids that failed the image gates on 2026-11-12 are accepted by the entry (checked against the list of
  ids from the failed run); the same package in any other image still fails.
- New kernel findings no longer stop a train or a release for this image until 2026-12-10. On that date the
  entry lapses and the question comes back: a patched vLLM tag, or our own image without the headers.
- The entry holds for the pinned digest only. When the pin moves, the entry covers nothing and the findings of
  the new image fail until they are looked at.

## After the adversarial review (2026-11-12)

Verdict: ship; nothing the reviewer tried made the entry accept a finding outside this package and repository.
Changed after it:

- **The pinned image, not the name.** The first version matched the repository at any tag or digest, and a local
  image merely tagged with the name. The ruling said "the pinned image": the entry now needs the lock's digest.
- A finding with a severity the gate cannot read, or with no id, is not accepted by an entry for every id.
- A lock that is not the expected shape refuses every such entry without a traceback.
- Three documents said "a new finding blocks" for this image without the exception; they say it now.
- **As ruled, and to know:** the entry accepts every severity and findings with no fix yet, for this package in
  this image. The form is open to any third-party image of the lock (test-only ones too); each use is an entry
  the owner approves in a pull request.
- The match is by the package's normalised name; the gate's findings carry no package type, so a language
  package of the same name in the image would be covered too. None exists.


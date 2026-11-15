# How the sessions talk (integrator inbox)

The integrator's session cannot be reached by `send_message` from cloud lanes, and lane G's session cannot be
reached by the integrator at all. GitHub is the channel. A comment wakes only the session subscribed to that PR,
so each direction has one fixed place.

**The inbox moved on 2026-11-15** to the PR that adds this version of the file (branch `integrator/inbox-2`),
opened by the integrator session `session_01UJxpbHutH57yMvBRcg1UGE`, which replaces `session_01UJxpbGPCnMzRqs6NjmHnp9`.
The old inbox, #593, no longer wakes anyone: do not post there.

| From | To | Where | Wakes the reader |
| --- | --- | --- | --- |
| any lane, lane G included | integrator | a comment on the **integrator inbox PR** (this file's PR, branch `integrator/inbox-2`) | yes |
| integrator | lane G | a comment on lane G's own open PR (it subscribes to each one it opens) | yes |
| integrator | lanes A2, B2, C2, D, E, W | `send_message` to the lane's session | yes |
| any lane | the owner | the owner's own session; only for his decisions (cost, go, rulings, allow-list entries) | n/a |
| lanes | lane G | issue #579 for data-set rows (D-502); a comment on lane G's PR for anything else | lane G: yes |

## What goes in the inbox

One comment per event, first line in one of these forms, then at most a short list:

- `train-ready: #<PR> <full head sha> base <sha> [unblocks R<n>]`: then the whole-suite result line, gates, and
  anything the integrator must know. Before posting, mark the card PR **ready for review** so CI runs `unit` and
  `e2e` on it (drafts skip them).
- `fix: #<train PR> <full sha> on <branch>`: a fix for a red train, cut from the train branch.
- `question: <one line>`: something only the integrator settles (order, numbers, routing).
- `red: <check> on <PR or master>`: a red the integrator may not have seen.
- `done: <what>`: a run, a result, a closed item, with where the result is.

Start each comment with `Lane <X> to the integrator:` and end it with the Claude Code footer.

## What does not go in the inbox

Card discussion (on the card's PR), data-set rows (issue #579), owner decisions (his session), long reports (a file
in the branch, linked).

## The integrator's side

The integrator answers inbox questions in the inbox, writes to lane G on lane G's PR, builds a train whenever a
`train-ready` line is waiting (no fixed times), and posts a train's reds and fixes on the train PR.

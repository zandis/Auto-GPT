# D-849 A link with a data access group works with a group user's token

- **Task:** RC13-D (D-521: the owner's REDCap 13.7.23 run privately and offline in lane E's container; synthetic
  projects only)
- **PR:** this branch (`agent/RC13-D-group-bound-token`)
- **Date:** 2026-11-16
- **Status:** proposed (merges on green CI)
- **Builds on:** D-123 (write-back), D-134 (the link as a data-core source), D-142

## Decision

1. Seen on REDCap 13.7: a token of a user who is in a data access group exports that group's records only and never
   the group column, even when asked for it; any import carrying the group column is refused whole, even naming the
   user's own group; and the group list is refused to that user. A site coordinator's token is such a token.
2. `rc_bridge.link.in_group` reads the rows of a link's group: with the column, other groups' rows are left out as
   before; with no row carrying it, the token is a group user's and every row is the group's. `read_back`,
   `LinkSource` and the data core's `RedcapSource` use it; a create through a group user's token sends no group
   column (REDCap puts the new record in the user's group).
3. The token's own group cannot be read through the API by a group user, so it is taken to be the link's group; a
   link whose group differs from its token's reads the token's group. The set-up check of that pairing stays a
   person's.
4. The simulator plays a group user's token (`/sim/token_group`) as 13.7 behaves; the write-back rules reference
   (`writeback.plan`) is unchanged.

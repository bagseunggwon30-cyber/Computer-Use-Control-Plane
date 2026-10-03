# Reviewed legacy registry source refresh

The initial source-only registry checkpoint is retained as baseline provenance:
local `8fafca8cc4b59d86a34ee6674aaea88b97009afb`, public source-equivalent
[`968379e6eca731ff849fd554339601261c291584`](https://github.com/bagseunggwon30-cyber/Computer-Use-Control-Plane/commit/968379e6eca731ff849fd554339601261c291584),
tree `5fb9191301f91e585efe40c8c86c0f74b296f92c`.

The separately reviewed native Raw/Err scalar-copy correction was integrated as
local `ea8fc1c58411fe03a7016badb751b64c8ae2b3b1`. This is a new source revision,
not an assertion that the old public commit contains the correction. The refresh
uses exact Git blobs, so qualification does not depend on fetching a private
local commit identifier:

- Before wrapper blob: `dc4d420158f490000c85e0b8a0eb483f022dcc76`
- After wrapper blob: `8e996169535fb4c6ffa57207711ead9cf85b30df`

The only wrapper delta is two guarded fresh-string copies after the stderr
Get-Content read in `Invoke-NativeHelper`. The regression test reconstructs the
new blob from the old blob using that one exact insertion; any other edit fails.
No blanket normalization, arbitrary edit stripping or regeneration is accepted.
Canonical BOM/CRLF handling remains the original explicitly documented checkout
normalization only.

All 126 previously frozen extent hashes are unchanged; their later line
locations move by two. `Invoke-NativeHelper`, previously protected by the whole
wrapper hash, now has an additional explicit function extent. The total is 127.
The 109 ordered clauses, 108 distinct names, 109 handler relationships and all
safety/confirmation/gate metadata remain identical after excluding only source
line locations. Their before/after invariant SHA-256 is:
`197e928b0dc9b729f7089cffe8ac12e11bc62351990979676c76adf510c2284d`.

A separate metadata correction restores `l5` to the top-level CLI JSON capture
list. The initial extraction accidentally excluded its digit; production already
contains `l5`. A new independent full-list assertion tests all twelve first words
and `l5`/`L5` routing. No production routing changed for this correction.

The existing 21 registry tests and four new refresh tests must all pass. The
candidate CI includes those exact test IDs as required, non-skippable checks.
The live registry remains inert metadata; this refresh does not enable another
host command, change authority, promote a family, or retire PowerShell.

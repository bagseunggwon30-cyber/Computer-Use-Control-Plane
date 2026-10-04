# First retained diagnostic candidate Windows result

[Run 37090071710](https://github.com/bagseunggwon30-cyber/Computer-Use-Control-Plane/actions/runs/37090071710)
tested published commit `7efbf9d21b3916f5789fe1c214a4294127ad0270` and completed
with failure on 2026-10-03 at 02:40:47 UTC. The focused diagnostic job ran
31 Python tests in 530.258 seconds. The fast-contracts job passed.

The new four-route corpus contains 332 inputs. All 332 current retained-original
comparisons matched the pinned original. Twelve inputs differed in at least one
candidate route: eleven pure-candidate comparisons and twelve actual-adapter
comparisons failed. Those 23 subtest failures plus the final partition-count
assertion produced 24 failed assertions. The input, route and assertion counts
are different denominators and must not be added as independent cases.

The complete log confirms differences in:

- Culture-sensitive positive/negative Infinity cast display
- The Korean date representation used in a failed Int32 cast
- Empty and nested PSObject interpolation in audit output
- Boolean file-data conversion during benchmark baseline percentage calculation
- Exact empty/nonempty/nested-object Int32 conversion errors
- Corresponding Brief/JSON-only Console output where applicable

The original 323 production-entry diagnostic cases still passed, with the
existing partition of 287 exact, 26 owned-write failures and ten terminal
postdispatch failures. This result does not qualify the candidate benchmark or
audit replacement. Both original production bodies remain; control-envelope
integer validation and effect authority are unchanged.

Artifact `qualification-diagnostics`, ID `11262567165`, was downloaded and
verified against SHA256
`e93a415dc74d7ca0939a6b752dd53dabda3fced6808c56420185386b5c40f05e`.
It contains all six command logs and the source map. This first gate did not
retain the raw per-route observation arrays; complete logs are not equivalent
to raw capture. Follow-up evidence hardening and exact conversion repairs are
required before qualification. No assertion was weakened or failure allowlisted.

The separately qualified seven-helper retirement remains established by
[full run 37086869922](https://github.com/bagseunggwon30-cyber/Computer-Use-Control-Plane/actions/runs/37086869922)
at `f09e5200a37022fbdf1580b54a3fad232121950c`. The diagnostic candidate adds or
removes no PowerShell source bytes. Main remains outside this migration work.

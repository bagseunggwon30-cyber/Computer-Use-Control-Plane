# History reducer functional taxonomy: df200f07

This is an additional analysis of the immutable evidence from
[Windows run 37096050477](https://github.com/bagseunggwon30-cyber/Computer-Use-Control-Plane/actions/runs/37096050477).
It does not qualify production history, change the original comparison, or repair
any reducer. The [complete machine-readable taxonomy](history-functional-df200f07.json)
contains every case in all six runs, the changed original-repeat cases, source
hashes, raw-output hashes and raw-mismatch artifact hashes. It also records the
exact comparator and analysis-harness bytes used to generate this analysis;
these fingerprints are distinct from the observed Windows source identities.

Both results remain failures: `exact_status=failed-parity` and
`status=failed-functional-parity`. `production_cutover` and
`caller_roundtrip_qualified` remain false.

## Disjoint case categories

The following counts apply independently to each full repeat. Each row sums to
465. The operation denominators are pick 169, stats 136, read 37 and last-good 123.
Both singleton runs have one exact match.

| Runtime | Exact | Allowed representation | Data/selection/shape blocker | Visible serialization blocker | Console/error-only blocker |
| --- | ---: | ---: | ---: | ---: | ---: |
| PS5.1 | 299 | 118 | 48 | 0 | 0 |
| PS7 | 281 | 115 | 19 | 50 | 0 |

Conservative functional blockers are **48/465 for PS5.1 and 69/465 for PS7**.
Across one full repeat of each runtime, there are 580 exact cases, 233 cases
within the approved representation allowances, and 117 blocked cases out of
930. The data/selection subset contains 67 runtime/case combinations, covering
58 distinct fixture IDs. Repeating a fixture does not add a distinct input.

Classification precedence is data/selection/shape, visible serialization,
console/error, allowed representation, exact. Every failed field is retained
alongside the single case category, so mixed failure classes are not discarded.

| Runtime/operation | Exact | Allowed representation | Functional blocker | Denominator |
| --- | ---: | ---: | ---: | ---: |
| PS5 pick | 153 | 0 | 16 | 169 |
| PS5 stats | 6 | 116 | 14 | 136 |
| PS5 read | 33 | 1 | 3 | 37 |
| PS5 last-good | 107 | 1 | 15 | 123 |
| PS7 pick | 167 | 0 | 2 | 169 |
| PS7 stats | 14 | 115 | 7 | 136 |
| PS7 read | 25 | 0 | 12 | 37 |
| PS7 last-good | 75 | 0 | 48 | 123 |

The original exact field differences remain **484 / 484 / 354 / 330** across the
four full runs. Each full run compares five fields for 465 cases (2,325 field
comparisons). The two singleton runs have zero differences. No console or error
fields differ in this observation.

## Narrow comparison policy

`caller-backed-history-values/v1` allows only:

- Numeric CLR-width/type tags invented by the oracle, when mathematical values
  are exactly equal. Numeric JSON lexemes use Python `Decimal`/integers, never
  binary float, tolerances, rounding or numeric/string/boolean coercion.
- Equivalent JSON number spelling and decoded JSON escape spelling.
- Enumeration order of the top-level stats `strategies` Hashtable/count map.

All other record property order, keys, casing/codepoints, full values, strings,
array order/cardinality, missing output, null, errors and Console output remain
strict. Input types and parsing are not normalized before reduction. DateTime
versus String is not an allowed tag change. Equal typed DateTime values do not
waive changed serialized strings.

The reported integer case is intentionally blocked:
`9.223372036854776E+18 - 9223372036854775808 = 192` as exact JSON numbers.
Although a binary double can represent this particular power of two, its emitted
JSON number here does not preserve the original exact decimal value.

## Smallest coherent repairs, with disjoint blocker counts

These categories partition the data blockers; the final row is the additional
serialization class. They are proposed work, not changes in this batch.

| Repair group | PS5 cases | PS7 cases | Evidence/examples |
| --- | ---: | ---: | --- |
| Runtime-specific key merging and label comparison | 25 | 0 | Five cultures × composed/decomposed e-acute key pair, Kelvin key pair, and Hangul label match; selections and map cardinality change. |
| Empty-object strategy interpolation | 2 | 2 | `pick/stats-strategy-interpolation-23`: candidate `@{}` versus original empty string. |
| Parsed data, acceptance and numeric/date values | 6 | 14 | NaN/Infinity; PS7 relaxed member syntax, comment-only input, Microsoft dates, overflow and large integers; includes both mixed-line cases. |
| LastGood pipeline array output shape | 2 | 1 | PS5 `last-good-raw-row-30/32`, PS7 `last-good-raw-row-32`. |
| LastGood equal/missing timestamp sorting | 12 | 0 | Sizes 2,3,5,17,33,100, both equal and missing timestamps; original five-row winner is `s3`, candidate `s0`. |
| LastGood mixed-type timestamp sorting | 1 | 2 | PS5 `last-good-ts-10`; PS7 `last-good-ts-8/9`. |
| Caller-visible timestamp strings | 0 | 50 | 45 LastGood and five Read cases; `...00.0000000Z` versus `...00Z`. Remain blocked absent an identical caller round trip. |
| **Total** | **48** | **69** | |

Do not retune rounding to compensate for parser differences. All seven dedicated
rounding fixtures agree numerically. Mixed stats are wrong because rows differ:
PS5 candidate 24 total / 25% versus original 26 / 23.1%; PS7 candidate 25 total /
7 successes / 28% versus original 30 / 8 / 26.7%.

## Caller evidence and release boundary

The caller audit used local commit `4bb16dc07f6a2b394eb983bc6e18cfe3cc61ab12`;
`df200f07` was not present in that checkout's object database. All four original
helper bodies were independently verified against the immutable qualified source.

- Stats has one caller, `scripts/cucp.ps1:5874`; brief output sorts strategy keys
  at 5876 and JSON emits the map at 5881. Exact values and brief rendering remain
  required; arbitrary map order outside this stats field is not exempted.
- Pick feeds smart-plan at `scripts/cucp.ps1:6010` and execution at 6335.
  `LegacySmartPlanKernel.cs:240` exposes `history_hint`.
  `LegacyExecutionSmartClick.cs:19–21,63,172–189` consumes it for stage selection,
  fallback and output. Selection is an operational contract.
- Read feeds only LastGood (`scripts/cucp.ps1:6547`); LastGood feeds app-profile
  at 6672. `LegacyAppProfileKernel.cs:406–419,439` uses its strategy and exposes
  its complete record. `LegacyStrategyKernel.cs:174` applies an 18-point bonus;
  a changed choice can alter an already-authorized record decision.
- Captures cross JSON at `scripts/cucp.ps1:2442` and are cloned/preserved at
  `LegacyAppProfileKernel.cs:213,263,414,439`. Timestamp spelling can therefore
  be a public string difference. None of the fifty cases is waived here.
- Form/task/workflow wrappers preserve these payloads. Reducers only read data;
  appends remain separate effects (`scripts/cucp.ps1:6336,6679`). No authority,
  no-retry, malformed-input or mutation boundary is weakened.

This comparison only analyzes retained reducer captures. Future promotion still
needs inert caller-roundtrip tests for stats brief/JSON, plan hints, execution
query/effect order, and app-profile scoring/full evidence/authorized append traces.
The historical exact gate continues to return nonzero on its existing failures,
even if the additional functional report would pass.

## Repeated-original nondeterminism

PS5 originals are byte-identical. PS7 originals change only stats strategy-map
order in 41/465 cases: 123 raw field differences, zero functional differences.
For example `stats-keys-invariant-0` changes `UIA,separate` to `separate,UIA`.
The candidate's two runs also reorder maps in 36 PS5-profile and 37 PS7-profile
cases, without changing values. This does not authorize treating equal-timestamp
record selection or arbitrary nested objects as unordered.

## Provenance and reproduction

- Observed candidate revision: `df200f07`; Windows run: `37096050477`.
- Verified downloaded artifact ZIP SHA-256:
  `6b2b30d5d8c91c875940d4f9d573ea47883612166754a796a5c034d10eba84d2`.
- Original source revision: `d4c9660d40c7e909f18afb166a8e846798f63b1d`.
- Original source SHA-256:
  `8a3140745701a828628b13c4741b30063119babbcbd74e5230caae2d49591c4c`.
- Original manifest SHA-256:
  `8cba53d610ec92f31be4a9a3d71b946b14ca8b023cda3f1979cba81fdff7f487`.
- Full 465-case input SHA-256:
  `27a952a9bb2c6e7cf3235bfcc1f3517519ae93bc724c138ce6fb17b7bb86e2b5`.

The JSON artifact additionally preserves every candidate source hash recorded by
the Windows gate. Those are recorded source identities, not a new build claim.
The command verifies the immutable source/input bytes, report identities, all
six process outcomes and raw hashes, and unchanged historical mismatch results.
It fails closed on missing, malformed, oversized, truncated or changed evidence.
It creates its additional output exclusively and refuses to overwrite any file.

```sh
python pcucp-next/packaging/history_functional_comparison.py \
  --evidence-dir /path/to/historyUtf8/differential \
  --output /new/path/history-functional.json
```

Exit 1 is expected for this saved run. Generating a functional report does not
change the source directory. Future history differentials also write a separate
`functional-report.json`; `report.json`, exact mismatches and raw files retain
independent original content and status. No reducer, production caller or
PowerShell source changed in this comparison batch.

# Completion parser and host regression

The completion envelope is JSON. Its integer tokens must be accepted as CLR
`System.Int32` or `System.Int64`, without casting strings, Boolean values or
floating-point values into integers. Interaction exits retain the signed Int32
range; execution and diagnostic exits retain their narrower 0 through 3 range.
JSON depth remains 0 through 100. Validation precedes output and the Int32 casts.

## Confirmed cause

PowerShell 7 calls `JsonConvert.DeserializeObject` and directly transfers each
`JValue.Value` into its result. Newtonsoft's ordinary integer-token parser uses
`Int64TryParse`. A valid small JSON integer therefore does not satisfy an exact
`-is [int]` check in that host. See the primary
[PowerShell 7 implementation](https://github.com/PowerShell/PowerShell/blob/v7.4.6/src/Microsoft.PowerShell.Commands.Utility/commands/utility/WebCmdlet/JsonObject.cs#L148-L169)
and [Newtonsoft integer parsing](https://github.com/JamesNK/Newtonsoft.Json/blob/13.0.3/Src/Newtonsoft.Json/JsonTextReader.cs#L2040-L2044).

The historical Framework implementation uses `JavaScriptSerializer`, while its
Core branch uses Newtonsoft; the maintained PowerShell repository also records
the observed PS5 Int32 / PS7 Int64 difference. See the
[historical implementation](https://github.com/PowerShell/PowerShell/blob/v6.0.0-alpha.9/src/Microsoft.PowerShell.Commands.Utility/commands/utility/WebCmdlet/JsonObject.cs#L42-L72)
and [PowerShell issue 14264](https://github.com/PowerShell/PowerShell/issues/14264).
These sources explain the failure; the tests below require both actual parsers.

## Test boundaries

`test_legacy_execution_completion.py` runs 118 cases under each of Windows
PowerShell 5.1 and PowerShell 7. Each runtime must be present on Windows; neither
is silently skipped there. The accepted cases explicitly assert the parsed CLR
types, exact host return/pipeline output, and JSON or brief Console output.

- Twenty accepted cases cover both depth boundaries, all existing 0 through 3
  exits, signed Int32 interaction endpoints, and brief output
- Seventy-three malformed cases cover null, both Boolean values, strings,
  integral and fractional floats, arrays, objects, Int32 overflow, Int64 endpoints,
  invalid depth and the narrower family exit bounds
- The same 25 malformed execution cases run again after one acknowledged inert
  possible-write dispatch; the twentieth accepted case also follows that dispatch

The visible `legacy-execution-completion.ps1` fixture loads exact unique AST
definitions of the production shared host, loop, codecs, validation, dispatch and
state-change classification. It does not execute the main script. Its only
acquisition stub is `_Trajectory-Append`, which counts a call. Actual Console and
pipeline output are captured. A buffered interaction output marker must remain
unemitted on malformed completion.

The existing `PcuCp.LegacyExecution.ContractTests` executable supplies the inert
process. Its test-only `CompletionTransportFixture` reuses production
`LegacyExecutionSession` for framing, a `TrajectoryAppend` descriptor and its
acknowledgment. A small output writer substitutes only final completion bytes,
preserving malformed JSON value types such as `0.0`. All fixture/log files and
temporary environment directories belong to the enclosing temporary directory.
No native, GUI, input, model or real history implementation is loaded.

For malformed completion after the acknowledged possible write, assertions
require the exact `mutation_may_have_occurred=true; automatic_retry=false;`
error prefix, no Console or pipeline output, one dispatch and exactly one child
start/startup/acknowledgment. The host cannot improve the test by coercing a value,
retrying a request or emitting a report before rejecting it.

## Verification and limits

The existing execution-family discovery pattern `test_legacy_execution*.py`
includes this file. Run it on Windows with the existing SDK and both shells:

```text
python -m unittest discover -s tests/python -p test_legacy_execution_completion.py -v
```

The required Windows result is four tests passed with zero skips. Linux local
verification passed the real C# stream fixture test, including unchanged floating
token bytes and a captured write acknowledgment. The two Windows parser/host tests
are explicitly skipped on Linux, where neither PowerShell runtime is installed;
this is not PS5/PS7 runtime evidence. Python syntax compilation and diff checks
also passed. All 21 existing Pester assertions remain unchanged.

The same representation repair also covers the separately tested protocol
guards for history elapsed time, sleep, precision coordinates/cache age,
app-profile score, diagnostic tail bytes/process ordinals/delay/cache age and UIA
count. Their original Int32, nonnegative, threshold and exact-value constraints
remain. The inert `test_legacy_execution_protocol_integers.py` matrix adds 259
cases per shell: 121 accepted and 138 rejected across 12 fields, including
nullable previous-process ordinals. It uses actual source guards, captured
leaves and each shell's real JSON parser. Both Windows runtimes are mandatory;
local source checks are not parser evidence. Business-logic type tests such as
confidence scoring are unchanged. This does not claim full PS7 semantic parity
for every retained legacy operation or retire any additional source body.

The repaired local cross-platform suite passed 509 tests with 113 explicit
Windows/browser skips; native contract checks passed 12,884 assertions. This
local .NET 8-targeted code used the available .NET 10 runtime with explicit major
roll-forward, so the required Windows .NET 8 and PS5.1/PS7 results remain separate
CI evidence. NuGet vulnerability metadata lookup warned about a read-only user
cache; it was not a successful package security audit.

## Follow-up from run 37066314234

The first repaired full run exposed additional fixture and replay problems.
The completion fixture had consumed startup with a custom reader instead of the
production strict UTF-8 reader and first-BOM-aware startup parser. Its PS5 run
disconnected before completion; the original failing bytes were not captured.
It now links and uses both production components with full validated startup
payloads. Local byte-level tests accept a single initial BOM and reject duplicate
or late BOMs, malformed UTF-8 and a forged startup schema before any dispatch.

The integer fixture had passed raw Hashtable wire nodes into object guards that
receive PSCustomObject nodes after production JSON decoding. Its 49 accepted
wire cases per shell consequently failed before numeric validation, and 71
negative cases per shell rejected prematurely. The fixture now converts only
containers recursively, preserving adversarial scalar CLR types. Every wire
case, including rejected cases, must prove schema readiness and exact target-field
CLR type after decoding before its numeric result is accepted as evidence.

PS7 also exposed a production replay bug: positional `Write-Output -NoEnumerate`
wrapped a buffered string in a collection. The host now emits the already
validated string through named `-InputObject`, matching original scalar output.
The fixture inspects every collected pipeline element's actual CLR type before
JSON serialization, preserving exact order, terminal Int32 exit, and no output
on invalid completion. The 118 completion cases and 259 integer cases per shell
remain required; these repairs do not weaken validation or uncertainty handling.

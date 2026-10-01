# Pure strategy-score migration checkpoint

`LegacyStrategyKernel.Score(args)` accepts bounded JSON snapshots: app_type,
route_order, cdp_probe, uia_probe, labels, persisted_strategy, browser_like,
office_like and no_probe. `Normalize(args)` takes strategy and returns `{value}`.
The proposed compatibility operations are `strategy-score` and `strategy-normalize`.

The implementation never probes CDP/UIA, selects a window, reads/writes history,
starts an application or grants input permission. It ranks only the supplied data.
Weights, reason insertion order, alias merging, suffix removal, final 0–100 clamp,
confidence boundaries and evidence fields follow the pinned PS functions. Unknown
route whitespace is not trimmed. Label uniqueness is case-sensitive linguistic
comparison, not an ordinal set. Windows uses explicit NLS comparisons to avoid
.NET 8 ICU/.NET Framework differences; Linux checks are only partial evidence.

Source basis for label comparison: Microsoft's Select-Object implementation uses a
current-culture, case-sensitive ObjectCommandComparer for default Unique behavior:
https://github.com/PowerShell/PowerShell/blob/master/src/Microsoft.PowerShell.Commands.Utility/commands/utility/Select-Object.cs
The pinned Windows PowerShell 5.1 differential remains the decisive proof rather
than assuming current upstream source guarantees historical behavior.

Qualification fixtures extract `_AppStrategy-NormalizeRoute` and
`_AppProfile-StrategyScore` from tree `bf895d3120dd5e145f360cb1c41e1d79a061d048` and
compare whole outputs, including first recommendation, route order, reasons and
label counts. The matrix includes missing/available/unavailable probes, aliases,
empty entries, duplicate routes, score caps, office/browser combinations, labels
with Unicode canonical variants, and tied custom route names.

Do not retire the original functions until exact Windows differential passes.
Linguistically equivalent distinct custom routes can expose the original PS
hashtable enumeration and unstable-sort behavior; that is a material parity risk,
not permission to weaken assertions or silently impose a new tie-break rule.

The first Windows run (b6a29f0, job 110486690519) passed 82 of 85 cases.
The three failures exposed a key-comparison mismatch: Windows PowerShell 5.1
merges composed é and decomposed e+accent as one route, whereas an ordinal
map did not. The candidate now uses a bounded linear map with explicit Windows
NLS current-culture case-insensitive equality, preserving the first spelling,
accumulated weight and reason order. Hashing with .NET 8 ICU is avoided.
Four isolated canonical-variant cases and complete failure diffs were added;
all original exact assertions remain. This correction still needs Windows
differential qualification before the PowerShell bodies can be retired.

A separate test-only net8 culture harness links the exact candidate source and
changes only its process culture. Ten targeted route/label fixtures are compared
under en-US, ko-KR, tr-TR and invariant cultures against process-local Windows
PowerShell 5.1 cultures. This checks the historical hashtable comparator rather
than assuming an en-US success establishes non-English key merging. It changes
no OS or user settings. The original production 89-case dispatcher check remains.

# Pure legacy safety classifier migration

`LegacySafetyKernel.Classify(args)` accepts an object with `text` (string/null, at
most 262,144 UTF-16 units) and `macro` (string/null, at most 128). Missing values are
empty strings. Unknown/duplicate keys and wrong types fail, never return low risk.
`Truncate(args)` accepts `value` and integer `max` (0–262,144); it returns `{value}`.
The compatibility dispatcher maps operations `safety-classify`/`safety-truncate` to
these methods under `cucp.legacy-compat/v1`. The kernel itself has no PowerShell,
process, filesystem, network, model or desktop dependency.

The classifier preserves the pinned legacy rule patterns and their order, category
weights/reasons, duplicate category vs evidence behavior, macro overrides, maximum
individual weight, summed/capped score, risk levels, both confirmation booleans,
confirmation flag and recommendation strings. In particular, registry keeps the
first system category's weight 70 while its macro override raises total risk to 80.
Broad substring matches and false positives are retained deliberately; this is a
compatibility migration, not a redesign or weakening of confirmation behavior.

Classification is advisory metadata, not authorization. A failure, timeout or malformed
response must block the compatibility caller rather than being interpreted as safe.
The host's confirmation policy remains independent and authoritative.

Windows differential fixtures extract only `_Safety-Truncate` and
`_Classify-SafetyFromText` from pinned tree
`bf895d3120dd5e145f360cb1c41e1d79a061d048`, without executing the full legacy script.
Cases cover English/Korean keywords, macro casing, multiple categories, force,
null/empty input, NUL and UTF-16/emoji truncation boundaries. Exact whole-result
comparison is required before removing any old PS function body. Linux pure tests
are useful but cannot establish Windows PowerShell/.NET serialization parity.

The 57 exact differential cases passed on Windows at checkpoint `2934645`, run `36890543863`. The current PS classifier is a checked compatibility bridge, and its private truncation helper has been removed. The same suite now compares the retained bridge against the pinned original and verifies a missing native host throws without producing a low-risk result. This new bridge still requires its own exact-commit Windows qualification.

Retained compatibility requests now carry the PowerShell caller's current culture. The one-off native pure entry validates the optional bounded culture name, applies it only inside that request, and restores the previous culture in `finally`. It changes no OS settings. The actual classifier bridge adds 32 comparisons spanning en-US, ko-KR, tr-TR and invariant culture, including culture-sensitive regex folding; these are required in current-commit Windows CI.

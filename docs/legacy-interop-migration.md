# Prebuilt legacy Win32 interop

`pcucp-next/dotnet/PcuCp.LegacyInterop` moves three existing C# here-strings into
a real, independently built C# library. It targets **.NET Framework 4.8** and
AnyCPU so Windows PowerShell 5.1 can load it. It is not a renamed PowerShell
script, an encoded script, or a subprocess which compiles C# at runtime.

The public global names remain `CucpNative`, `CucpWin32` and `HelperWin32`.
Nested classes, structs, delegates, constants, methods, field names, P/Invoke
attributes and managed method bodies are retained verbatim. In particular,
the historically different character-set declarations are preserved rather
than silently changing their behavior during extraction.

The source baseline is published commit
`9ffa354b9904235835a7bc6eb78ed8d3d76317c8`, tree
`bf895d3120dd5e145f360cb1c41e1d79a061d048`. Source parity tests address the
immutable tree, which is also available in reconstructed checkouts of that
same snapshot. No full PowerShell source is duplicated in this library.

## Build and deployment interface

From the repository root, with an installed .NET SDK:

```text
python pcucp-next/packaging/publish_legacy_interop.py
```

The default output is `pcucp-next/bin/legacy/PcuCp.LegacyInterop.dll`.
`--output` selects another directory; `--dotnet` selects an installed SDK
executable. The publisher uses an argument array with `shell=False`, checks
the build exit status and requires the expected artifact. Spaces and Unicode
in SDK/output paths do not become shell syntax.

The only package dependency is Microsoft's pinned reference-assembly package,
used privately at **build time**. The DLL requires the machine's .NET Framework
4.8 at runtime. It does not include a CLR, install frameworks, launch an SDK,
download a missing DLL, or fall back to dynamic compilation.

The three PowerShell entry points must be switched together after Windows CI
qualification. One DLL load defines all three types; mixing a DLL loader with
an old `Add-Type` body in the same process can cause a duplicate-type error.
Only the C# literal/compilation step should change. Preserve surrounding error
handling, load flags and the native helper's explicit DPI initialization.
The prebuilt library does not itself remove those remaining PowerShell entry
points or the rest of their orchestration.

## Qualification without desktop actions

Source/publisher checks run on any platform in a full-history Git checkout:

```text
python -m unittest discover -s tests/python -p test_legacy_interop.py -v
dotnet run --project pcucp-next/dotnet/PcuCp.LegacyInterop.ContractTests -c Release
```

The default contract project targets .NET 8 and links the exact C# files. Its
managed checks cover 32/64-bit-sensitive `INPUT` union layout, keyboard/mouse
structures, rectangles, points, monitor layout and key P/Invoke metadata.
It never calls input, clipboard, window enumeration or other desktop methods.
Linux execution is source/ABI evidence, not proof that .NET Framework or
Windows PowerShell can load the deployed DLL.

On Windows, first build the production DLL and set
`CUCP_LEGACY_INTEROP_TEST_DLL` to its absolute path. Then run the same Python
test command. The additional Windows test:

1. Reads only the three original C# literals from the pinned Git tree
2. Compiles them into a separate temporary .NET Framework 4.8 baseline library
3. Builds the contract runner for .NET Framework 4.8 and compares all exported
   interop types, public fields/constants, constructors, methods, parameters,
   P/Invoke and marshalling metadata, struct sizes and field offsets against
   the supplied candidate DLL
4. Relocates that candidate into a Unicode/spaced directory and loads it via
   reflection in an actual Windows PowerShell 5.1 process, checking the target
   framework and all three root type names

Neither baseline nor candidate desktop methods are invoked. Loading is checked
without changing execution policy, interacting with user windows or invoking
the legacy PowerShell entry points. Missing Windows/explicit DLL configuration
causes the Windows-only test to skip; CI must configure that variable so it
cannot mistake a skip for Windows qualification.

This extraction preserves existing API behavior; it neither adds new privilege
boundaries nor claims to repair legacy input races. Interactive application,
clipboard, mixed-DPI, privilege and real input acceptance tests remain separate.


## Qualified loader retirement

Windows qualification passed on commit `293464549f93411f02c8f409822157b9a8cd87b7`, run `36890543863`: exact source identity, 301 reflected API/PInvoke/marshalling/ABI entries and actual PowerShell 5.1 load all matched. The three PowerShell C# literals/runtime compilation calls are now replaced together by small explicit loaders. They use the default published DLL above or the human-configured `CUCP_LEGACY_INTEROP_DLL`; no compile/download fallback exists. A type from a different already-loaded assembly fails closed and asks for a fresh process.

This removes **20,786 bytes of actual PowerShell source** across the three runtimes (11,553 native helper, 8,846 wrapper, 387 helper server), retaining the real C# implementations in the separately compiled library. Surrounding exception/log/load-flag behavior and native-helper DPI initialization remain. The production wrapper/server loader definitions are exercised in separate PowerShell 5.1 processes by the next exact-commit CI, without invoking desktop methods.

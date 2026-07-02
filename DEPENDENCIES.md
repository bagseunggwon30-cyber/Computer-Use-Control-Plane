# Dependencies

CUCP has a stable PowerShell core and a staged `pcucp-next` split. The next
split adds Python standard-library code and a C#/.NET native host project, but
does not add external pip, npm, Go, or Rust package dependencies.

## Runtime

- Windows 10 or Windows 11
- Windows PowerShell 5.1 or PowerShell 7+
- .NET classes available from PowerShell
- Windows UI Automation
- Windows.Media.Ocr for OCR-backed commands

## Optional Capabilities

- Python 3.10+ for `pcucp-next/python/pcucp_cli`
- .NET 8 SDK for `pcucp-next/dotnet/PcuCp.NativeHost`
- Windows SDK APIs exposed by `net8.0-windows10.0.19041.0` for the staged OCR
  route
- Chromium or Electron app launched with a local CDP port for CDP commands
- Pester for the regression tests

```powershell
Install-Module Pester -Scope CurrentUser
```

## Package Manifests

- `requirements.txt` is intentionally empty except for comments because
  `pcucp-next` uses Python standard-library modules only.
- No `package.json` is included because the public runtime does not require
  Node.js packages.

## License Inventory

- Project license: MIT, see `LICENSE`.
- No third-party source package is vendored in this repository.

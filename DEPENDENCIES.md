# Dependencies

CUCP is PowerShell-first and has no npm or pip runtime dependency.

## Runtime

- Windows 10 or Windows 11
- Windows PowerShell 5.1 or PowerShell 7+
- .NET classes available from PowerShell
- Windows UI Automation
- Windows.Media.Ocr for OCR-backed commands

## Optional Capabilities

- Chromium or Electron app launched with a local CDP port for CDP commands
- Pester for the regression tests

```powershell
Install-Module Pester -Scope CurrentUser
```

## Package Manifests

- `requirements.txt` is intentionally empty except for comments because there
  are no Python runtime packages required.
- No `package.json` is included because the public runtime does not require
  Node.js packages.

## License Inventory

- Project license: MIT, see `LICENSE`.
- No third-party source package is vendored in this repository.

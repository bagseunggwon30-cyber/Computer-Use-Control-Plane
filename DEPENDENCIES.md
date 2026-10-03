# Dependencies

Source: Python 3.10+ standard library, Windows UI Automation/Windows.Media.Ocr, and a published .NET 8 native worker. Publishing needs .NET 8 SDK. Portable Windows x64 bundles include Python and a self-contained C# runtime.

Optional Pi: Node 22.19+ and the packages locked in integrations/pi/package-lock.json. Python runtime dependencies are empty. Portable build: Python 3.12 x64 and pcucp-next/packaging/requirements-build.txt. Optional CDP endpoints must already exist and be user-approved.

PowerShell/Pester are not runtime/test prerequisites. Tests use unittest, Node tests and C# contracts. The builder collects runtime licenses; project license is MIT.

# Pester 3.x/4.x compatible read-only smoke tests for the CUCP core.
# Native tests use a published host only: no build, restore, input, or elevation.
# Missing prerequisites are reported as skipped/pending, never as passing tests.

$repoRoot = Split-Path -Parent $PSScriptRoot
$nextRoot = Join-Path $repoRoot "pcucp-next"

function Get-TestPython {
  $candidates = @("python.exe", "py.exe", "python")
  foreach ($candidate in $candidates) {
    $cmd = Get-Command $candidate -ErrorAction SilentlyContinue
    if ($null -ne $cmd) { return $cmd.Source }
  }
  return $null
}


function Test-PcuCpPublishedHost {
  if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) { return $false }
  $path = $env:CUCP_NATIVE_HOST
  if (-not $path) { $path = Join-Path $nextRoot "bin\native\PcuCp.NativeHost.exe" }
  if (-not [IO.Path]::IsPathRooted($path) -or -not (Test-Path -LiteralPath $path -PathType Leaf)) { return $false }
  if ([IO.Path]::GetExtension($path) -eq ".dll") {
    return $null -ne (Get-Command dotnet -ErrorAction SilentlyContinue)
  }
  return [IO.Path]::GetExtension($path) -eq ".exe"
}

function Get-PcuCpSkipParameters {
  param([bool]$Unavailable)
  if (-not $Unavailable) { return @{} }
  $parameters = (Get-Command It -ErrorAction Stop).Parameters
  # Pester versions that expose Skip use it; older versions expose Pending.
  # Both mark the test unexecuted in the report instead of returning a false pass.
  if ($parameters.ContainsKey("Skip")) { return @{ Skip = $true } }
  if ($parameters.ContainsKey("Pending")) { return @{ Pending = $true } }
  throw "This Pester version cannot report skipped tests. Install Pester 3.4 or later."
}

$skipPython = Get-PcuCpSkipParameters -Unavailable (-not (Get-TestPython))
$skipNative = Get-PcuCpSkipParameters -Unavailable ((-not (Get-TestPython)) -or (-not (Test-PcuCpPublishedHost)))
$skipLauncher = Get-PcuCpSkipParameters -Unavailable ((-not (Get-TestPython)) -or ($null -eq (Get-Command powershell.exe -ErrorAction SilentlyContinue)))
$skipNativeLauncher = Get-PcuCpSkipParameters -Unavailable ((-not (Test-PcuCpPublishedHost)) -or (-not (Get-TestPython)) -or ($null -eq (Get-Command powershell.exe -ErrorAction SilentlyContinue)))

function Assert-PcuCpBoundedObservation {
  param($Result, $Payload)
  # An explicit partial observation is expected when UIA exhausts its bounded
  # budget. Actual errors must still fail this smoke test.
  (@("ok", "partial") -contains $Payload.status) | Should Be $true
  if ($Payload.status -eq "ok") {
    $Result.ExitCode | Should Be 0
    @($Payload.errors).Count | Should Be 0
  } else {
    ($Result.ExitCode -ne 0) | Should Be $true
    (@($Payload.errors).Count -gt 0) | Should Be $true
  }
}

function Invoke-PcuCpPython {
  param([string[]]$ArgList)

  $python = Get-TestPython
  if (-not $python) { throw "Python executable not found on PATH" }

  $out = Join-Path $env:TEMP ("pcucp-next-out-" + [guid]::NewGuid().ToString("N") + ".txt")
  $err = Join-Path $env:TEMP ("pcucp-next-err-" + [guid]::NewGuid().ToString("N") + ".txt")
  $pythonPath = Join-Path $nextRoot "python"
  $oldPythonPath = $env:PYTHONPATH
  try {
    $env:PYTHONPATH = $pythonPath
    $proc = Start-Process -FilePath $python -ArgumentList (@("-m", "pcucp_cli") + $ArgList) -RedirectStandardOutput $out -RedirectStandardError $err -NoNewWindow -PassThru -Wait
    $raw = ""
    if (Test-Path -LiteralPath $out) { $raw = Get-Content -LiteralPath $out -Raw -Encoding UTF8 }
    $stderr = ""
    if (Test-Path -LiteralPath $err) { $stderr = Get-Content -LiteralPath $err -Raw -Encoding UTF8 }
    return [pscustomobject]@{ ExitCode = $proc.ExitCode; Raw = $raw; Stderr = $stderr }
  } finally {
    $env:PYTHONPATH = $oldPythonPath
    Remove-Item -LiteralPath $out,$err -Force -ErrorAction SilentlyContinue
  }
}

function New-PcuCpOcrFixturePng {
  param([string]$Path)

  Add-Type -AssemblyName System.Drawing
  $bmp = New-Object System.Drawing.Bitmap 520, 140
  $g = [System.Drawing.Graphics]::FromImage($bmp)
  $g.Clear([System.Drawing.Color]::White)
  $g.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
  $g.TextRenderingHint = [System.Drawing.Text.TextRenderingHint]::AntiAliasGridFit
  $font = New-Object System.Drawing.Font("Segoe UI", 30, [System.Drawing.FontStyle]::Bold)
  $g.DrawString("Send Message", $font, [System.Drawing.Brushes]::Black, 24.0, 36.0)
  $font.Dispose()
  $g.Dispose()
  $bmp.Save($Path, [System.Drawing.Imaging.ImageFormat]::Png)
  $bmp.Dispose()
}

Describe "pcucp-next fast smoke - structure" {
  It "contains the requested multi-runtime layout" {
    @(
      "pcucp-next\powershell\cucp-next.ps1",
      "pcucp-next\python\pcucp_cli\__main__.py",
      "pcucp-next\python\pcucp_cli\cli.py",
      "pcucp-next\python\pcucp_cli\find_label.py",
      "pcucp-next\python\pcucp_cli\native_host.py",
      "pcucp-next\python\pcucp_cli\ocr.py",
      "pcucp-next\python\pcucp_cli\planner.py",
      "pcucp-next\python\pcucp_cli\task_plan.py",
      "pcucp-next\dotnet\PcuCp.NativeHost\PcuCp.NativeHost.csproj",
      "pcucp-next\dotnet\PcuCp.NativeHost\Program.cs",
      "pcucp-next\schemas\command.schema.json",
      "pcucp-next\schemas\observation.schema.json",
      "pcucp-next\config\runtime-profile.json"
    ) | ForEach-Object {
      Test-Path -LiteralPath (Join-Path $repoRoot $_) | Should Be $true
    }
  }

  It "keeps the legacy PowerShell wrapper as a compatibility path" {
    Test-Path -LiteralPath (Join-Path $repoRoot "scripts\cucp.ps1") | Should Be $true
  }
}

Describe "pcucp-next fast smoke - python router" {
  It "reports language roles and source component paths" @skipPython {
    $r = Invoke-PcuCpPython -ArgList @("version", "--json")
    $r.ExitCode | Should Be 0
    $obj = $r.Raw | ConvertFrom-Json
    $obj.schema | Should Be "pcucp.version/v1"
    $obj.status | Should Be "ok"
    $obj.language_roles.powershell | Should Match "legacy"
    $obj.language_roles.python | Should Match "session"
    $obj.language_roles.dotnet | Should Match "Windows"
    $obj.components.python_cli | Should Not BeNullOrEmpty
    $obj.components.native_host_project | Should Not BeNullOrEmpty
    $obj.components.legacy_wrapper | Should Not BeNullOrEmpty
  }

  It "plans read-only commands through Python before native or legacy execution" @skipPython {
    $r = Invoke-PcuCpPython -ArgList @("plan", "--command", "windows", "--json")
    $r.ExitCode | Should Be 0
    $obj = $r.Raw | ConvertFrom-Json
    $obj.schema | Should Be "pcucp.plan/v1"
    $obj.command | Should Be "windows"
    $obj.safety.live_control_required | Should Be $false
    $obj.route.primary | Should Be "dotnet-native-host"
    $obj.route.fallback | Should Be "none"
  }

  It "executes windows observation through Python into the native host" @skipNative {
    $r = Invoke-PcuCpPython -ArgList @("windows", "--json")
    $r.ExitCode | Should Be 0
    $obj = $r.Raw | ConvertFrom-Json
    $obj.schema | Should Be "pcucp.observation/v1"
    $obj.kind | Should Be "windows"
    ($obj.route.primary -eq "dotnet-native-host") | Should Be $true
    ($null -ne $obj.data.count) | Should Be $true
  }

  It "executes UIA tree observation through Python into the native host" @skipNative {
    $r = Invoke-PcuCpPython -ArgList @("uia-tree", "--max-depth", "1", "--json")
    $obj = $r.Raw | ConvertFrom-Json
    Assert-PcuCpBoundedObservation -Result $r -Payload $obj
    $obj.schema | Should Be "pcucp.uia-tree/v1"
    $obj.kind | Should Be "uia-tree"
    $obj.route.primary | Should Be "dotnet-native-host"
    ($null -ne $obj.data.count) | Should Be $true
    if ($obj.data.nodes.Count -gt 0) {
      ($null -ne $obj.data.nodes[0].patterns) | Should Be $true
    }
  }

  It "runs find-label in Python over native window observations" @skipNative {
    $r = Invoke-PcuCpPython -ArgList @("find-label", "--label", "__pcucp_unlikely_label__", "--json")
    $obj = $r.Raw | ConvertFrom-Json
    $obj.schema | Should Be "pcucp.find-label/v1"
    (@("not_found", "partial") -contains $obj.status) | Should Be $true
    if ($obj.status -eq "partial") {
      $r.ExitCode | Should Be 3
      (@($obj.errors).Count -gt 0) | Should Be $true
      (@($obj.providers | Where-Object { $_.status -eq "partial" }).Count -gt 0) | Should Be $true
      @($obj.providers | Where-Object { $_.status -eq "error" }).Count | Should Be 0
    } else {
      $r.ExitCode | Should Be 2
    }
    @($obj.candidates).Count | Should Be 0
    $obj.query.label | Should Be "__pcucp_unlikely_label__"
    $obj.route.primary | Should Be "python-router"
    ($obj.route.observations -contains "dotnet-native-host/windows") | Should Be $true
    ($obj.route.observations -contains "dotnet-native-host/uia-tree") | Should Be $true
    ($null -ne $obj.uia_node_count) | Should Be $true
  }

  It "returns a nonzero native transport error without legacy fallback" @skipPython {
    $oldHost = $env:CUCP_NATIVE_HOST
    try {
      $env:CUCP_NATIVE_HOST = Join-Path ([IO.Path]::GetTempPath()) ([guid]::NewGuid().ToString("N") + ".exe")
      $r = Invoke-PcuCpPython -ArgList @("windows", "--json")
      ($r.ExitCode -ne 0) | Should Be $true
      $obj = $r.Raw | ConvertFrom-Json
      $obj.schema | Should Be "pcucp.native/v1"
      $obj.status | Should Be "error"
      $obj.errors[0].code | Should Be "native_transport_error"
      ($null -eq $obj.route.fallback) | Should Be $true
    } finally {
      $env:CUCP_NATIVE_HOST = $oldHost
    }
  }

  It "creates a Python task-plan with live actions gated by default" @skipPython {
    $r = Invoke-PcuCpPython -ArgList @("task-plan", "--type-text", "hello", "--shortcut", "ctrl+s", "--json")
    $r.ExitCode | Should Be 0
    $obj = $r.Raw | ConvertFrom-Json
    $obj.schema | Should Be "pcucp.task-plan/v1"
    $obj.route.primary | Should Be "python-router"
    $obj.safety.live_control_required | Should Be $true
    $obj.safety.default_allow_live_control | Should Be $false
    $obj.steps.Count | Should Be 2
  }

  It "routes OCR image recognition through Python into the native host" @skipNative {
    $fixture = Join-Path $env:TEMP ("pcucp-next-ocr-" + [guid]::NewGuid().ToString("N") + ".png")
    try {
      New-PcuCpOcrFixturePng -Path $fixture
      $r = Invoke-PcuCpPython -ArgList @("ocr-image", "--path", $fixture, "--json")
      $r.ExitCode | Should Be 0
      $obj = $r.Raw | ConvertFrom-Json
      $obj.schema | Should Be "pcucp.ocr-image/v1"
      $obj.status | Should Be "ok"
      $obj.kind | Should Be "ocr-image"
      $obj.route.primary | Should Be "dotnet-native-host"
      ($obj.text -match "Send|Message") | Should Be $true
    } finally {
      Remove-Item -LiteralPath $fixture -Force -ErrorAction SilentlyContinue
    }
  }

  It "finds OCR text through Python over native OCR image output" @skipNative {
    $fixture = Join-Path $env:TEMP ("pcucp-next-ocr-find-" + [guid]::NewGuid().ToString("N") + ".png")
    try {
      New-PcuCpOcrFixturePng -Path $fixture
      $r = Invoke-PcuCpPython -ArgList @("ocr-find-text", "--path", $fixture, "--text", "Send", "--json")
      $r.ExitCode | Should Be 0
      $obj = $r.Raw | ConvertFrom-Json
      $obj.schema | Should Be "pcucp.ocr-find-text/v1"
      $obj.kind | Should Be "ocr-find-text"
      $obj.route.primary | Should Be "python-router"
      $obj.route.observation | Should Be "dotnet-native-host/ocr-image"
      $obj.status | Should Be "ok"
      ($obj.top.text -match "Send") | Should Be $true
      ($obj.top.score -ge 60) | Should Be $true
    } finally {
      Remove-Item -LiteralPath $fixture -Force -ErrorAction SilentlyContinue
    }
  }
}

Describe "pcucp-next fast smoke - thin launcher" {
  It "delegates version requests to the Python router" @skipLauncher {
    $launcher = Join-Path $nextRoot "powershell\cucp-next.ps1"
    $out = Join-Path $env:TEMP ("pcucp-next-launcher-out-" + [guid]::NewGuid().ToString("N") + ".txt")
    $err = Join-Path $env:TEMP ("pcucp-next-launcher-err-" + [guid]::NewGuid().ToString("N") + ".txt")
    try {
      $proc = Start-Process -FilePath "powershell.exe" -ArgumentList @(
        "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $launcher, "version", "--json"
      ) -RedirectStandardOutput $out -RedirectStandardError $err -NoNewWindow -PassThru -Wait
      $raw = Get-Content -LiteralPath $out -Raw -Encoding UTF8
      $proc.ExitCode | Should Be 0
      $obj = $raw | ConvertFrom-Json
      $obj.schema | Should Be "pcucp.version/v1"
    } finally {
      Remove-Item -LiteralPath $out,$err -Force -ErrorAction SilentlyContinue
    }
  }

  It "delegates windows observation to the Python/native path" @skipNativeLauncher {
    $launcher = Join-Path $nextRoot "powershell\cucp-next.ps1"
    $out = Join-Path $env:TEMP ("pcucp-next-launcher-windows-out-" + [guid]::NewGuid().ToString("N") + ".txt")
    $err = Join-Path $env:TEMP ("pcucp-next-launcher-windows-err-" + [guid]::NewGuid().ToString("N") + ".txt")
    try {
      $proc = Start-Process -FilePath "powershell.exe" -ArgumentList @(
        "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $launcher, "windows", "--json"
      ) -RedirectStandardOutput $out -RedirectStandardError $err -NoNewWindow -PassThru -Wait
      $raw = Get-Content -LiteralPath $out -Raw -Encoding UTF8
      $proc.ExitCode | Should Be 0
      $obj = $raw | ConvertFrom-Json
      $obj.schema | Should Be "pcucp.observation/v1"
      $obj.kind | Should Be "windows"
      $obj.route.primary | Should Be "dotnet-native-host"
    } finally {
      Remove-Item -LiteralPath $out,$err -Force -ErrorAction SilentlyContinue
    }
  }

  It "delegates UIA tree observation to the Python/native path" @skipNativeLauncher {
    $launcher = Join-Path $nextRoot "powershell\cucp-next.ps1"
    $out = Join-Path $env:TEMP ("pcucp-next-launcher-uia-out-" + [guid]::NewGuid().ToString("N") + ".txt")
    $err = Join-Path $env:TEMP ("pcucp-next-launcher-uia-err-" + [guid]::NewGuid().ToString("N") + ".txt")
    try {
      $proc = Start-Process -FilePath "powershell.exe" -ArgumentList @(
        "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $launcher, "uia-tree", "--max-depth", "1", "--json"
      ) -RedirectStandardOutput $out -RedirectStandardError $err -NoNewWindow -PassThru -Wait
      $raw = Get-Content -LiteralPath $out -Raw -Encoding UTF8
      $obj = $raw | ConvertFrom-Json
      Assert-PcuCpBoundedObservation -Result $proc -Payload $obj
      $obj.schema | Should Be "pcucp.uia-tree/v1"
      $obj.kind | Should Be "uia-tree"
      $obj.route.primary | Should Be "dotnet-native-host"
    } finally {
      Remove-Item -LiteralPath $out,$err -Force -ErrorAction SilentlyContinue
    }
  }

  It "delegates OCR image recognition to the Python/native path" @skipNativeLauncher {
    $launcher = Join-Path $nextRoot "powershell\cucp-next.ps1"
    $fixture = Join-Path $env:TEMP ("pcucp-next-launcher-ocr-" + [guid]::NewGuid().ToString("N") + ".png")
    $out = Join-Path $env:TEMP ("pcucp-next-launcher-ocr-out-" + [guid]::NewGuid().ToString("N") + ".txt")
    $err = Join-Path $env:TEMP ("pcucp-next-launcher-ocr-err-" + [guid]::NewGuid().ToString("N") + ".txt")
    try {
      New-PcuCpOcrFixturePng -Path $fixture
      $proc = Start-Process -FilePath "powershell.exe" -ArgumentList @(
        "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $launcher, "ocr-image", "--path", $fixture, "--json"
      ) -RedirectStandardOutput $out -RedirectStandardError $err -NoNewWindow -PassThru -Wait
      $proc.ExitCode | Should Be 0
      $raw = Get-Content -LiteralPath $out -Raw -Encoding UTF8
      $obj = $raw | ConvertFrom-Json
      $obj.schema | Should Be "pcucp.ocr-image/v1"
      $obj.status | Should Be "ok"
      $obj.kind | Should Be "ocr-image"
      $obj.route.primary | Should Be "dotnet-native-host"
    } finally {
      Remove-Item -LiteralPath $fixture,$out,$err -Force -ErrorAction SilentlyContinue
    }
  }
}

Describe "pcucp-next fast smoke - schemas and native host" {
  It "ships parseable JSON schemas and profile config" {
    @(
      "pcucp-next\schemas\command.schema.json",
      "pcucp-next\schemas\observation.schema.json",
      "pcucp-next\config\runtime-profile.json"
    ) | ForEach-Object {
      $raw = Get-Content -LiteralPath (Join-Path $repoRoot $_) -Raw -Encoding UTF8
      ($raw | ConvertFrom-Json) | Should Not BeNullOrEmpty
    }
  }

  It "defines a Windows native host project without adding external packages" {
    $csproj = Get-Content -LiteralPath (Join-Path $repoRoot "pcucp-next\dotnet\PcuCp.NativeHost\PcuCp.NativeHost.csproj") -Raw -Encoding UTF8
    ($csproj -match "<TargetFramework>net8.0-windows10.0.19041.0</TargetFramework>") | Should Be $true
    ($csproj -match "<PackageReference") | Should Be $false
  }

  It "runs the published native host without building a project" @skipNative {
    $hostPath = $env:CUCP_NATIVE_HOST
    if (-not $hostPath) { $hostPath = Join-Path $nextRoot "bin\native\PcuCp.NativeHost.exe" }
    if ([IO.Path]::GetExtension($hostPath) -eq ".dll") {
      $raw = & dotnet $hostPath version
    } else {
      $raw = & $hostPath version
    }
    $LASTEXITCODE | Should Be 0
    $obj = ($raw -join "`n") | ConvertFrom-Json
    $obj.schema | Should Be "pcucp.native/v1"
    $obj.status | Should Be "ok"
    $obj.kind | Should Be "version"
    $obj.data.component | Should Be "PcuCp.NativeHost"
  }
}

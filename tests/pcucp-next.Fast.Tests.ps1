# Pester 3.x compatible fast smoke tests for the next-generation CUCP split.
# This suite verifies that the multi-runtime skeleton is real and executable
# without requiring live desktop control, dotnet restore, or long-running tests.

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

function Invoke-PcuCpPython {
  param([string[]]$ArgList)

  $python = Get-TestPython
  if (-not $python) { throw "Python executable not found on PATH" }

  $out = Join-Path $env:TEMP ("pcucp-next-out-" + [guid]::NewGuid().ToString("N") + ".txt")
  $err = Join-Path $env:TEMP ("pcucp-next-err-" + [guid]::NewGuid().ToString("N") + ".txt")
  $pythonPath = Join-Path $nextRoot "python"
  try {
    $env:PYTHONPATH = $pythonPath
    $proc = Start-Process -FilePath $python -ArgumentList (@("-m", "pcucp_cli") + $ArgList) -RedirectStandardOutput $out -RedirectStandardError $err -NoNewWindow -PassThru -Wait
    $raw = ""
    if (Test-Path -LiteralPath $out) { $raw = Get-Content -LiteralPath $out -Raw -Encoding UTF8 }
    $stderr = ""
    if (Test-Path -LiteralPath $err) { $stderr = Get-Content -LiteralPath $err -Raw -Encoding UTF8 }
    return [pscustomobject]@{ ExitCode = $proc.ExitCode; Raw = $raw; Stderr = $stderr }
  } finally {
    Remove-Item -LiteralPath $out,$err -Force -ErrorAction SilentlyContinue
  }
}

Describe "pcucp-next fast smoke - structure" {
  It "contains the requested multi-runtime layout" {
    @(
      "pcucp-next\powershell\cucp-next.ps1",
      "pcucp-next\python\pcucp_cli\__main__.py",
      "pcucp-next\python\pcucp_cli\cli.py",
      "pcucp-next\python\pcucp_cli\planner.py",
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
  It "reports the target language split and component paths" {
    $r = Invoke-PcuCpPython -ArgList @("version", "--json")
    $r.ExitCode | Should Be 0
    $obj = $r.Raw | ConvertFrom-Json
    $obj.schema | Should Be "pcucp.version/v1"
    $obj.status | Should Be "ok"
    $obj.language_targets.powershell | Should Be "15-25%"
    $obj.language_targets.python | Should Be "35-45%"
    $obj.language_targets.dotnet | Should Be "20-30%"
    $obj.components.python_cli | Should Not BeNullOrEmpty
    $obj.components.native_host_project | Should Not BeNullOrEmpty
    $obj.components.legacy_wrapper | Should Not BeNullOrEmpty
  }

  It "plans read-only commands through Python before native or legacy execution" {
    $r = Invoke-PcuCpPython -ArgList @("plan", "--command", "windows", "--json")
    $r.ExitCode | Should Be 0
    $obj = $r.Raw | ConvertFrom-Json
    $obj.schema | Should Be "pcucp.plan/v1"
    $obj.command | Should Be "windows"
    $obj.safety.live_control_required | Should Be $false
    $obj.route.primary | Should Be "dotnet-native-host"
    $obj.route.fallback | Should Be "legacy-powershell"
  }
}

Describe "pcucp-next fast smoke - thin launcher" {
  It "delegates version requests to the Python router" {
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
    ($csproj -match "<TargetFramework>net8.0-windows</TargetFramework>") | Should Be $true
    ($csproj -match "<PackageReference") | Should Be $false
  }

  It "builds and runs the native host window observation when dotnet is available" {
    if (-not (Get-Command dotnet -ErrorAction SilentlyContinue)) { return }
    $project = Join-Path $repoRoot "pcucp-next\dotnet\PcuCp.NativeHost\PcuCp.NativeHost.csproj"
    $build = & dotnet build $project --nologo --verbosity quiet 2>&1
    $LASTEXITCODE | Should Be 0
    $raw = & dotnet run --project $project --no-build -- windows 2>&1
    $LASTEXITCODE | Should Be 0
    $obj = ($raw -join "`n") | ConvertFrom-Json
    $obj.schema | Should Be "pcucp.observation/v1"
    $obj.kind | Should Be "windows"
  }
}

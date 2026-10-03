[CmdletBinding(PositionalBinding = $false)]
param(
  [Alias('AllowLive')]
  [switch]$AllowLiveControl,
  [switch]$Quiet,
  [switch]$Brief,
  [Alias('CacheSec')]
  [int]$CacheSeconds = 2,
  [Alias('TimeoutMs','InvokeTimeout')]
  [int]$InvokeTimeoutMs = 30000,
  [Parameter(ValueFromRemainingArguments = $true)]
  [string[]]$CucpArgs
)

# Strip a leading "--" only if it has already reached the argument array.
# This cannot protect the native powershell.exe -File parameter-binding boundary.
# Inside PowerShell, pass option-like data through the named -CucpArgs string array.
# Internal planning queries use a fixed stdin bootstrap for that typed binding.
if ($CucpArgs -and $CucpArgs.Count -gt 0 -and $CucpArgs[0] -eq "--") {
  if ($CucpArgs.Count -gt 1) {
    $CucpArgs = $CucpArgs[1..($CucpArgs.Count - 1)]
  } else {
    $CucpArgs = @()
  }
}

# ============================================================================
# CUCP Wrapper - Claude Computer Use grade control plane
# ============================================================================
# CUCP Wrapper - Claude Computer Use grade control plane for Windows
# ============================================================================
# 이 스크립트는 로컬 CUCP CLI 위에 다음 기능을 추가합니다:
#  - Observation cache + automatic observation_id injection (--after)
#  - Label-based grounding: 좌표 대신 텍스트 라벨로 클릭/입력
#  - Composite macros: wait-window, click-label, fill-label, goal 등 50+ 매크로
#  - Brief output mode: 모델 루프용 한 줄 결과
#  - UTF-8 safe output + persistent audit log
#  - Hard live-control gate: -AllowLiveControl 없으면 라이브 조작 전부 차단
#  - Win32 deterministic fallback: helper 없어도 window 목록 항상 가능
#  - Unified observation envelope (cucp.observation/v1)
# ============================================================================

$ErrorActionPreference = "Stop"

# Some hosts inject both `Path` and `PATH` into the process environment. Windows
# treats them as the same variable, but Windows PowerShell 5 can throw
# "item has already been added" when launching child processes. Keep canonical
# `Path` and remove only the duplicate uppercase spelling from this process.
try {
  $processEnv = [System.Environment]::GetEnvironmentVariables("Process")
  if ($processEnv.Contains("Path") -and $processEnv.Contains("PATH")) {
    [System.Environment]::SetEnvironmentVariable("PATH", $null, "Process")
  }
} catch { }

# ----- console encoding -----------------------------------------------------
# PowerShell 5.x 기본 인코딩이 CP949라 한글이 깨질 수 있음. UTF-8로 강제.
try {
  [System.Console]::OutputEncoding = [System.Text.Encoding]::UTF8
  $OutputEncoding = [System.Text.Encoding]::UTF8
  if ($PSVersionTable.PSVersion.Major -ge 7 -and $PSStyle) {
    $PSStyle.OutputRendering = "Host"
  }
} catch { }

# ----- paths ----------------------------------------------------------------
# cli.mjs 경로 자동 탐색 순서:
#   1. 환경변수 CUCP_CLI_PATH (사용자가 명시 지정)
#   2. 스크립트 위치 기준 상대 경로 (스킬 폴더에 cli/ 번들된 경우)
#   3. 사용자 홈 기준 일반 설치 경로들
#   4. PATH에서 node + cucp 탐색
# 이 방식으로 하드코딩 없이 어느 PC에서도 동작.
#
# IMPORTANT: 잘못된 cli.mjs (예: CUCP Lite 같은 판매용 워크플로 검증 도구)를
# 자동으로 잡지 않도록 검증합니다. 진짜 desktop control CLI는
# package.json 의 name == "computer-use-control-plane" 또는 cli.mjs 안에
# "ControlPlane" / "observe appshot" 키워드가 존재해야 합니다.
function _Validate-CliMjs {
  param([string]$Path)
  if (-not $Path -or -not (Test-Path -LiteralPath $Path)) { return $false }
  try {
    # 1) package.json 검사 (있으면 가장 강력한 신호)
    $dir = Split-Path -Parent $Path
    $pkgPath = Join-Path $dir "..\package.json"
    if (Test-Path -LiteralPath $pkgPath) {
      try {
        $pkg = Get-Content -LiteralPath $pkgPath -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($pkg.name -eq "computer-use-control-plane") { return $true }
        # cucp-lite 같은 다른 패키지는 거부
        if ($pkg.name -and $pkg.name -ne "computer-use-control-plane") { return $false }
      } catch { }
    }
    # 2) cli.mjs 내용에 ControlPlane import 또는 observe appshot 명령이 있는지
    $head = Get-Content -LiteralPath $Path -TotalCount 60 -Encoding UTF8 -ErrorAction SilentlyContinue
    if (-not $head) { return $false }
    $headStr = $head -join "`n"
    if ($headStr -match 'ControlPlane|control-plane\.mjs|observeAppshot|"observe"\s+&&\s+subcommand') {
      return $true
    }
    # 3) 명백히 다른 도구의 시그니처면 거부
    if ($headStr -match 'CUCP Lite|cucp-lite|workflow.*score|wizard\s+\[out\.json\]') {
      return $false
    }
    return $false
  } catch { return $false }
}

function _Find-CliPath {
  # 1) 환경변수 명시 지정
  if ($env:CUCP_CLI_PATH -and (Test-Path -LiteralPath $env:CUCP_CLI_PATH)) {
    if (_Validate-CliMjs $env:CUCP_CLI_PATH) { return $env:CUCP_CLI_PATH }
  }
  # 2) 스킬 폴더 내 번들 (cli/cli.mjs 또는 cli/src/cli.mjs)
  $scriptDir = $PSScriptRoot
  if (-not $scriptDir) { $scriptDir = Split-Path -Parent $MyInvocation.ScriptName }
  $bundleCandidates = @(
    (Join-Path $scriptDir "..\cli\cli.mjs"),
    (Join-Path $scriptDir "..\cli\src\cli.mjs"),
    (Join-Path $scriptDir "cli.mjs")
  )
  foreach ($c in $bundleCandidates) {
    $resolved = [System.IO.Path]::GetFullPath($c)
    if (_Validate-CliMjs $resolved) { return $resolved }
  }
  # 3) 홈 디렉토리 기준 일반 설치 경로
  $homeCandidates = @(
    (Join-Path $env:USERPROFILE "cucp\src\cli.mjs"),
    (Join-Path $env:USERPROFILE ".cucp\src\cli.mjs"),
    (Join-Path $env:USERPROFILE "Documents\cucp\src\cli.mjs")
  )
  foreach ($c in $homeCandidates) {
    if (_Validate-CliMjs $c) { return $c }
  }
  # 4) 개발 환경 fallback: Documents\Codex 하위에서 검증을 통과한 cli.mjs만
  #    Lite 등 잘못된 CLI는 _Validate-CliMjs 가 거부함.
  # v1.6.0 perf: 재귀 walking 결과 캐시. 캐시 파일 없거나 stale 시에만 스캔.
  $devBase = Join-Path $env:USERPROFILE "Documents\Codex"
  if (Test-Path -LiteralPath $devBase) {
    # 캐시 우선 — wrapper-cache 디렉터리에 cli-path.txt 가 있으면 그 경로 검증만
    $cacheDir = Join-Path $env:TEMP "computer-use-control-plane\wrapper-cache"
    $cliCacheFile = Join-Path $cacheDir "cli-path.txt"
    if (Test-Path -LiteralPath $cliCacheFile) {
      try {
        $cached = (Get-Content -LiteralPath $cliCacheFile -Raw -Encoding UTF8).Trim()
        if ($cached -and (_Validate-CliMjs $cached)) { return $cached }
      } catch { }
    }
    # cache miss → 1회 재귀 스캔 후 결과를 캐시 파일에 저장
    $found = Get-ChildItem -LiteralPath $devBase -Recurse -Filter "cli.mjs" -ErrorAction SilentlyContinue |
      Where-Object { $_.FullName -match "src[/\\]cli\.mjs$" } |
      Sort-Object LastWriteTime -Descending
    foreach ($f in $found) {
      if (_Validate-CliMjs $f.FullName) {
        try {
          if (-not (Test-Path -LiteralPath $cacheDir)) {
            New-Item -ItemType Directory -Path $cacheDir -Force | Out-Null
          }
          Set-Content -LiteralPath $cliCacheFile -Value $f.FullName -Encoding UTF8 -NoNewline -ErrorAction SilentlyContinue
        } catch { }
        return $f.FullName
      }
    }
  }
  return $null
}

$Script:CliPath  = _Find-CliPath
$Script:AuditDir = Join-Path $env:TEMP "computer-use-control-plane"
$Script:CacheDir = Join-Path $Script:AuditDir "wrapper-cache"
$Script:WrapperLog = Join-Path $Script:AuditDir "cucp-wrapper.log"
$Script:InvokeTimeoutMs = [Math]::Max(1000, $InvokeTimeoutMs)

# ----- skill version --------------------------------------------------------
# Single source of truth for skill (wrapper) version. CHANGELOG/README 와 동기화.
# Get-CucpVersionReport 가 이 상수 + cli/package.json + helper-server 헤더를 합쳐
# `cucp.version/v1` envelope 으로 통합 출력.
# v2.3.0: daemon serve (single-shot 가속 정공법) + autostart(v2.2.0) 포함.
$Script:SkillVersion = "2.4.1"

# ----- platform detection (v1.9.0 honest stub) -----------------------------
# CUCP 의 actuation / OCR / UIA 는 Windows 에 종속 (Windows.Media.Ocr, P/Invoke,
# UIAutomationClient). non-Windows 에서 호출되면 honest_stub envelope 으로 응답하고
# live action 은 platform_unsupported 로 거부. PowerShell Core (pwsh) 6+ 의
# $IsWindows / $IsLinux / $IsMacOS 변수를 사용. PowerShell 5 (Windows-only) 에서는
# 이 변수가 없을 수 있으므로 [Environment]::OSVersion.Platform 으로 fallback.
$Script:IsWindowsPlatform = $true
try {
  if ($null -ne (Get-Variable -Name IsWindows -ErrorAction SilentlyContinue)) {
    $Script:IsWindowsPlatform = [bool]$IsWindows
  } else {
    $plat = [Environment]::OSVersion.Platform
    $Script:IsWindowsPlatform = ($plat -eq [System.PlatformID]::Win32NT)
  }
} catch { $Script:IsWindowsPlatform = $true }
$Script:PlatformName = if ($Script:IsWindowsPlatform) { "windows" }
  elseif ($null -ne (Get-Variable -Name IsMacOS -ErrorAction SilentlyContinue) -and $IsMacOS) { "macos" }
  elseif ($null -ne (Get-Variable -Name IsLinux -ErrorAction SilentlyContinue) -and $IsLinux) { "linux" }
  else { "unknown" }

# ----- logging --------------------------------------------------------------
function Write-WrapperLog {
  param([string]$Message)
  $timestamp = (Get-Date).ToString("yyyy-MM-ddTHH:mm:ss.fffK")
  try { Add-Content -LiteralPath $Script:WrapperLog -Value "[$timestamp] $Message" -Encoding UTF8 } catch { }
}

# ----- native helper path ---------------------------------------------------
# CUCP 전용 PowerShell helper 위치. Win32 + UIA + Screenshot을 직접 호출해서
# 외부 windows-mcp 서버나 Codex 공식 helper에 의존하지 않습니다. 이 helper는
# 스킬 폴더 안에 항상 같이 배포되므로 절대 경로 탐색 불필요.
$Script:NativeHelperPath = Join-Path $PSScriptRoot "cucp-native-helper.ps1"
if (-not (Test-Path -LiteralPath $Script:NativeHelperPath)) {
  $Script:NativeHelperPath = ""
}

# cli.mjs를 찾지 못하면 경고만 남기고 계속 진행 (read-only 매크로는 동작 가능)
if (-not $Script:CliPath) {
  $Script:CliPath = ""
  # 로그는 AuditDir 생성 후 기록
}

if (-not (Test-Path -LiteralPath $Script:CacheDir)) {
  try { New-Item -ItemType Directory -Path $Script:CacheDir -Force | Out-Null } catch { }
}

if (-not $Script:CliPath) {
  Write-WrapperLog -Message "WARNING: cli.mjs not found. Set CUCP_CLI_PATH env var or bundle cli/ into the skill folder. Read-only macros (windows, health-quick, icon-find) still work."
}
if (-not $Script:NativeHelperPath) {
  Write-WrapperLog -Message "WARNING: cucp-native-helper.ps1 not found in scripts/. Native fallback unavailable; macros will require cli.mjs."
}

# ============================================================================
# v1.6.0 — Helper Persistent Server IPC
# ============================================================================
# cucp-helper-server.ps1 (named pipe server) 와의 JSON-line IPC 헬퍼.
# wrapper 가 첫 호출 시 lock 파일 (helper.pid) 검사 → server 살아있으면 pipe,
# 없거나 stale 이면 child PowerShell fallback. 같은 wrapper invocation 안에서
# 여러 매크로가 helper 를 N회 호출할 때 cold-start 비용 (~500ms × N) 회피.
#
# 사용 흐름:
#   1. _Read-LockSafely → lock JSON 안전 read (없으면 null)
#   2. _Is-StaleLock → PID alive / mtime / pipe_name / SemVer 검사
#   3. Invoke-HelperPipe → JSON-line request 전송 + response 수신
#   4. Invoke-NativeHelper 가 위 헬퍼를 server-first 분기에서 사용
# ============================================================================

$Script:HelperLockPath = Join-Path $Script:AuditDir "helper.pid"
$Script:HelperServerScript = Join-Path $PSScriptRoot "cucp-helper-server.ps1"
$Script:_HelperPipeReqId = 0
# server 가 직접 처리 가능한 action 화이트리스트 (cucp-helper-server.ps1 v1.7.0 의 _Dispatch 와 일치)
$Script:HelperServerSupported = @("windows", "health", "focused", "modal-detect", "ocr-screen-fast", "uia-find-fast")

function _Read-LockSafely {
  # 결과: hashtable {pid, pipe_name, started_at, helper_version} 또는 $null
  if (-not (Test-Path -LiteralPath $Script:HelperLockPath)) { return $null }
  try {
    $raw = Get-Content -LiteralPath $Script:HelperLockPath -Raw -Encoding UTF8
    if (-not $raw) { return $null }
    $obj = $raw | ConvertFrom-Json -ErrorAction Stop
    return $obj
  } catch {
    return $null
  }
}

function _Is-StaleLock {
  param($Lock)
  if (-not $Lock) { return $true }
  # v2.0.0 — multi-user 격리: 다른 user 의 lock 은 stale 처리하지 않고 무시.
  # wrapper 가 자기 user 의 lock 만 정리하도록. owner_user 가 없으면 (legacy) 검사 skip.
  try {
    $myUser = [Environment]::UserName
    if ($Lock.owner_user -and "$($Lock.owner_user)" -ne $myUser) {
      # 남의 user 의 lock — stale 아니지만 우리는 사용 안 함. 호출자가 lock 을 무시할 수 있도록 stale 로 처리 (delete 안 함).
      return $true
    }
  } catch { }
  # 1. PID alive 검증
  try {
    $proc = Get-Process -Id ([int]$Lock.pid) -ErrorAction SilentlyContinue
    if (-not $proc) { return $true }
  } catch { return $true }
  # 2. mtime 검증 (24h margin)
  try {
    $started = [DateTime]::Parse("$($Lock.started_at)")
    $age = (Get-Date).ToUniversalTime() - $started.ToUniversalTime()
    if ($age.TotalHours -gt 24) { return $true }
  } catch { return $true }
  # 3. pipe_name 형식 검증
  $expectedPipe = "cucp-helper-$($Lock.pid)"
  if ("$($Lock.pipe_name)" -ne $expectedPipe) { return $true }
  # 4. helper_version SemVer 검증
  if ("$($Lock.helper_version)" -notmatch '^\d+\.\d+\.\d+$') { return $true }
  return $false
}

function _Try-Delete-Lock {
  # v2.0.0 — 자기 user 의 lock 만 삭제. 남의 lock 은 절대 삭제 안 함.
  if (-not (Test-Path -LiteralPath $Script:HelperLockPath)) { return }
  try {
    $lock = _Read-LockSafely
    if ($lock -and $lock.owner_user) {
      $myUser = [Environment]::UserName
      if ("$($lock.owner_user)" -ne $myUser) { return }
    }
    Remove-Item -LiteralPath $Script:HelperLockPath -Force -ErrorAction SilentlyContinue
  } catch { }
}

function Get-HelperServerStatus {
  # macro session helper-status 용. server up/down 둘 다 일관 envelope 반환.
  $lock = _Read-LockSafely
  if (-not $lock -or (_Is-StaleLock -Lock $lock)) {
    return [pscustomobject]@{
      schema = "cucp.helper-status/v1"
      alive = $false
      pid = $null
      pipe_name = $null
      started_at = $null
      uptime_s = 0
      request_count = 0
      helper_version = $null
    }
  }
  # server 살아있으면 health action 으로 추가 정보 가져옴
  $extra = $null
  try {
    $resp = Invoke-HelperPipe -Action "health" -ArgsHash @{} -TimeoutMs 1500
    if ($resp -and $resp.exit_code -eq 0) { $extra = $resp.result }
  } catch { $extra = $null }
  $upS = 0; $reqC = 0
  if ($extra) {
    if ($extra.uptime_s) { $upS = [int]$extra.uptime_s }
    if ($extra.request_count) { $reqC = [int]$extra.request_count }
  }
  return [pscustomobject]@{
    schema = "cucp.helper-status/v1"
    alive = $true
    pid = [int]$lock.pid
    pipe_name = "$($lock.pipe_name)"
    started_at = "$($lock.started_at)"
    uptime_s = $upS
    request_count = $reqC
    helper_version = "$($lock.helper_version)"
  }
}

function Invoke-HelperPipe {
  # JSON-line client. server 가 살아있다고 가정 (호출자가 lock 검증 후 사용).
  # request: {id, action, args, timeout_ms?, trace_id?}
  # response: {id, exit_code, result, error, ...}
  # 실패 시 throw — 호출자가 catch 후 child fallback 으로 처리.
  param(
    [Parameter(Mandatory=$true)][string]$Action,
    [hashtable]$ArgsHash = @{},
    [int]$TimeoutMs = 30000
  )
  $lock = _Read-LockSafely
  if (-not $lock) { throw "helper_lock_missing" }
  $pipeName = "$($lock.pipe_name)"
  if (-not $pipeName) { throw "helper_pipe_name_missing" }
  $client = New-Object System.IO.Pipes.NamedPipeClientStream(
    ".", $pipeName,
    [System.IO.Pipes.PipeDirection]::InOut,
    [System.IO.Pipes.PipeOptions]::Asynchronous
  )
  $reader = $null
  $writer = $null
  try {
    $connectTimeout = [Math]::Min(2000, $TimeoutMs)
    $client.Connect($connectTimeout)
    if (-not $client.IsConnected) { throw "pipe_connect_failed" }
    $reader = New-Object System.IO.StreamReader($client, [System.Text.Encoding]::UTF8)
    $writer = New-Object System.IO.StreamWriter($client, [System.Text.Encoding]::UTF8)
    $writer.AutoFlush = $true
    $Script:_HelperPipeReqId++
    $reqId = $Script:_HelperPipeReqId
    $req = [ordered]@{
      id = $reqId
      action = $Action
      args = $ArgsHash
      timeout_ms = $TimeoutMs
    }
    $line = $req | ConvertTo-Json -Compress -Depth 8
    $writer.WriteLine($line)
    # async ReadLine 으로 timeout 통제
    $task = [System.Threading.Tasks.Task]::Run([System.Func[string]] { $reader.ReadLine() })
    $waited = $task.Wait($TimeoutMs)
    if (-not $waited) { throw "pipe_read_timeout" }
    $respLine = $task.Result
    if (-not $respLine) { throw "pipe_empty_response" }
    $resp = $respLine | ConvertFrom-Json -ErrorAction Stop
    if ($resp.id -ne $reqId) { throw "pipe_id_mismatch (req=$reqId, resp=$($resp.id))" }
    return $resp
  } finally {
    try { if ($reader) { $reader.Close() } } catch { }
    try { if ($writer) { $writer.Close() } } catch { }
    try { $client.Close() } catch { }
    try { $client.Dispose() } catch { }
  }
}

function Start-HelperServer {
  # idempotent — 이미 살아있는 server 가 있으면 그대로 reuse
  param(
    [int]$IdleTimeoutMs = 60000
  )
  $lock = _Read-LockSafely
  if ($lock -and -not (_Is-StaleLock -Lock $lock)) {
    return [pscustomobject]@{
      status = "ok"
      reused = $true
      pid = [int]$lock.pid
      pipe_name = "$($lock.pipe_name)"
      started_at = "$($lock.started_at)"
    }
  }
  if ($lock) { _Try-Delete-Lock }  # stale 정리
  if (-not (Test-Path -LiteralPath $Script:HelperServerScript)) {
    return [pscustomobject]@{
      status = "error"
      reason = "helper_server_script_missing"
      path = $Script:HelperServerScript
    }
  }
  $argList = @(
    "-NoProfile", "-NoLogo", "-NonInteractive",
    "-ExecutionPolicy", "Bypass",
    "-File", $Script:HelperServerScript,
    "-IdleTimeoutMs", "$IdleTimeoutMs"
  )
  $proc = Start-Process powershell.exe -ArgumentList $argList `
    -WindowStyle Hidden -PassThru -ErrorAction Stop
  # lock 등장 대기 (3s deadline, 50ms tick)
  $deadline = (Get-Date).AddMilliseconds(3000)
  while ((Get-Date) -lt $deadline) {
    Start-Sleep -Milliseconds 50
    $lock = _Read-LockSafely
    if ($lock -and [int]$lock.pid -eq [int]$proc.Id -and -not (_Is-StaleLock -Lock $lock)) {
      return [pscustomobject]@{
        status = "ok"
        reused = $false
        pid = [int]$lock.pid
        pipe_name = "$($lock.pipe_name)"
        started_at = "$($lock.started_at)"
      }
    }
  }
  # 실패 → spawn 된 proc 정리
  try { $proc.Kill() } catch { }
  _Try-Delete-Lock
  return [pscustomobject]@{
    status = "error"
    reason = "server_start_timeout"
  }
}

function Stop-HelperServer {
  param([switch]$Force)
  $lock = _Read-LockSafely
  if (-not $lock) {
    return [pscustomobject]@{ status = "ok"; reason = "no_helper_running" }
  }
  $oldPid = [int]$lock.pid
  # A lock PID is not a process identity. Never terminate by an untrusted or
  # stale PID: it may now belong to an unrelated application.
  if (_Is-StaleLock -Lock $lock) {
    _Try-Delete-Lock
    return [pscustomobject]@{ status = "ok"; reason = "stale_lock_removed"; stopped_pid = $null; forced = $false }
  }
  try {
    $resp = Invoke-HelperPipe -Action "shutdown" -ArgsHash @{} -TimeoutMs 1500
    if (-not $resp -or $resp.exit_code -ne 0) { throw "shutdown_not_acknowledged" }
  } catch {
    return [pscustomobject]@{ status = "error"; reason = "shutdown_not_acknowledged_no_pid_kill"; stopped_pid = $null; forced = $false }
  }
  _Try-Delete-Lock
  return [pscustomobject]@{ status = "ok"; reason = "shutdown_requested"; stopped_pid = $oldPid; forced = $false }

}

# ============================================================================
# v2.2.0 — Helper-server autostart (cold first-call 제거)
# ============================================================================
# benchmark 실측: read-only 매크로의 cold first-call 이 1.3~2.4초 (PowerShell
# cold start + UIA/EnumWindows 초기화). warm (server-up) 은 ~25ms. AI agent 는
# single-shot 으로 wrapper 를 부르므로 항상 cold 를 맞음. 이 함수들은 Windows
# 로그인 시 helper-server 를 자동 기동하는 startup shim 을 설치/제거한다.
#
# 설계 선택 — 왜 Startup 폴더 .cmd shim 인가:
#   - 레지스트리 Run 키 / 작업 스케줄러보다 권한 안전 (UAC / 관리자 불필요)
#   - 사용자가 shell:startup 에서 직접 눈으로 확인 / 삭제 가능 (투명성)
#   - HKCU 만 건드리지 않으므로 다른 user 영향 0 (multi-user 격리 유지)
#   - shim 은 idle-timeout 을 길게 (기본 8h) 줘서 부팅 후 종일 warm 유지
# 안전: read-only IPC server 만 띄움. live actuation 게이트
#       (-AllowLiveControl) 는 server 경로에서도 그대로 적용된다.
# ============================================================================

function _Get-AutostartShimPath {
  # 현재 user 의 Startup 폴더 안 shim 경로. 파일명에 PID 안 넣음 (1개만 유지).
  $startupDir = [System.Environment]::GetFolderPath([System.Environment+SpecialFolder]::Startup)
  return (Join-Path $startupDir "cucp-helper-autostart.cmd")
}

function Install-HelperAutostart {
  # Startup 폴더에 helper-server 를 hidden 으로 기동하는 .cmd shim 생성 (idempotent).
  param([int]$IdleTimeoutMs = 28800000)  # 기본 8시간
  if (-not $Script:HelperServerScript -or -not (Test-Path -LiteralPath $Script:HelperServerScript)) {
    return [pscustomobject]@{ status = "error"; reason = "helper_server_script_missing"; path = $Script:HelperServerScript }
  }
  $shimPath = _Get-AutostartShimPath
  # cmd shim: powershell 을 hidden 으로 띄워 helper-server 를 background 기동.
  # 경로/인자는 cmd 인용 규칙에 맞춰 "..." 로 감쌈 (공백 포함 경로 안전).
  # 주의: start 명령과 인자는 반드시 한 줄. 줄바꿈되면 cmd 가 인자를 못 받는다.
  # 주석은 ASCII 로만 (cmd 기본 코드페이지에서 한글 mojibake 회피).
  $psArgs = '-NoProfile -NoLogo -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden -File "' + $Script:HelperServerScript + '" -IdleTimeoutMs ' + $IdleTimeoutMs
  $startLine = 'start "" /min powershell.exe ' + $psArgs
  $content = "@echo off`r`n" +
             "rem CUCP helper-server autostart shim (v2.2.0). Remove via: cucp macro session uninstall-autostart`r`n" +
             $startLine + "`r`n"
  try {
    # ASCII 인코딩 + 명시적 CRLF 로 cmd 호환성 보장. WriteAllText 로 한 번에 기록
    # (Set-Content 배열 처리로 긴 줄이 분할되는 문제 회피).
    [System.IO.File]::WriteAllText($shimPath, $content, [System.Text.Encoding]::ASCII)
  } catch {
    return [pscustomobject]@{ status = "error"; reason = "shim_write_failed"; detail = "$($_.Exception.Message)"; path = $shimPath }
  }
  return [pscustomobject]@{
    status = "ok"
    action = "install-autostart"
    shim_path = $shimPath
    idle_timeout_ms = $IdleTimeoutMs
    note = "다음 로그인부터 helper-server 가 자동 기동됩니다. 지금 바로 띄우려면 macro session start-helper."
  }
}

function Uninstall-HelperAutostart {
  # Startup shim 제거. shim 없어도 graceful (status ok, removed=false).
  $shimPath = _Get-AutostartShimPath
  $removed = $false
  if (Test-Path -LiteralPath $shimPath) {
    try { Remove-Item -LiteralPath $shimPath -Force; $removed = $true }
    catch { return [pscustomobject]@{ status = "error"; reason = "shim_remove_failed"; detail = "$($_.Exception.Message)"; path = $shimPath } }
  }
  return [pscustomobject]@{
    status = "ok"
    action = "uninstall-autostart"
    shim_path = $shimPath
    removed = $removed
  }
}

function Get-HelperAutostartStatus {
  # shim 설치 여부 + 경로 반환.
  $shimPath = _Get-AutostartShimPath
  return [pscustomobject]@{
    status = "ok"
    installed = [bool](Test-Path -LiteralPath $shimPath)
    shim_path = $shimPath
  }
}

# ============================================================================
# v2.1.0 — 공통 헬퍼 (envelope / timestamp / error / emit)
# ============================================================================
# v1.8.0~v2.0.0 에서 추가된 매크로들이 반복하던 패턴을 한 곳으로 모음.
# 목적:
#   - timestamp 포맷 일관성 (ISO 8601 + 로컬 offset)
#   - recoverable_errors[] 항목 schema 일관성 (code / layer / recommended_action)
#   - "brief 면 한 줄, 아니면 JSON" emit 패턴 중복 제거
# 기존 (v1.x) 매크로는 건드리지 않음 — 회귀 위험 회피. 신규 코드만 사용.
# ============================================================================

function _Now-Iso {
  # ISO 8601 + 로컬 타임존 offset. 모든 v2.1.0 envelope 의 generated_at 에 사용.
  return (Get-Date).ToString("yyyy-MM-ddTHH:mm:ss.fffK")
}

function _Make-RecoverableError {
  # recoverable_errors[] 한 항목을 일관 schema 로 생성.
  #   code               : 기계 판독용 짧은 코드 (예: cli_path_unresolved)
  #   layer              : 어느 layer 에서 난 문제인지 (wrapper / cli / helper_server)
  #   recommended_action : 호출자(AI agent)가 다음에 할 행동 한 줄
  param(
    [Parameter(Mandatory=$true)][string]$Code,
    [string]$Layer = "wrapper",
    [string]$RecommendedAction = ""
  )
  return @{
    code = $Code
    layer = $Layer
    recommended_action = $RecommendedAction
  }
}

function _Emit-Envelope {
  # "brief 면 한 줄, 아니면 JSON 전체" 출력 패턴을 한 곳으로.
  #   -Envelope   : 출력할 pscustomobject (JSON 직렬화 대상)
  #   -BriefLine  : -Brief 모드일 때 출력할 한 줄 문자열
  #   -Depth      : ConvertTo-Json depth (중첩 깊은 envelope 는 크게)
  #   -ForceJson  : --json-only 처럼 brief 여도 JSON 강제
  param(
    [Parameter(Mandatory=$true)]$Envelope,
    [string]$BriefLine = "",
    [int]$Depth = 8,
    [switch]$ForceJson
  )
  if ($Brief -and -not $ForceJson -and $BriefLine) {
    [Console]::Out.WriteLine($BriefLine)
  } else {
    [Console]::Out.WriteLine(($Envelope | ConvertTo-Json -Depth $Depth))
  }
}

# ============================================================================
# v1.8.0 — Get-CucpVersionReport (Option B Layer 통합 surface)
# ============================================================================
# CUCP 의 entry point 는 cucp.ps1 단독. 그 아래 layer 가 셋:
#   - skill (wrapper, $Script:SkillVersion) — 매크로 + helper-server lifecycle
#   - cli (Node backend, package.json) — 저수준 control-plane (read-only 기본)
#   - helper-server (cucp-helper-server.ps1 헤더) — long-running named pipe
# 이 함수는 셋의 버전 + helper_mode + envelope 일관 schema 로 통합.
# 어느 layer 가 누락돼도 status="partial" + recoverable_errors[] 로 graceful.
# ============================================================================

function _Read-CliVersion {
  # cli backend 의 package.json 에서 version 읽기. 없으면 $null.
  if (-not $Script:CliPath) { return @{ version = $null; package_path = $null; error = "cli_path_unresolved" } }
  $cliDir = Split-Path -Parent $Script:CliPath
  # cli.mjs 위치 기준 package.json 후보: ../package.json (대부분), ./package.json
  $candidates = @(
    (Join-Path $cliDir "..\package.json"),
    (Join-Path $cliDir "package.json")
  )
  foreach ($p in $candidates) {
    $resolved = [System.IO.Path]::GetFullPath($p)
    if (Test-Path -LiteralPath $resolved) {
      try {
        $pkg = Get-Content -LiteralPath $resolved -Raw -Encoding UTF8 | ConvertFrom-Json
        return @{ version = "$($pkg.version)"; package_path = $resolved; error = $null }
      } catch {
        return @{ version = $null; package_path = $resolved; error = "package_json_parse_failed" }
      }
    }
  }
  return @{ version = $null; package_path = $null; error = "package_json_not_found" }
}

function _Read-HelperServerVersion {
  # cucp-helper-server.ps1 헤더 주석 또는 helper_version 라인에서 SemVer 추출.
  if (-not $Script:HelperServerScript -or -not (Test-Path -LiteralPath $Script:HelperServerScript)) {
    return @{ version = $null; error = "helper_server_script_missing" }
  }
  try {
    $head = Get-Content -LiteralPath $Script:HelperServerScript -TotalCount 600 -Encoding UTF8 -ErrorAction SilentlyContinue
    if (-not $head) { return @{ version = $null; error = "helper_server_empty" } }
    foreach ($line in $head) {
      # 우선순위 1: helper_version = "X.Y.Z" 라인 (단일 source of truth)
      if ($line -match 'helper_version\s*=\s*"(\d+\.\d+\.\d+)"') {
        return @{ version = $Matches[1]; error = $null }
      }
    }
    foreach ($line in $head) {
      # 우선순위 2: 헤더 주석 "# CUCP Helper Persistent Server (vX.Y.Z)"
      if ($line -match 'Helper.*\(v(\d+\.\d+\.\d+)\)') {
        return @{ version = $Matches[1]; error = $null }
      }
    }
    return @{ version = $null; error = "helper_server_version_not_found" }
  } catch {
    return @{ version = $null; error = "helper_server_read_failed" }
  }
}

function Get-CucpVersionReport {
  # 출력 envelope schema = "cucp.version/v1"
  # 입력: 없음 (전역 상태 $Script:SkillVersion / CliPath / HelperServerScript / lock 참조)
  # 출력 필드:
  #   surface     : "wrapper_only" (cucp.ps1 단독) | "wrapper+cli" (cli backend 동반)
  #   helper_mode : "persistent_server" (lock alive) | "child_only" (lock 부재/stale)
  #   status      : "ok" | "partial" (cli / helper_server layer 누락 시)
  #   versions    : { skill, cli, helper_server } SemVer
  #   recoverable_errors[] : 누락 layer 마다 code/layer/recommended_action
  # why: AI agent 가 한 번의 호출로 3 layer 버전 + 가동 모드를 파악하게 함.
  $errs = New-Object System.Collections.ArrayList
  $cli = _Read-CliVersion
  if ($cli.error) {
    [void]$errs.Add((_Make-RecoverableError -Code $cli.error -Layer "cli" -RecommendedAction "Set CUCP_CLI_PATH or run wrapper-only mode"))
  }
  $hs = _Read-HelperServerVersion
  if ($hs.error) {
    [void]$errs.Add((_Make-RecoverableError -Code $hs.error -Layer "helper_server" -RecommendedAction "Verify scripts/cucp-helper-server.ps1 헤더의 helper_version 표기"))
  }
  $lock = _Read-LockSafely
  $helperMode = "child_only"
  if ($lock -and -not (_Is-StaleLock -Lock $lock)) { $helperMode = "persistent_server" }
  $surface = "wrapper_only"
  if ($cli.version) { $surface = "wrapper+cli" }
  $status = if ($errs.Count -gt 0) { "partial" } else { "ok" }
  return [pscustomobject]@{
    schema = "cucp.version/v1"
    status = $status
    surface = $surface
    helper_mode = $helperMode
    versions = @{
      skill = $Script:SkillVersion
      cli = $cli.version
      helper_server = $hs.version
    }
    sources = @{
      skill = "scripts/cucp.ps1::Script:SkillVersion"
      cli = $cli.package_path
      helper_server = $Script:HelperServerScript
    }
    recoverable_errors = @($errs)
    generated_at = (_Now-Iso)
  }
}

function Invoke-MacroVersion {
  # macro version [--json-only]
  # 사용처:
  #   - cucp version                    (사람용 brief 한 줄, 단 brief 모드일 때만)
  #   - cucp macro version              (envelope JSON)
  #   - cucp macro version --json-only  (envelope JSON only, brief 무시)
  # 반환 exit code: status="partial" 이면 2, 아니면 0.
  param([string[]]$Rest)
  $jsonOnly = _Read-Switch -Rest $Rest -Name "--json-only"
  $report = Get-CucpVersionReport
  $skill = if ($report.versions.skill) { "v$($report.versions.skill)" } else { "v?" }
  $cli = if ($report.versions.cli) { "v$($report.versions.cli)" } else { "missing" }
  $hs = if ($report.versions.helper_server) { "v$($report.versions.helper_server)" } else { "missing" }
  $briefLine = "ok cucp $skill (skill) + $cli (cli) + $hs (helper-server, $($report.helper_mode)) surface=$($report.surface) status=$($report.status)"
  _Emit-Envelope -Envelope $report -BriefLine $briefLine -Depth 8 -ForceJson:$jsonOnly
  if ($report.status -eq "partial") { return 2 }
  return 0
}

# ============================================================================
# v1.9.0 — Cross-platform honest stub
# ============================================================================
# 비Windows 환경에서 호출 시 envelope schema 일관 + live action 거부.
# 호출자 (AI agent) 가 동일 schema 로 결과를 받아 fallback 결정 가능.
# ============================================================================

function _Make-PlatformStubEnvelope {
  # 비Windows 환경 응답 envelope 생성.
  #   ActionKind = "live"      → status="blocked",     reason="platform_unsupported"
  #   ActionKind = "read_only" → status="honest_stub", reason="platform_stub_only"
  # schema 는 cucp.observation/v1 유지 (호출자가 동일 파서로 처리 가능).
  param([string]$Macro, [string]$ActionKind)
  $isLive = ($ActionKind -eq "live")
  $recAction = if ($isLive) {
    "CUCP live actuation requires Windows 10/11. Run on Windows or omit -AllowLiveControl."
  } else {
    "Read-only result on non-Windows is a stub. Cassette / observation may be incomplete."
  }
  return [pscustomobject]@{
    schema = "cucp.observation/v1"
    status = if ($isLive) { "blocked" } else { "honest_stub" }
    reason = if ($isLive) { "platform_unsupported" } else { "platform_stub_only" }
    macro = $Macro
    platform = $Script:PlatformName
    is_windows = $Script:IsWindowsPlatform
    recoverable_errors = @((_Make-RecoverableError -Code (if ($isLive) { "platform_unsupported" } else { "platform_stub_only" }) -Layer "wrapper" -RecommendedAction $recAction))
    generated_at = (_Now-Iso)
  }
}

function _Assert-PlatformOrStub {
  # macro 진입 시 호출. 반환값:
  #   $null  → Windows. 호출자는 그냥 진행.
  #   3      → 비Windows + live macro (envelope emit 후 exit 3 권장).
  #   0      → 비Windows + read-only (honest_stub envelope emit 후 exit 0 권장).
  param([string]$Macro, [string]$ActionKind)
  if ($Script:IsWindowsPlatform) { return $null }
  $envelope = _Make-PlatformStubEnvelope -Macro $Macro -ActionKind $ActionKind
  $briefLine = "$($envelope.status) $Macro reason=$($envelope.reason) platform=$($envelope.platform)"
  _Emit-Envelope -Envelope $envelope -BriefLine $briefLine -Depth 8
  if ($ActionKind -eq "live") { return 3 }
  return 0
}

# ============================================================================
# v1.9.0 — Recorder / Replay
# ============================================================================
# trajectory hook 위에 가벼운 session recorder. wrapper invocation 안에서 발생한
# 매크로 호출을 step 단위로 캡처하고, 나중에 dry-run 또는 라이브 재실행 가능.
# 라이브 재실행 시에도 wrapper -AllowLiveControl 게이트는 그대로 enforce.
# ============================================================================

$Script:RecorderDir = Join-Path $Script:AuditDir "recorder"
$Script:RecorderActive = $false
$Script:RecorderSession = $null
$Script:RecorderSteps = @()

function _Recorder-Path {
  param([string]$Name)
  if (-not (Test-Path -LiteralPath $Script:RecorderDir)) {
    try { New-Item -ItemType Directory -Path $Script:RecorderDir -Force | Out-Null } catch { }
  }
  $safeName = if ($Name) { $Name -replace '[^A-Za-z0-9_\-\.]', '_' } else { "session-" + (Get-Date).ToString("yyyyMMdd-HHmmss") }
  return (Join-Path $Script:RecorderDir ($safeName + ".json"))
}

function Recorder-Start {
  param([string]$Name)
  $Script:RecorderActive = $true
  $Script:RecorderSession = if ($Name) { $Name } else { "session-" + (Get-Date).ToString("yyyyMMdd-HHmmss") }
  $Script:RecorderSteps = @()
  return $Script:RecorderSession
}

function Recorder-Append {
  # 녹화 중이면 step 한 건 누적. 현재는 recorder 매크로가 명시적으로 호출하지 않고
  # (자동 trajectory hook 미연동), 향후 Invoke-Macro onAfter hook 에서 사용 예정.
  param([string]$Macro, [string[]]$StepArgs, [int]$Exit, [int]$ElapsedMs)
  if (-not $Script:RecorderActive) { return }
  $Script:RecorderSteps += [pscustomobject]@{
    ts = (_Now-Iso)
    macro = $Macro
    args = @($StepArgs)
    exit_code = $Exit
    elapsed_ms = $ElapsedMs
  }
}

function Recorder-Stop {
  # 녹화 종료 + session JSON 저장. schema = cucp.recorder/v1.
  # 반환: { status, session, step_count, path }
  if (-not $Script:RecorderActive) {
    return [pscustomobject]@{ status = "not_recording"; session = $null; step_count = 0; path = $null }
  }
  $path = _Recorder-Path -Name $Script:RecorderSession
  $session = [pscustomobject]@{
    schema = "cucp.recorder/v1"
    name = $Script:RecorderSession
    started_at = if ($Script:RecorderSteps.Count -gt 0) { $Script:RecorderSteps[0].ts } else { $null }
    ended_at = (_Now-Iso)
    step_count = $Script:RecorderSteps.Count
    steps = $Script:RecorderSteps
  }
  try {
    Set-Content -LiteralPath $path -Value ($session | ConvertTo-Json -Depth 12) -Encoding UTF8
  } catch { }
  $name = $Script:RecorderSession
  $count = $Script:RecorderSteps.Count
  $Script:RecorderActive = $false
  $Script:RecorderSession = $null
  $Script:RecorderSteps = @()
  return [pscustomobject]@{ status = "saved"; session = $name; step_count = $count; path = $path }
}

function Invoke-MacroRecorder {
  # macro recorder start [--name X]
  # macro recorder stop
  # macro recorder list
  # macro recorder show --name X
  # macro recorder replay --name X [--dry-run] [--continue-on-error]
  param([string[]]$Rest)
  $sub = if ($Rest.Count -gt 0) { $Rest[0] } else { "" }
  $rest2 = if ($Rest.Count -gt 1) { $Rest[1..($Rest.Count-1)] } else { @() }
  switch ($sub) {
    "start" {
      $name = _Read-OptValue -Rest $rest2 -Name "--name"
      $sName = Recorder-Start -Name $name
      $out = [pscustomobject]@{ schema = "cucp.recorder/v1"; status = "recording"; session = $sName }
      _Emit-Envelope -Envelope $out -BriefLine "ok recorder start session=$sName" -Depth 6
      return 0
    }
    "stop" {
      $r = Recorder-Stop
      _Emit-Envelope -Envelope $r -BriefLine "ok recorder stop session=$($r.session) steps=$($r.step_count) path=$($r.path)" -Depth 6
      return 0
    }
    "list" {
      $files = @()
      if (Test-Path -LiteralPath $Script:RecorderDir) {
        $files = @(Get-ChildItem -LiteralPath $Script:RecorderDir -Filter '*.json' -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 50 | ForEach-Object {
          [pscustomobject]@{ name = [System.IO.Path]::GetFileNameWithoutExtension($_.Name); path = $_.FullName; size_bytes = $_.Length; mtime = $_.LastWriteTime.ToString("yyyy-MM-ddTHH:mm:ss") }
        })
      }
      $out = [pscustomobject]@{ schema = "cucp.recorder/v1"; status = "ok"; sessions = $files; count = $files.Count }
      [Console]::Out.WriteLine(($out | ConvertTo-Json -Depth 6))
      return 0
    }
    "show" {
      $name = _Read-OptValue -Rest $rest2 -Name "--name"
      if (-not $name) { Write-Notice -Level "ERROR" -Message "--name required"; return 1 }
      $path = _Recorder-Path -Name $name
      if (-not (Test-Path -LiteralPath $path)) { Write-Notice -Level "ERROR" -Message "session not found: $name"; return 1 }
      [Console]::Out.WriteLine((Get-Content -LiteralPath $path -Raw -Encoding UTF8))
      return 0
    }
    "replay" {
      $name = _Read-OptValue -Rest $rest2 -Name "--name"
      $dryRun = _Read-Switch -Rest $rest2 -Name "--dry-run"
      $continueOnError = _Read-Switch -Rest $rest2 -Name "--continue-on-error"
      if (-not $name) { Write-Notice -Level "ERROR" -Message "--name required"; return 1 }
      $path = _Recorder-Path -Name $name
      if (-not (Test-Path -LiteralPath $path)) { Write-Notice -Level "ERROR" -Message "session not found: $name"; return 1 }
      $session = Get-Content -LiteralPath $path -Raw -Encoding UTF8 | ConvertFrom-Json
      $results = @()
      $finalExit = 0
      foreach ($step in @($session.steps)) {
        $stepArgs = @($step.args)
        if ($dryRun) {
          $results += [pscustomobject]@{ macro = $step.macro; args = $stepArgs; mode = "dry_run"; exit_code = 0 }
          continue
        }
        # 라이브 재실행: Invoke-Macro 가 wrapper -AllowLiveControl 게이트를 그대로 enforce.
        $argList = @("macro") + @($stepArgs)
        try {
          $code = Invoke-Macro -ArgList $argList
          if ($null -eq $code) { $code = 0 }
          if ($code -is [array]) { $code = ($code | Where-Object { $_ -is [int] } | Select-Object -Last 1) }
          if ($code -isnot [int]) { try { $code = [int]$code } catch { $code = 0 } }
        } catch {
          $code = 1
        }
        $results += [pscustomobject]@{ macro = $step.macro; args = $stepArgs; mode = "live"; exit_code = $code }
        if ($code -ne 0 -and -not $continueOnError) { $finalExit = $code; break }
        if ($code -ne 0) { $finalExit = $code }
      }
      $out = [pscustomobject]@{
        schema = "cucp.recorder-replay/v1"
        session = $name
        mode = if ($dryRun) { "dry_run" } else { "live" }
        step_count = $session.step_count
        executed = $results.Count
        results = $results
        exit_code = $finalExit
      }
      _Emit-Envelope -Envelope $out -BriefLine "ok recorder replay session=$name mode=$($out.mode) executed=$($results.Count)/$($session.step_count) exit=$finalExit" -Depth 12
      return $finalExit
    }
    default {
      Write-Notice -Level "ERROR" -Message "recorder sub-command 필요: start | stop | list | show | replay"
      return 1
    }
  }
}

# ============================================================================
# v2.0.0 — Governance: audit-summary / policy-check
# ============================================================================
# 기존 trajectory.ndjson 파일들을 시간대 / 매크로 / exit_code 별로 집계.
# policy-check 는 사용자가 정의한 policy 파일 (JSON) 을 평가해서
# allow / deny / require_confirm 세 결과 중 하나를 반환.
# ============================================================================

function Invoke-MacroAuditSummary {
  param([string[]]$Rest)
  $sinceMin = _Read-OptValue -Rest $Rest -Name "--since-minutes"
  $jsonOnly = _Read-Switch -Rest $Rest -Name "--json-only"
  $cutoff = $null
  if ($sinceMin) {
    try { $cutoff = (Get-Date).AddMinutes(-1 * [int]$sinceMin) } catch { $cutoff = $null }
  }
  $files = @()
  if (Test-Path -LiteralPath $Script:AuditDir) {
    $files = @(Get-ChildItem -LiteralPath $Script:AuditDir -Filter 'trajectory*.ndjson' -ErrorAction SilentlyContinue -Recurse | Sort-Object LastWriteTime -Descending | Select-Object -First 20)
  }
  $totalEvents = 0
  $byMacro = @{}
  $byExit = @{}
  $sensitiveCount = 0
  $blockedCount = 0
  $earliest = $null
  $latest = $null
  foreach ($f in $files) {
    try {
      $lines = Get-Content -LiteralPath $f.FullName -Encoding UTF8 -ErrorAction SilentlyContinue
      foreach ($line in @($lines)) {
        if ([string]::IsNullOrWhiteSpace($line)) { continue }
        try {
          $ev = $line | ConvertFrom-Json -ErrorAction Stop
        } catch { continue }
        if ($cutoff -and $ev.ts) {
          try { $evTs = [datetime]$ev.ts } catch { $evTs = $null }
          if ($evTs -and $evTs -lt $cutoff) { continue }
        }
        $totalEvents++
        $m = "$($ev.macro)"
        if (-not $m) { $m = "$($ev.action)" }
        if ($m) {
          if (-not $byMacro.ContainsKey($m)) { $byMacro[$m] = 0 }
          $byMacro[$m] = $byMacro[$m] + 1
        }
        $ec = "$($ev.exit_code)"
        if ($ec) {
          if (-not $byExit.ContainsKey($ec)) { $byExit[$ec] = 0 }
          $byExit[$ec] = $byExit[$ec] + 1
        }
        if ($ev.sensitive -or "$($ev.reason)" -match 'sensitive') { $sensitiveCount++ }
        if ($ev.status -eq "blocked" -or $ec -eq "3") { $blockedCount++ }
        if ($ev.ts) {
          if (-not $earliest -or "$($ev.ts)" -lt $earliest) { $earliest = "$($ev.ts)" }
          if (-not $latest   -or "$($ev.ts)" -gt $latest)   { $latest   = "$($ev.ts)" }
        }
      }
    } catch { }
  }
  $status = if ($totalEvents -eq 0) { "empty" } else { "ok" }
  $out = [pscustomobject]@{
    schema = "cucp.audit-summary/v1"
    status = $status
    file_count = @($files).Count
    event_count = $totalEvents
    earliest_ts = $earliest
    latest_ts = $latest
    by_macro = $byMacro
    by_exit_code = $byExit
    sensitive_count = $sensitiveCount
    blocked_count = $blockedCount
    since_cutoff = if ($cutoff) { $cutoff.ToString("yyyy-MM-ddTHH:mm:ss.fffK") } else { $null }
  }
  $briefLine = "$status audit-summary files=$($files.Count) events=$totalEvents sensitive=$sensitiveCount blocked=$blockedCount"
  _Emit-Envelope -Envelope $out -BriefLine $briefLine -Depth 8 -ForceJson:$jsonOnly
  return 0
}

function Invoke-MacroPolicyCheck {
  param([string[]]$Rest)
  $action = _Read-OptValue -Rest $Rest -Name "--action"
  $policyPath = _Read-OptValue -Rest $Rest -Name "--policy"
  $jsonOnly = _Read-Switch -Rest $Rest -Name "--json-only"
  if (-not $action) { Write-Notice -Level "ERROR" -Message "--action <macro> required"; return 1 }
  $policy = $null
  $policyError = $null
  if ($policyPath) {
    if (Test-Path -LiteralPath $policyPath) {
      try { $policy = Get-Content -LiteralPath $policyPath -Raw -Encoding UTF8 | ConvertFrom-Json }
      catch { $policyError = "policy_parse_failed: $($_.Exception.Message)"; $policy = $null }
    } else { $policyError = "policy_not_found" }
  }
  # 기본 정책: live macro = require_confirm, read-only = allow.
  # 정책 파일이 있으면 그 결과로 override.
  $liveMacros = @("click-label","click-id","click-point","fill-label","shortcut","type-native",
    "smart-click","ime-paste","safe-type-ime","safe-type","cdp-eval","cdp-smart-click","cdp-smart-type",
    "cdp-prosemirror-insert","mouse-verify","recovery-run","auto-do","goal","app-launch","app-close")
  $sensitiveMacros = @("recovery-run","auto-do","goal")
  $decision = "allow"
  $reason = "default_read_only"
  if ($liveMacros -contains $action) { $decision = "require_confirm"; $reason = "default_live_macro" }
  if ($sensitiveMacros -contains $action) { $decision = "require_confirm"; $reason = "default_sensitive" }
  $matchedRule = $null
  if ($policy) {
    foreach ($rule in @($policy.rules)) {
      $pat = "$($rule.match)"
      if (-not $pat) { continue }
      $matched = $false
      try {
        if ($action -match $pat) { $matched = $true }
      } catch { $matched = ($action -eq $pat) }
      if ($matched) {
        $decision = "$($rule.decision)"
        if (-not $decision) { $decision = "allow" }
        $reason = if ($rule.reason) { "$($rule.reason)" } else { "policy_match:$pat" }
        $matchedRule = $rule
        break
      }
    }
  }
  $out = [pscustomobject]@{
    schema = "cucp.policy/v1"
    status = "ok"
    action = $action
    decision = $decision
    reason = $reason
    matched_rule = $matchedRule
    policy_path = $policyPath
    policy_error = $policyError
  }
  _Emit-Envelope -Envelope $out -BriefLine "ok policy-check action=$action decision=$decision reason=$reason" -Depth 6 -ForceJson:$jsonOnly
  if ($decision -eq "deny") { return 3 }
  return 0
}

# ============================================================================
# v2.0.0 — Vision LLM Token Budget Gate
# ============================================================================
# vision-click / vision-find / vision-click-precise 호출 누적 추적.
# wrapper invocation 안에서만 누적 (단일 invocation scope).
# CUCP_VISION_MAX_CALLS / CUCP_VISION_MAX_TOKENS 환경변수로 한도 설정.
# ============================================================================

$Script:VisionBudget = [pscustomobject]@{
  calls = 0
  tokens = 0
  max_calls = if ($env:CUCP_VISION_MAX_CALLS) { try { [int]$env:CUCP_VISION_MAX_CALLS } catch { $null } } else { $null }
  max_tokens = if ($env:CUCP_VISION_MAX_TOKENS) { try { [int]$env:CUCP_VISION_MAX_TOKENS } catch { $null } } else { $null }
  history = @()
}

function _Vision-CheckBudget {
  param([string]$Macro, [int]$EstimatedTokens = 1000)
  if ($Script:VisionBudget.max_calls -and $Script:VisionBudget.calls -ge $Script:VisionBudget.max_calls) {
    return @{ allowed = $false; reason = "vision_budget_calls_exceeded"; max_calls = $Script:VisionBudget.max_calls; calls = $Script:VisionBudget.calls }
  }
  if ($Script:VisionBudget.max_tokens -and ($Script:VisionBudget.tokens + $EstimatedTokens) -gt $Script:VisionBudget.max_tokens) {
    return @{ allowed = $false; reason = "vision_budget_tokens_exceeded"; max_tokens = $Script:VisionBudget.max_tokens; tokens = $Script:VisionBudget.tokens; estimated = $EstimatedTokens }
  }
  return @{ allowed = $true }
}

function _Vision-RecordCall {
  # 호출 성공 시 누적 카운터 증가 + history 한 줄.
  param([string]$Macro, [int]$Tokens = 1000)
  $Script:VisionBudget.calls = $Script:VisionBudget.calls + 1
  $Script:VisionBudget.tokens = $Script:VisionBudget.tokens + $Tokens
  $Script:VisionBudget.history += [pscustomobject]@{ ts = (Get-Date).ToString("HH:mm:ss"); macro = $Macro; tokens = $Tokens }
}

function _Vision-GateOrRecord {
  # vision 매크로 진입부 공통 게이트.
  # 한도 초과면 blocked envelope 을 직접 emit 하고 exit code 3 을 반환.
  # 통과면 호출을 카운터에 기록하고 $null 반환 (호출자는 계속 진행).
  #   반환: 3 (blocked) | $null (allowed)
  param([string]$Macro, [int]$EstimatedTokens = 1000)
  $bg = _Vision-CheckBudget -Macro $Macro -EstimatedTokens $EstimatedTokens
  if (-not $bg.allowed) {
    $payload = [pscustomobject]@{
      schema = "cucp.safety-block/v1"
      status = "blocked"
      reason = $bg.reason
      macro = $Macro
      budget = $Script:VisionBudget
      next_action = "Increase CUCP_VISION_MAX_CALLS / CUCP_VISION_MAX_TOKENS or unset to disable budget."
    }
    _Emit-Envelope -Envelope $payload -BriefLine "blocked $Macro reason=$($bg.reason)" -Depth 6
    return 3
  }
  _Vision-RecordCall -Macro $Macro -Tokens $EstimatedTokens
  return $null
}

# ============================================================================
# Invoke-NativeHelper - CUCP 자체 PowerShell helper 호출
# ============================================================================
# 외부 helper (windows-mcp, codex-win.ps1) 우회용. Win32 + UIA + Screenshot을
# 직접 호출하는 cucp-native-helper.ps1을 child PowerShell로 띄우고 JSON을
# stdout으로 받아 파싱합니다.
#
# Parameters:
#   -ArgList  string[]  helper에 그대로 전달할 인자 (예: @("-Action","windows","-Match","electron"))
#   -TimeoutMs int       타임아웃 (기본 wrapper의 InvokeTimeoutMs)
#
# Returns: pscustomobject @{
#   ExitCode  int
#   Json      psobject  (parse 성공시)
#   Raw       string    (stdout 원본)
#   Err       string    (stderr 원본)
#   ElapsedMs int
# }
# ============================================================================
$Script:LegacyCdpSourceRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
. (Join-Path $PSScriptRoot 'cucp-legacy-cdp-adapter.ps1')
. (Join-Path $PSScriptRoot 'cucp-legacy-interaction-adapter.ps1')
. (Join-Path $PSScriptRoot 'cucp-legacy-diagnostic-adapter.ps1')

function Invoke-NativeHelper {
  # ==========================================================================
  # cucp-native-helper.ps1 을 child PowerShell 프로세스로 띄우고 결과 파싱.
  # ==========================================================================
  # 책임:
  #   1. -File 모드로 helper 호출 (NoProfile / ExecutionPolicy Bypass)
  #   2. 시간 초과 시 child kill + envelope ExitCode=124 반환
  #   3. stdout/stderr 임시 파일 → 읽기 → JSON 파싱 → 반환
  #   4. exit code 정확히 추정 (PS5 의 Start-Process bug 우회)
  #
  # exit code 추정 흐름 (v1.0.0 fix):
  #   a. proc.Refresh() + [int]proc.ExitCode  ← 가장 정확
  #   b. by-PID 재조회 ([Process]::GetProcessById)  ← (a) 가 InvalidOpEx 던질 때
  #   c. JSON status 기반 보정 (partial → 2, error → 1) ← (b) 도 실패 시
  # 이 3-tier fallback 이 없으면 partial(2) / error(1) 가 wrapper exit 0 으로
  # 흘러 들어가는 잠재 버그 발생 (v0.6.0~0.8.0 까지 있던 버그).
  # ==========================================================================
  param(
    [string[]]$ArgList,
    [int]$TimeoutMs = 0,
    [switch]$ForceChild
  )
  if ($null -eq $ArgList -or $ArgList.Count -lt 2 -or
      -not [string]::Equals($ArgList[0], '-Action', [StringComparison]::OrdinalIgnoreCase) -or
      [string]::IsNullOrEmpty($ArgList[1])) {
    throw 'Native helper requests must begin with -Action and a nonempty action value.'
  }
  if ($ArgList[1].StartsWith('cdp-', [StringComparison]::OrdinalIgnoreCase)) {
    return (_Invoke-LegacyCdpNativeArgv -ArgList $ArgList -LiveAuthority:([bool]$AllowLiveControl))
  }
  if (-not $Script:NativeHelperPath) {
    return [pscustomobject]@{
      ExitCode = 1
      Json = $null
      Raw = ""
      Err = "native_helper_missing"
      ElapsedMs = 0
    }
  }
  # ==========================================================================
  # v1.6.0 — Helper Persistent Server server-first 라우팅
  # ==========================================================================
  # ForceChild=true 또는 lock 없음/stale → 즉시 child 경로 (기존 동작 보존).
  # lock valid + action 이 server whitelist 안 → pipe IPC 시도. 실패시 child fallback.
  # 결과 envelope 에 route="pipe"|"child" 표기, 외부 ExitCode 는 99 (fallback) 노출 안 함.
  # ==========================================================================
  $ipcSw = [System.Diagnostics.Stopwatch]::StartNew()
  $serverRouteAttempted = $false
  if (-not $ForceChild -and -not $env:CUCP_FORCE_CHILD) {
    $lock = _Read-LockSafely
    if ($lock -and -not (_Is-StaleLock -Lock $lock)) {
      # action 추출
      $hAction = $null
      for ($k = 0; $k -lt $ArgList.Count - 1; $k++) {
        if ($ArgList[$k] -eq "-Action") { $hAction = "$($ArgList[$k+1])"; break }
      }
      if ($hAction -and ($Script:HelperServerSupported -contains $hAction)) {
        $serverRouteAttempted = $true
        # 옵션 → hashtable
        $hArgs = @{}
        $optKeys = @("Match","TargetMatch","TargetHwnd")
        foreach ($oK in $optKeys) {
          for ($k = 0; $k -lt $ArgList.Count - 1; $k++) {
            if ($ArgList[$k] -eq "-$oK") { $hArgs[$oK] = "$($ArgList[$k+1])"; break }
          }
        }
        $tm = $TimeoutMs
        if ($tm -le 0) { $tm = $Script:InvokeTimeoutMs }
        try {
          $resp = Invoke-HelperPipe -Action $hAction -ArgsHash $hArgs -TimeoutMs $tm
          $ipcSw.Stop()
          if ($resp -and $resp.exit_code -ne 99) {
            # 정상 응답 — pipe 경로로 envelope 구성
            $exitMapped = [int]$resp.exit_code
            $jsonObj = $resp.result
            $rawJson = $jsonObj | ConvertTo-Json -Compress -Depth 12
            return [pscustomobject]@{
              ExitCode = $exitMapped
              Json = $jsonObj
              Raw = $rawJson
              Err = if ($resp.error) { "$($resp.error)" } else { "" }
              ElapsedMs = [int]$ipcSw.Elapsed.TotalMilliseconds
              FromHotCache = $false
              Route = "pipe"
            }
          }
          # exit_code=99 → fallback_required, child 경로로 빠짐
        } catch {
          # pipe broken / timeout / id mismatch → child fallback
          # stale 검사 한 번 더 (server 가 죽었을 수 있음)
          $lock2 = _Read-LockSafely
          if ($lock2 -and (_Is-StaleLock -Lock $lock2)) { _Try-Delete-Lock }
          Write-WrapperLog -Message "PIPE FAILED ($($_.Exception.Message)) → child fallback for action=$hAction"
        }
      }
    }
  }
  # ==========================================================================
  # v1.5.0 Phase 1: in-memory hot cache (TTL 500ms)
  # 같은 read-only action 을 짧은 시간 내 반복 호출 시 child process spawn 우회.
  # 적용 대상: -Action windows / health / focused / modal-detect 만.
  # 키: action + 주요 옵션 (Match, TargetMatch, TargetHwnd) 정규화.
  # `-CacheSeconds 0` 또는 환경 변수 `CUCP_HOT_CACHE_DISABLE=1` 시 비활성.
  # ==========================================================================
  $hotKey = $null
  $hotEligible = $false
  if (-not $env:CUCP_HOT_CACHE_DISABLE -and $Script:CacheSeconds -gt 0) {
    $hotAction = $null
    for ($i = 0; $i -lt $ArgList.Count - 1; $i++) {
      if ($ArgList[$i] -eq "-Action") { $hotAction = $ArgList[$i+1]; break }
    }
    $hotEligibleActions = @("windows","health","focused","modal-detect")
    if ($hotAction -and ($hotEligibleActions -contains $hotAction)) {
      $hotEligible = $true
      $hotKey = "$hotAction|"
      foreach ($optName in @("-Match","-TargetMatch","-TargetHwnd")) {
        for ($j = 0; $j -lt $ArgList.Count - 1; $j++) {
          if ($ArgList[$j] -eq $optName) { $hotKey += "$optName=$($ArgList[$j+1])|"; break }
        }
      }
    }
  }
  if (-not $Script:HotCache) { $Script:HotCache = @{} }
  if (-not $Script:HotCacheStats) { $Script:HotCacheStats = @{ hits = 0; misses = 0; evictions = 0 } }
  if ($hotEligible -and $hotKey -and $Script:HotCache.ContainsKey($hotKey)) {
    $entry = $Script:HotCache[$hotKey]
    $nowTicks = [DateTime]::UtcNow.Ticks
    if ($entry.expires_ticks -gt $nowTicks) {
      $Script:HotCacheStats.hits++
      return [pscustomobject]@{
        ExitCode = $entry.exit_code
        Json = $entry.json
        Raw = $entry.raw
        Err = $null
        ElapsedMs = 0
        FromHotCache = $true
        Route = "hot-cache"
      }
    } else {
      $Script:HotCacheStats.evictions++
      [void]$Script:HotCache.Remove($hotKey)
    }
  }
  if ($hotEligible) { $Script:HotCacheStats.misses++ }
  if ($TimeoutMs -le 0) { $TimeoutMs = $Script:InvokeTimeoutMs }
  $sw = [System.Diagnostics.Stopwatch]::StartNew()
  $stdoutFile = Join-Path $Script:CacheDir ("native-" + [guid]::NewGuid().ToString("N") + ".json")
  $stderrFile = $stdoutFile + ".err"
  try {
    $allArgs = @("-NoProfile","-ExecutionPolicy","Bypass","-File",$Script:NativeHelperPath) + $ArgList
    $procArgs = ConvertTo-ProcessArgumentString -ArgList $allArgs
    $proc = Start-Process -FilePath "powershell" -ArgumentList $procArgs `
      -RedirectStandardOutput $stdoutFile -RedirectStandardError $stderrFile `
      -NoNewWindow -PassThru
    $exited = $proc.WaitForExit($TimeoutMs)
    if (-not $exited) {
      try { $proc.Kill() } catch { }
      try { [void]$proc.WaitForExit(3000) } catch { }
      $sw.Stop()
      Write-WrapperLog -Message "NATIVE TIMEOUT $($ArgList -join ' ')"
      return [pscustomobject]@{
        ExitCode = 124
        Json = $null
        Raw = ""
        Err = "TIMEOUT after ${TimeoutMs}ms"
        ElapsedMs = [int]$sw.Elapsed.TotalMilliseconds
      }
    }
    $sw.Stop()
    # Start-Process -PassThru 로 만든 Process 객체는 timeout-overload WaitForExit
    # 후 ExitCode 속성이 InvalidOperationException 을 던질 수 있음 (Process.HasExited 이슈).
    # 핸들 리프레시 후 [System.Diagnostics.Process]::GetProcessById 로 재조회.
    $exitCode = 0
    try {
      $proc.Refresh()
      $exitCode = [int]$proc.ExitCode
    } catch {
      # Process.ExitCode 가 throw 면 by-pid 로 다시 시도
      try {
        $pid2 = $proc.Id
        $p2 = [System.Diagnostics.Process]::GetProcessById($pid2)
        $exitCode = [int]$p2.ExitCode
      } catch {
        # 그래도 실패하면 stdout JSON 의 status 로 추정
        $exitCode = 0
      }
    }
    $raw = ""
    $err = ""
    if (Test-Path -LiteralPath $stdoutFile) { $raw = Get-Content -LiteralPath $stdoutFile -Raw -Encoding UTF8 }
    if (Test-Path -LiteralPath $stderrFile) { $err = Get-Content -LiteralPath $stderrFile -Raw -Encoding UTF8 }
    $json = $null
    if ($raw -and $raw.Trim().Length -gt 0) {
      try { $json = $raw | ConvertFrom-Json -ErrorAction Stop } catch { }
    }
    # ExitCode 추정 실패 시 JSON status 기반으로 보정
    if ($exitCode -eq 0 -and $json) {
      switch ("$($json.status)") {
        "partial" { $exitCode = 2 }
        "error"   { $exitCode = 1 }
      }
    }
    # v1.5.0 Phase 1: hot cache write (정상 응답만, ok+JSON 있을 때, eligible action 만)
    if ($hotEligible -and $hotKey -and $exitCode -eq 0 -and $json) {
      try {
        $ttlMs = 500
        $expiresTicks = [DateTime]::UtcNow.AddMilliseconds($ttlMs).Ticks
        $Script:HotCache[$hotKey] = @{
          exit_code = [int]$exitCode
          json = $json
          raw = $raw
          expires_ticks = $expiresTicks
        }
        # 메모리 보호: 캐시 항목 16개 초과 시 가장 오래된 것 evict
        if ($Script:HotCache.Count -gt 16) {
          $oldest = $Script:HotCache.GetEnumerator() | Sort-Object { $_.Value.expires_ticks } | Select-Object -First 1
          [void]$Script:HotCache.Remove($oldest.Key)
          $Script:HotCacheStats.evictions++
        }
      } catch { }
    }
    return [pscustomobject]@{
      ExitCode = $exitCode
      Json = $json
      Raw = $raw
      Err = $err
      ElapsedMs = [int]$sw.Elapsed.TotalMilliseconds
      FromHotCache = $false
      Route = "child"
    }
  } catch {
    $sw.Stop()
    return [pscustomobject]@{
      ExitCode = 1
      Json = $null
      Raw = ""
      Err = $_.Exception.Message
      ElapsedMs = [int]$sw.Elapsed.TotalMilliseconds
      Route = "child-error"
    }
  } finally {
    Remove-Item -LiteralPath $stdoutFile -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $stderrFile -Force -ErrorAction SilentlyContinue
  }
}

# ----- logging --------------------------------------------------------------
# NOTE: Write-WrapperLog 는 파일 상단(라인 ~201, $Script:WrapperLog 설정 직후)에서
# 이미 정의된다. 외부 업데이트본 병합 과정에서 이 위치에 중복 정의가 들어왔던 것을
# v2.1.1 정리 단계에서 제거했다. Write-Notice / ConvertTo-ProcessArgumentString 은
# 여기가 유일 정의이므로 보존한다.
function Write-Notice {
  param([string]$Message, [string]$Level = "INFO")
  if (-not $Quiet) {
    switch ($Level) {
      "ERROR"   { Write-Host "[CUCP] $Message" -ForegroundColor Red }
      "WARN"    { Write-Host "[CUCP] $Message" -ForegroundColor Yellow }
      "OK"      { Write-Host "[CUCP] $Message" -ForegroundColor Green }
      "BRIEF"   { Write-Host $Message }
      default   { Write-Host "[CUCP] $Message" -ForegroundColor Cyan }
    }
  }
  Write-WrapperLog -Message "$Level $Message"
}

function ConvertTo-ProcessArgumentString {
  param([string[]]$ArgList)
  $quoted = @()
  foreach ($arg in $ArgList) {
    if ($null -eq $arg) {
      $quoted += '""'
    } elseif ($arg -match '[\s"]') {
      $escaped = $arg -replace '"', '\"'
      $quoted += '"' + $escaped + '"'
    } else {
      $quoted += $arg
    }
  }
  return ($quoted -join " ")
}

# ----- prerequisites --------------------------------------------------------
function Test-Tool { param([string]$Name)
  try { $null = Get-Command $Name -ErrorAction Stop; return $true } catch { return $false }
}

if (-not (Test-Tool "node")) {
  Write-Notice -Level "ERROR" -Message "node 명령을 찾을 수 없습니다. Node.js 20+가 필요합니다."
  throw "node not found in PATH"
}

if (-not $Script:CliPath -or -not (Test-Path -LiteralPath $Script:CliPath)) {
  Write-Notice -Level "WARN" -Message "CUCP CLI를 찾지 못했습니다. native/read-only 매크로만 사용할 수 있습니다."
}

# ----- core invocation ------------------------------------------------------
function Invoke-Cucp {
  param([string[]]$ArgList, [switch]$CaptureJson)

  $invokeId = [guid]::NewGuid().ToString("N").Substring(0, 12)
  $invokeSw = [System.Diagnostics.Stopwatch]::StartNew()
  Write-WrapperLog -Message "INVOKE [$invokeId] $($ArgList -join ' ')"

  # CLI 경로 검증: 비어있으면 즉시 envelope 에러 반환 (외부 helper 의존 없는
  # native 매크로는 이 경로를 우회함). cli.mjs 가 잘못 잡힌 경우(예: CUCP Lite)
  # 호출 자체가 부적절한 메시지를 내는 것을 방지.
  if (-not $Script:CliPath -or -not (Test-Path -LiteralPath $Script:CliPath)) {
    Write-WrapperLog -Message "INVOKE [$invokeId] aborted: cli.mjs not found"
    return [pscustomobject]@{
      ExitCode = 1
      Json = [pscustomobject]@{
        status = "error"
        error_type = "cli_missing"
        summary = "CUCP control-plane CLI (cli.mjs) was not found"
        recommended_action = "Set CUCP_CLI_PATH env var to the desktop control cli.mjs, or use 'macro native-*' commands which require no external CLI."
      }
      Raw = ""
      Err = "cli.mjs not found"
      FilePath = $null
      CommandId = $invokeId
      ElapsedMs = 0
    }
  }

  if ($CaptureJson) {
    $stdoutFile = Join-Path $Script:CacheDir ("invoke-" + [guid]::NewGuid().ToString("N") + ".json")
    try {
      # Use System.Diagnostics.Process for reliable arg passing + UTF-8 stdout
      $psi = New-Object System.Diagnostics.ProcessStartInfo
      $psi.FileName = "node"
      $psi.RedirectStandardOutput = $true
      $psi.RedirectStandardError = $true
      $psi.UseShellExecute = $false
      $psi.CreateNoWindow = $true
      $psi.StandardOutputEncoding = [System.Text.Encoding]::UTF8
      $psi.StandardErrorEncoding = [System.Text.Encoding]::UTF8
      $psi.Arguments = ""
      $allArgs = @($Script:CliPath) + $ArgList
      foreach ($a in $allArgs) {
        if ($a -match '[\s"]') {
          $escaped = $a -replace '"', '\"'
          $psi.Arguments += '"' + $escaped + '" '
        } else {
          $psi.Arguments += $a + ' '
        }
      }
      $stderrFile = Join-Path $Script:CacheDir ("invoke-" + [guid]::NewGuid().ToString("N") + ".stderr.txt")
      $proc = Start-Process -FilePath "node" `
        -ArgumentList $psi.Arguments `
        -RedirectStandardOutput $stdoutFile `
        -RedirectStandardError $stderrFile `
        -WindowStyle Hidden `
        -PassThru
      $exited = $proc.WaitForExit($Script:InvokeTimeoutMs)
      if (-not $exited) {
        try { $proc.Kill() } catch { }
        try { [void]$proc.WaitForExit(5000) } catch { }
        $invokeSw.Stop()
        $elapsed = [int]$invokeSw.Elapsed.TotalMilliseconds
        Write-WrapperLog -Message "TIMEOUT [$invokeId] $($ArgList -join ' ') after ${Script:InvokeTimeoutMs}ms (elapsed=${elapsed}ms)"
        $envelope = [pscustomobject]@{
          status = "error"
          error_type = "invoke_timeout"
          command_id = $invokeId
          elapsed_ms = $elapsed
          timeout_ms = $Script:InvokeTimeoutMs
          summary = "CUCP command timed out after ${Script:InvokeTimeoutMs}ms"
          recommended_action = "Increase -InvokeTimeoutMs or run 'cucp macro ensure-helper'. Failing command: $($ArgList -join ' ')"
        }
        return [pscustomobject]@{
          ExitCode = 124
          Json = $envelope
          Raw = if (Test-Path -LiteralPath $stdoutFile) { [System.IO.File]::ReadAllText($stdoutFile, [System.Text.Encoding]::UTF8) } else { "" }
          Err = "CUCP command timed out after ${Script:InvokeTimeoutMs}ms (id=$invokeId, elapsed=${elapsed}ms)"
          FilePath = $stdoutFile
          CommandId = $invokeId
          ElapsedMs = $elapsed
        }
      }
      # 이미 WaitForExit($InvokeTimeoutMs) 로 정상 종료를 확인한 경로다. 여기서의
      # 두 번째 대기는 redirect 된 stdout/stderr 의 flush 완료 보장이 목적이며,
      # 무바운드 WaitForExit() 는 이론상 핸들 잔류 시 행(hang) 위험이 있으므로
      # 짧은 바운드(5s)를 준다. 초과해도 이미 exit 한 상태라 결과 읽기에 지장 없음.
      try { [void]$proc.WaitForExit(5000) } catch { }
      $invokeSw.Stop()
      $elapsed = [int]$invokeSw.Elapsed.TotalMilliseconds
      $raw = if (Test-Path -LiteralPath $stdoutFile) { [System.IO.File]::ReadAllText($stdoutFile, [System.Text.Encoding]::UTF8) } else { "" }
      $err = if (Test-Path -LiteralPath $stderrFile) { [System.IO.File]::ReadAllText($stderrFile, [System.Text.Encoding]::UTF8) } else { "" }
      try { $proc.Refresh() } catch { }
      $code = $proc.ExitCode
      if ($null -eq $code -and $raw -and $raw.Trim().Length -gt 0) { $code = 0 }
      $json = $null
      if ($raw -and $raw.Trim().Length -gt 0) {
        try { $json = $raw | ConvertFrom-Json -ErrorAction Stop } catch { $json = $null }
      }
      return [pscustomobject]@{
        ExitCode = $code
        Json = $json
        Raw = $raw
        Err = $err
        FilePath = $stdoutFile
        CommandId = $invokeId
        ElapsedMs = $elapsed
      }
    } catch {
      $invokeSw.Stop()
      return [pscustomobject]@{
        ExitCode = 1
        Json = $null
        Raw = $_.Exception.Message
        Err = ""
        FilePath = $null
        CommandId = $invokeId
        ElapsedMs = [int]$invokeSw.Elapsed.TotalMilliseconds
      }
    }
  } else {
    & node $Script:CliPath @ArgList
    $invokeSw.Stop()
    return [pscustomobject]@{
      ExitCode = $LASTEXITCODE
      Json = $null
      Raw = ""
      FilePath = $null
      CommandId = $invokeId
      ElapsedMs = [int]$invokeSw.Elapsed.TotalMilliseconds
    }
  }
}

# ----- live-control gate ----------------------------------------------------
function Test-LiveControlRequest {
  param([string[]]$ArgList)
  if ($null -eq $ArgList -or $ArgList.Count -lt 1) { return $false }

  if ($ArgList[0] -eq "act") { return $true }
  if ($ArgList.Count -ge 2 -and $ArgList[0] -eq "app" -and $ArgList[1] -eq "switch") { return $true }
  if ($ArgList.Count -ge 2 -and $ArgList[0] -eq "plan" -and $ArgList[1] -eq "run") { return $true }
  if ($ArgList.Count -ge 2 -and $ArgList[0] -eq "scenario" -and $ArgList[1] -eq "run" -and ($ArgList -contains "--execute")) {
    return $true
  }

  if ($ArgList.Count -ge 3 -and $ArgList[0] -eq "desktop" -and $ArgList[1] -eq "benchmark") {
    $op = $ArgList[2]
    $isPreflight = $ArgList -contains "--preflight-only"
    $isVerify = $ArgList -contains "--verify-only"
    $isDry = $ArgList -contains "--dry-run"
    if ($op -eq "runbook") {
      if ($isDry -or $isVerify -or $isPreflight) { return $false }
      if ($ArgList -contains "--allow-live-control") { return $true }
    }
    if (($op -eq "run" -or $op -eq "collect") -and ($ArgList -contains "--live") -and -not $isPreflight) {
      return $true
    }
  }

  if ($ArgList.Count -ge 2 -and $ArgList[0] -eq "l5") {
    $sub = $ArgList[1]
    if ($sub -eq "run") { return $true }
    if (($sub -eq "resume" -or $sub -eq "live-eval") -and ($ArgList -contains "--allow-control")) { return $true }
  }

  return $false
}

function Test-CoordinateMissingObservation {
  param([string[]]$ArgList)
  if ($ArgList.Count -lt 2 -or $ArgList[0] -ne "act") { return $false }
  $coordSubs = @("click", "right-click", "drag", "scroll", "type")
  if (-not ($coordSubs -contains $ArgList[1])) { return $false }
  $hasCoord = ($ArgList -contains "--x") -or ($ArgList -contains "--from-x")
  if (-not $hasCoord) { return $false }
  if ($ArgList -contains "--after") { return $false }
  if ($ArgList -contains "--force") { return $false }
  return $true
}

function Assert-Authorized {
  param([string[]]$ArgList)
  $isLive = Test-LiveControlRequest -ArgList $ArgList
  $missingObs = Test-CoordinateMissingObservation -ArgList $ArgList
  if ($missingObs) {
    Write-Notice -Level "ERROR" -Message "좌표 기반 act 명령은 --after <observation-id>가 필요합니다. 'observe appshot'을 먼저 실행하거나 매크로(click-label 등)를 사용하세요."
    throw "Coordinate-based act command requires --after <observation-id>."
  }
  if ($isLive -and -not $AllowLiveControl) {
    Write-Notice -Level "ERROR" -Message "라이브 데스크톱 조작이 차단되었습니다. 사용자가 명시 허락한 경우만 -AllowLiveControl 와 함께 다시 실행하세요."
    Write-Notice -Level "WARN"  -Message "차단된 명령: $($ArgList -join ' ')"
    throw "Live desktop control blocked. Re-run with -AllowLiveControl after explicit user authorization."
  }
  if ($isLive) {
    Write-Notice -Level "WARN" -Message "라이브 컨트롤 모드: $($ArgList -join ' ')"
  } else {
    Write-Notice -Level "INFO" -Message "관찰/시뮬레이션 모드: $($ArgList -join ' ')"
  }
}

# ----- observation cache ----------------------------------------------------
function Get-CacheKey {
  param([string]$Match)
  $base = if ([string]::IsNullOrWhiteSpace($Match)) { "_full" } else { $Match.ToLowerInvariant() }
  $bytes = [System.Text.Encoding]::UTF8.GetBytes($base)
  $hash = [System.Security.Cryptography.MD5]::Create().ComputeHash($bytes)
  return ($hash | ForEach-Object { $_.ToString("x2") }) -join ""
}

function Get-CachedAppshot {
  param([string]$Match, [int]$MaxAgeSeconds)
  if ($MaxAgeSeconds -le 0) { return $null }
  $key = Get-CacheKey -Match $Match
  $cacheFile = Join-Path $Script:CacheDir "appshot-$key.json"
  if (-not (Test-Path -LiteralPath $cacheFile)) { return $null }
  $info = Get-Item -LiteralPath $cacheFile
  $age = (Get-Date) - $info.LastWriteTime
  if ($age.TotalSeconds -gt $MaxAgeSeconds) { return $null }
  try {
    $json = Get-Content -LiteralPath $cacheFile -Raw -Encoding UTF8 | ConvertFrom-Json -ErrorAction Stop
    Write-Notice -Level "INFO" -Message "appshot 캐시 적중 (age=$([int]$age.TotalSeconds)s, match='$Match')"
    return [pscustomobject]@{ Json = $json; Path = $cacheFile; FromCache = $true }
  } catch { return $null }
}

function Save-AppshotCache {
  param([string]$Match, [string]$SourceFile)
  if (-not (Test-Path -LiteralPath $SourceFile)) { return }
  $key = Get-CacheKey -Match $Match
  $cacheFile = Join-Path $Script:CacheDir "appshot-$key.json"
  Copy-Item -LiteralPath $SourceFile -Destination $cacheFile -Force
}

function Invoke-Appshot {
  <#
    Captures appshot, returns [pscustomobject]{ Json, Path, ObservationId, FocusedWindow, Items, FusedElements, FromCache }.
    Uses cache if Match given and a fresh capture exists within $CacheSeconds.
  #>
  param(
    [string]$Match,
    [switch]$Semantic = $true,
    [switch]$NoCache,
    [int]$CacheMaxSeconds = $CacheSeconds
  )

  if (-not $NoCache) {
    $cached = Get-CachedAppshot -Match $Match -MaxAgeSeconds $CacheMaxSeconds
    if ($cached) {
      return _Build-AppshotResult -Json $cached.Json -Path $cached.Path -FromCache $true
    }
  }

  $outFile = Join-Path $Script:CacheDir ("appshot-fresh-" + [guid]::NewGuid().ToString("N") + ".json")
  $cucpArgs = @("observe", "appshot")
  if ($Match) { $cucpArgs += @("--match", $Match) }
  if ($Semantic) { $cucpArgs += "--annotate" } else { $cucpArgs += "--no-semantic" }
  $cucpArgs += @("--out", $outFile)

  $r = Invoke-Cucp -ArgList $cucpArgs -CaptureJson
  if ($r.ExitCode -ne 0 -or -not (Test-Path -LiteralPath $outFile)) {
    Write-Notice -Level "ERROR" -Message "appshot 실패 (exit=$($r.ExitCode))"
    return $null
  }

  $json = Get-Content -LiteralPath $outFile -Raw -Encoding UTF8 | ConvertFrom-Json -ErrorAction Stop
  Save-AppshotCache -Match $Match -SourceFile $outFile
  $result = _Build-AppshotResult -Json $json -Path $outFile -FromCache $false
  $affCount = 0
  if ($result.Affordances) { $affCount = $result.Affordances.Count }
  # Push to working memory
  _Trajectory-Append -Kind "observation" -Payload @{
    observation_id = $result.ObservationId
    focused_window = $result.FocusedWindow
    match = $Match
    affordance_count = $affCount
    from_cache = $false
  }
  return $result
}

function _Build-AppshotResult {
  param($Json, $Path, [bool]$FromCache)

  # The CUCP envelope when written via --out can be either an envelope
  # ({status, artifacts}) or just the appshot artifact. Handle both.
  $appshot = $null
  $fusion = $null

  if ($Json.artifacts) {
    foreach ($a in $Json.artifacts) {
      if ($a.type -eq "desktop_appshot") { $appshot = $a }
      if ($a.type -eq "desktop_observation_fusion") { $fusion = $a }
    }
  }
  if (-not $appshot -and $Json.type -eq "desktop_appshot") { $appshot = $Json }

  $items = @()
  if ($appshot.text.items) { $items = $appshot.text.items }

  $fused = @()
  if ($fusion.fused_elements) { $fused = $fusion.fused_elements }

  # grounded_elements is the affordance pool emitted by observation-fusion.mjs
  # when the host build supports it. If absent, the wrapper falls back to a
  # native UIA tree walk so label grounding still works.
  $grounded = @()
  if ($fusion.grounded_elements) { $grounded = $fusion.grounded_elements }

  if (-not $grounded -or $grounded.Count -eq 0) {
    $grounded = _Get-UIAffordances -FocusedWindow $appshot.focused_window
  }

  # Affordance index: id -> element.
  $affordances = @{}
  foreach ($g in $grounded) {
    if ($g.affordance_id -and $g.rect) { $affordances[$g.affordance_id] = $g }
  }
  foreach ($t in $items) {
    if ($t.affordance_id -and $t.rect -and -not $affordances.ContainsKey($t.affordance_id)) {
      $affordances[$t.affordance_id] = $t
    }
  }

  return [pscustomobject]@{
    Json           = $Json
    Path           = $Path
    FromCache      = $FromCache
    ObservationId  = $appshot.observation_id
    FocusedWindow  = $appshot.focused_window
    ScreenshotPath = $appshot.screenshot_path
    Items          = $items
    FusedElements  = $fused
    Grounded       = $grounded
    Affordances    = $affordances
  }
}

# ----- Win32 window enumeration fallback ----------------------------------
# 헬퍼/CLI snapshot이 비어 돌아올 때 (예: helper가 막 시작했고 캐시가 비어 있을 때,
# CSRSS/UWP shell windows만 잡혀서 사용자 앱이 안 보일 때) 대신 사용할 수 있는
# 결정적 Win32 window enumeration. read-only이고 actuation 절대 안 함.
$Script:_Win32Loaded = $false

function _Ensure-Win32Loaded {
  if ($Script:_Win32Loaded) { return $true }
  try {
    $interopPath = $env:CUCP_LEGACY_INTEROP_DLL
    if (-not $interopPath) { $interopPath = Join-Path $PSScriptRoot '..\pcucp-next\bin\legacy\PcuCp.LegacyInterop.dll' }
    $existing = 'CucpWin32' -as [type]
    if ($existing -and $existing.Assembly.GetName().Name -ne 'PcuCp.LegacyInterop') {
      throw 'A different legacy interop type is already loaded. Restart this PowerShell process with the matching runtime.'
    }
    if (-not $existing) {
      if (-not (Test-Path -LiteralPath $interopPath -PathType Leaf)) { throw 'Legacy interop DLL missing. Run python pcucp-next/packaging/publish_legacy_interop.py or set CUCP_LEGACY_INTEROP_DLL.' }
      Add-Type -LiteralPath $interopPath -ErrorAction Stop
    }
    $Script:_Win32Loaded = $true
    return $true
  } catch {
    Write-WrapperLog -Message "Win32 enumerate load failed: $($_.Exception.Message)"
    return $false
  }
}

function _Enumerate-Win32Windows {
  <#
    Returns an array of objects with: hwnd, title, class, pid, process, visible,
    minimized, foreground, rect{x,y,width,height}. Optional Match filters by
    case-insensitive substring of title or process.
  #>
  param([string]$Match)
  if (-not (_Ensure-Win32Loaded)) { return @() }
  try {
    $list = [CucpWin32]::EnumerateTopLevel()
    $out = New-Object System.Collections.ArrayList
    foreach ($w in $list) {
      if ($Match) {
        $needle = $Match.ToLowerInvariant()
        $tt = if ($w.Title) { $w.Title.ToLowerInvariant() } else { "" }
        $pp = if ($w.ProcessName) { $w.ProcessName.ToLowerInvariant() } else { "" }
        if ($tt.IndexOf($needle) -lt 0 -and $pp.IndexOf($needle) -lt 0) { continue }
      }
      [void]$out.Add([pscustomobject]@{
        hwnd = [int64]$w.Hwnd
        title = $w.Title
        class = $w.ClassName
        pid = [int]$w.Pid
        process = $w.ProcessName
        visible = $w.Visible
        minimized = $w.Minimized
        foreground = $w.Foreground
        rect = [pscustomobject]@{
          x = $w.X; y = $w.Y; width = $w.Width; height = $w.Height
        }
      })
    }
    return $out.ToArray()
  } catch {
    Write-WrapperLog -Message "Win32 enumerate failed: $($_.Exception.Message)"
    return @()
  }
}

# ----- native UIA fallback --------------------------------------------------
$Script:_UIALoaded = $false

function _Ensure-UIALoaded {
  if ($Script:_UIALoaded) { return $true }
  try {
    Add-Type -AssemblyName UIAutomationClient -ErrorAction Stop
    Add-Type -AssemblyName UIAutomationTypes -ErrorAction Stop
    $Script:_UIALoaded = $true
    return $true
  } catch {
    Write-WrapperLog -Message "UIA load failed: $($_.Exception.Message)"
    return $false
  }
}

function _Slug {
  param([string]$Value)
  if ([string]::IsNullOrWhiteSpace($Value)) { return "unknown" }
  $s = $Value.ToLowerInvariant()
  $s = ($s -replace '[^a-z0-9가-힣]+', '-').Trim('-')
  if ([string]::IsNullOrEmpty($s)) { return "unknown" }
  if ($s.Length -gt 32) { return $s.Substring(0, 32) }
  return $s
}

function _Get-UIAffordances {
  <#
    Walks the UIA tree under the focused window (or root if no focus) and
    returns a list of grounded element objects compatible with the
    grounded_elements schema produced by observation-fusion.mjs.
    Roles included: button, edit, hyperlink, menuitem, tabitem, listitem,
    treeitem, checkbox, radiobutton, combobox, document, text.

    SMALL ICON FRIENDLY (sprint v4):
    - Includes elements down to 6x6px (toolbar icons commonly 16-24px).
    - Synonym labels mined from: Name, AutomationId, HelpText (tooltip),
      AccessKey, ItemStatus, IsKeyboardFocusable hint.
    - Per-element confidence is high when AutomationId+Name agree, medium
      when only Name, low when only AutomationId/HelpText.
    - Smaller leaf elements are preferred when nested (icon inside group).
  #>
  param([string]$FocusedWindow, [int]$MaxElements = 400, [int]$MinSize = 6, [int64]$Hwnd = 0)

  if (-not (_Ensure-UIALoaded)) { return @() }

  try {
    $root = [System.Windows.Automation.AutomationElement]::RootElement
    if (-not $root) { return @() }

    # Find target window: prefer exact HWND, then focused window match, else root scan.
    $target = $root
    if ($Hwnd -gt 0) {
      try {
        $byHandle = [System.Windows.Automation.AutomationElement]::FromHandle([IntPtr]$Hwnd)
        if ($byHandle) { $target = $byHandle }
      } catch { }
    }
    if ($target -eq $root -and $FocusedWindow) {
      $cond = New-Object System.Windows.Automation.PropertyCondition `
        ([System.Windows.Automation.AutomationElement]::ControlTypeProperty),
         ([System.Windows.Automation.ControlType]::Window)
      $windows = $root.FindAll([System.Windows.Automation.TreeScope]::Children, $cond)
      $needle = $FocusedWindow.ToLowerInvariant()
      foreach ($w in $windows) {
        try {
          $name = $w.Current.Name
          if ($name -and $name.ToLowerInvariant().Contains($needle.Substring(0, [Math]::Min($needle.Length, 16)))) {
            $target = $w
            break
          }
        } catch { }
      }
    }

    # Useful control types for label grounding (Image and Pane added so we
    # can resolve toolbar icons and embedded canvases).
    $typeNames = @(
      "Button","Edit","Hyperlink","MenuItem","TabItem","ListItem",
      "TreeItem","CheckBox","RadioButton","ComboBox","Document","Text",
      "Header","SplitButton","Group","Image","ToolBar","Pane"
    )

    $results = New-Object System.Collections.Generic.List[object]
    $orCond = $null
    foreach ($tn in $typeNames) {
      $ct = [System.Windows.Automation.ControlType]::$tn
      if (-not $ct) { continue }
      $c = New-Object System.Windows.Automation.PropertyCondition `
        ([System.Windows.Automation.AutomationElement]::ControlTypeProperty), $ct
      if (-not $orCond) { $orCond = $c }
      else { $orCond = New-Object System.Windows.Automation.OrCondition $orCond, $c }
    }
    if (-not $orCond) { return @() }

    $elements = $target.FindAll([System.Windows.Automation.TreeScope]::Descendants, $orCond)
    $count = 0
    foreach ($el in $elements) {
      if ($count -ge $MaxElements) { break }
      try {
        $cur = $el.Current
        $rect = $cur.BoundingRectangle
        if ($rect.IsEmpty) { continue }
        # Accept very small icons (down to MinSize px). Reject only zero-area.
        if ($rect.Width -lt $MinSize -or $rect.Height -lt $MinSize) { continue }

        # Mine label synonyms from multiple UIA properties so small icons
        # without visible text still resolve via tooltip / AutomationId.
        $name = ""; try { $name = "$($cur.Name)" } catch { }
        $autoId = ""; try { $autoId = "$($cur.AutomationId)" } catch { }
        $help = ""; try { $help = "$($cur.HelpText)" } catch { }
        $accessKey = ""; try { $accessKey = "$($cur.AccessKey)" } catch { }
        $status = ""; try { $status = "$($cur.ItemStatus)" } catch { }
        $clazz = ""; try { $clazz = "$($cur.ClassName)" } catch { }

        $synonyms = New-Object System.Collections.Generic.HashSet[string]
        foreach ($s in @($name, $autoId, $help, $accessKey, $status)) {
          if (-not [string]::IsNullOrWhiteSpace($s)) { [void]$synonyms.Add($s.Trim()) }
        }
        if ($synonyms.Count -eq 0) { continue }

        # Primary text = Name when present, else AutomationId, else HelpText.
        $text = if (-not [string]::IsNullOrWhiteSpace($name)) { $name }
                elseif (-not [string]::IsNullOrWhiteSpace($autoId)) { $autoId }
                else { $help }
        if ([string]::IsNullOrWhiteSpace($text)) { continue }

        $role = ""; try { $role = $cur.LocalizedControlType } catch { }
        if ([string]::IsNullOrWhiteSpace($role)) {
          try { $role = $cur.ControlType.ProgrammaticName } catch { }
        }

        # Derived attributes that downstream selector ranking can use.
        $isOffscreen = $false; try { $isOffscreen = [bool]$cur.IsOffscreen } catch { }
        $isEnabled = $true;   try { $isEnabled   = [bool]$cur.IsEnabled }   catch { }
        $isFocusable = $false; try { $isFocusable = [bool]$cur.IsKeyboardFocusable } catch { }
        if ($isOffscreen) { continue }   # never click invisible items

        # Confidence boost when multiple UIA properties agree on the label.
        $conf = "medium"
        $agree = 0
        if (-not [string]::IsNullOrWhiteSpace($name))   { $agree++ }
        if (-not [string]::IsNullOrWhiteSpace($autoId)) { $agree++ }
        if (-not [string]::IsNullOrWhiteSpace($help))   { $agree++ }
        if ($agree -ge 2) { $conf = "high" }
        elseif ($agree -eq 0) { $conf = "low" }

        $window = $FocusedWindow
        if (-not $window) {
          try { $window = $cur.Name } catch { }
        }

        $rectObj = [pscustomobject]@{
          x = [int]$rect.X
          y = [int]$rect.Y
          width = [int]$rect.Width
          height = [int]$rect.Height
        }
        $area = $rectObj.width * $rectObj.height
        $isSmall = ($rectObj.width -le 32 -and $rectObj.height -le 32)

        $w = (_Slug $window).Substring(0, [Math]::Min(24, (_Slug $window).Length))
        $r = (_Slug $role).Substring(0, [Math]::Min(16, (_Slug $role).Length))
        $t = (_Slug $text)
        $rk = "$($rectObj.x)-$($rectObj.y)-$($rectObj.width)-$($rectObj.height)"
        $afid = "aff:${w}:${r}:${t}:${rk}:uia"

        $results.Add([pscustomobject]@{
          affordance_id = $afid
          stable_id     = "window:${w}|role:${r}|text:${t}|rect:$($rectObj.x),$($rectObj.y),$($rectObj.width),$($rectObj.height)"
          text          = $text
          synonyms      = @($synonyms)
          role          = $role
          class_name    = $clazz
          window        = $window
          rect          = $rectObj
          area          = $area
          small_icon    = $isSmall
          enabled       = $isEnabled
          focusable     = $isFocusable
          access_key    = $accessKey
          tooltip       = $help
          item_status   = $status
          sources       = @("uia")
          confidence    = $conf
          source_ids    = [pscustomobject]@{ uia = $autoId }
        }) | Out-Null
        $count++
      } catch { continue }
    }
    Write-WrapperLog -Message ("UIA fallback collected $count affordances under window '" + $FocusedWindow + "' (small_icons included)")
    return $results.ToArray()
  } catch {
    Write-WrapperLog -Message "UIA fallback failed: $($_.Exception.Message)"
    return @()
  }
}

# ----- label grounding ------------------------------------------------------
function Find-Element {
  <#
    Search appshot for an element matching label/window/role.
    Searches in priority: affordances (grounded) -> fused_elements -> text items.
    Returns the matched element (with rect) or $null.
  #>
  param(
    [Parameter(Mandatory)] $Appshot,
    [Parameter(Mandatory)] [string]$Label,
    [string]$Window,
    [string]$Role,
    [switch]$Exact
  )

  $needle = $Label.ToLowerInvariant().Trim()

  # Priority 1: grounded_elements (single-source allowed, has affordance_id)
  $pool1 = @()
  if ($Appshot.Grounded) { $pool1 = $Appshot.Grounded }
  # Priority 2: fused_elements (multi-source)
  $pool2 = @()
  if ($Appshot.FusedElements) { $pool2 = $Appshot.FusedElements }
  # Priority 3: text items that have rect (last resort)
  $pool3 = @()
  if ($Appshot.Items) {
    foreach ($it in $Appshot.Items) {
      if ($it.rect) { $pool3 += $it }
    }
  }

  function _ScorePool { param($Pool, $Tier)
    $hits = @()
    foreach ($el in $Pool) {
      if (-not $el.text -or -not $el.rect) { continue }
      if ($Window -and $el.window -and ($el.window.ToLowerInvariant() -notmatch [regex]::Escape($Window.ToLowerInvariant()))) { continue }
      if ($Role -and $el.role -and ($el.role.ToLowerInvariant() -ne $Role.ToLowerInvariant())) { continue }

      # Mine all label sources: primary text + synonyms (Name/AutomationId/
      # HelpText/AccessKey/ItemStatus collected by _Get-UIAffordances).
      $haystacks = New-Object System.Collections.Generic.List[string]
      [void]$haystacks.Add($el.text.ToString().ToLowerInvariant())
      if ($el.synonyms) {
        foreach ($s in $el.synonyms) {
          if (-not [string]::IsNullOrWhiteSpace($s)) {
            $sl = $s.ToString().ToLowerInvariant()
            if (-not $haystacks.Contains($sl)) { [void]$haystacks.Add($sl) }
          }
        }
      }
      if ($el.tooltip) {
        $tl = $el.tooltip.ToString().ToLowerInvariant()
        if (-not $haystacks.Contains($tl)) { [void]$haystacks.Add($tl) }
      }

      $score = 0
      foreach ($hay in $haystacks) {
        $local = 0
        if ($script:_findExactOnly) {
          if ($hay -eq $needle) { $local = 100 }
        } else {
          if ($hay -eq $needle) { $local = 100 }
          elseif ($hay -match [regex]::Escape($needle)) { $local = 60 + (40 - [Math]::Min(40, $hay.Length - $needle.Length)) }
          elseif ($needle.Length -ge 3 -and $hay.Length -ge 3 -and ($hay.IndexOf($needle.Substring(0, [Math]::Min(3, $needle.Length))) -ge 0)) { $local = 20 }
        }
        if ($local -gt $score) { $score = $local }
      }
      if ($el.confidence) {
        if ($el.confidence -is [double] -or $el.confidence -is [int]) {
          $score += [int]([double]$el.confidence * 5)
        } elseif ($el.confidence -is [string]) {
          switch ($el.confidence.ToLowerInvariant()) {
            "high"   { $score += 4 }
            "medium" { $score += 2 }
            "low"    { $score += 1 }
            default  { }
          }
        }
      }
      # Small-icon bonus: small leaf elements are usually more specific
      # than the large group/pane that contains them. +3 nudges them
      # ahead in ambiguous cases.
      if ($el.small_icon) { $score += 3 }
      # Disabled elements are never clickable; deprioritize but don't
      # filter (caller may want to know they exist).
      if ($el.PSObject.Properties.Name -contains "enabled" -and -not $el.enabled) { $score -= 5 }

      if ($score -gt 0) {
        $hits += [pscustomobject]@{ Element = $el; Score = $score; Tier = $Tier }
      }
    }
    return $hits
  }

  $script:_findExactOnly = [bool]$Exact
  $allHits = @()
  $allHits += _ScorePool -Pool $pool1 -Tier 1
  $allHits += _ScorePool -Pool $pool2 -Tier 2
  $allHits += _ScorePool -Pool $pool3 -Tier 3

  if ($allHits.Count -eq 0) { return $null }
  $best = $allHits | Sort-Object @{Expression="Tier"; Ascending=$true}, @{Expression="Score"; Descending=$true} | Select-Object -First 1
  return $best.Element
}

function Find-AffordanceById {
  param([Parameter(Mandatory)] $Appshot, [Parameter(Mandatory)] [string]$Id)
  if ($Appshot.Affordances -and $Appshot.Affordances.ContainsKey($Id)) {
    return $Appshot.Affordances[$Id]
  }
  return $null
}

function Get-ElementCenter {
  param($Element)
  if (-not $Element -or -not $Element.rect) { return $null }
  $cx = [int]($Element.rect.x + ($Element.rect.width / 2))
  $cy = [int]($Element.rect.y + ($Element.rect.height / 2))
  return [pscustomobject]@{ X = $cx; Y = $cy }
}

# ----- macros ---------------------------------------------------------------
function Invoke-Macro {
  param([string[]]$ArgList)

  $sub = $ArgList[1]
  $rest = if ($ArgList.Count -gt 2) { $ArgList[2..($ArgList.Count-1)] } else { @() }

  # 직접 호출 시 sensitive 분류 게이트를 거치는 live 매크로 목록.
  # NOTE(v2.1.1): notify / multi-select / multi-edit / process / registry 는 본체
  # 미구현(_Macro-NotImplemented 로 처리)이라 이 목록에서 제외했다. 미구현 매크로를
  # sensitive 분류 대상에 두면 surface 정합성이 깨지기 때문. clipboard 는 구현돼 있어 유지.
  $directSafetyLiveMacros = @(
    "app-launch","app-close","with-app","focus-window","focus-verify",
    "click-label","double-click-label","right-click-label","click-id","click-point",
    "fill-label","shortcut","shortcut-native","type-native","uia-click-label",
    "uia-invoke","uia-set-value","uia-toggle","safe-type","smart-click","form-run",
    "icon-click","vision-click","vision-click-precise","click-and-verify",
    "click-and-verify-screen","ocr-click","ocr-uia-invoke","cdp-type","cdp-click",
    "cdp-eval","cdp-smart-click","cdp-smart-type","auto-do","goal","clipboard",
    "mouse-verify","cdp-prosemirror-insert","ime-paste","safe-type-ime",
    "recovery-run"
  )
  if ($AllowLiveControl -and ($directSafetyLiveMacros -contains $sub) -and -not (_Read-StandaloneConfirmation -Rest $rest)) {
    $directSafety = _Classify-SafetyFromText -Text ((@($sub) + @($rest)) -join " ") -MacroName $sub
    if ($directSafety.requires_explicit_confirmation) {
      $payload = [pscustomobject]@{
        schema = "cucp.safety-block/v1"
        status = "blocked"
        reason = "sensitive_action_requires_confirmation"
        macro = $sub
        confirmation_flag = "--confirm-sensitive"
        safety = $directSafety
        next_action = "Re-run with --confirm-sensitive only if the user explicitly approved this exact sensitive live action."
      }
      if ($Brief) { [Console]::Out.WriteLine("blocked $sub reason=sensitive_action_requires_confirmation risk=$($directSafety.risk_level)") }
      else { [Console]::Out.WriteLine(($payload | ConvertTo-Json -Depth 10)) }
      return 3
    }
  }

  switch ($sub) {
    "safety-classify" { return Invoke-MacroSafetyClassify -Rest $rest }
    "version"       { return Invoke-MacroVersion -Rest $rest }
    "recorder"      { return Invoke-MacroRecorder -Rest $rest }
    "audit-summary" { return Invoke-MacroAuditSummary -Rest $rest }
    "policy-check"  { return Invoke-MacroPolicyCheck -Rest $rest }
    "daemon"        { return Invoke-MacroDaemon -Rest $rest }
    "mouse-verify"  { return Invoke-MacroMouseVerify -Rest $rest }
    "click-label"   { return Invoke-MacroClickLabel -Rest $rest }
    "double-click-label" { return Invoke-MacroClickLabel -Rest $rest -Double }
    "right-click-label"  { return Invoke-MacroClickLabel -Rest $rest -RightClick }
    "click-id"      { return Invoke-MacroClickId -Rest $rest }
    "click-point"   { return Invoke-MacroClickPoint -Rest $rest }
    "fill-label"    { return Invoke-MacroFillLabel -Rest $rest }
    "focus-window"  { return Invoke-MacroFocusWindow -Rest $rest }
    "wait-window"   { return Invoke-MacroWaitWindow -Rest $rest }
    "wait-label"    { return Invoke-MacroWaitLabel -Rest $rest }
    "find-label"    { return Invoke-MacroFindLabel -Rest $rest }
    "list-affordances" { return Invoke-MacroListAffordances -Rest $rest }
    "shortcut"      { return Invoke-MacroShortcut -Rest $rest }
    "goal"          { return Invoke-MacroGoal -Rest $rest }
    "session"       { return Invoke-MacroSession -Rest $rest }
    "self-test"     { return Invoke-MacroSelfTest -Rest $rest }
    "trajectory"    { return Invoke-MacroTrajectory -Rest $rest }
    "ensure-helper" { return Invoke-MacroEnsureHelper -Rest $rest }
    "vision-find"   { return Invoke-MacroVisionFind -Rest $rest }
    "vision-click"  { return Invoke-MacroVisionClick -Rest $rest }
    "metrics"       { return Invoke-MacroMetrics -Rest $rest }
    "perf"          { return Invoke-MacroPerf -Rest $rest }
    "health-detail" { return Invoke-MacroHealthDetail -Rest $rest }
    "health-quick"  { return Invoke-MacroHealthQuick -Rest $rest }
    "windows"       { return Invoke-MacroWindows -Rest $rest }
    "focus-verify"  { return Invoke-MacroFocusVerify -Rest $rest }
    "log-tail"      { return Invoke-MacroLogTail -Rest $rest }
    "diagnose-lag"  { return Invoke-MacroDiagnoseLag -Rest $rest }
    "cleanup"       { return Invoke-MacroCleanup -Rest $rest }
    "icon-find"     { return Invoke-MacroIconFind -Rest $rest }
    "icon-click"    { return Invoke-MacroIconClick -Rest $rest }
    "vision-click-precise" { return Invoke-MacroVisionClickPrecise -Rest $rest }
    "screenshot"    { return Invoke-MacroScreenshot -Rest $rest }
    # ── Native helper 직통 (외부 helper 의존 없음) ─────────────────────────
    "native-health"     { return Invoke-MacroNativeHealth -Rest $rest }
    "native-windows"    { return Invoke-MacroNativeWindows -Rest $rest }
    "native-screenshot" { return Invoke-MacroNativeScreenshot -Rest $rest }
    "click-point"       { return Invoke-MacroClickPoint -Rest $rest }
    "type-native"       { return Invoke-MacroTypeNative -Rest $rest }
    "shortcut-native"   { return Invoke-MacroShortcutNative -Rest $rest }
    "uia-click-label"   { return Invoke-MacroUiaClickLabel -Rest $rest }
    # ── UIA Pattern 직접 호출 (마우스 안 움직임) ──────────────────────────
    "uia-invoke"        { return Invoke-MacroUiaInvoke -Rest $rest }
    "uia-set-value"     { return Invoke-MacroUiaSetValue -Rest $rest }
    "uia-toggle"        { return Invoke-MacroUiaToggle -Rest $rest }
    "workflow-plan"     { return Invoke-MacroWorkflowPlan -Rest $rest }
    "workflow-run"      { return Invoke-MacroWorkflowRun -Rest $rest }
    "smart-click"       { return Invoke-MacroSmartClick -Rest $rest }
    "smart-plan"        { return Invoke-MacroSmartPlan -Rest $rest }
    "app-profile"       { return Invoke-MacroAppProfile -Rest $rest }
    "task-preset"       { return Invoke-MacroTaskPreset -Rest $rest }
    "task-plan"         { return Invoke-MacroTaskPlan -Rest $rest }
    "task-run"          { return Invoke-MacroTaskRun -Rest $rest }
    "form-plan"         { return Invoke-MacroFormPlan -Rest $rest }
    "form-run"          { return Invoke-MacroFormRun -Rest $rest }
    "watch"             { return Invoke-MacroWatch -Rest $rest }
    # ── OCR (Windows.Media.Ocr) — 브라우저 캔버스 / 이미지 표면용 ──────────
    "ocr-screen"        { return Invoke-MacroOcrScreen -Rest $rest }
    "ocr-image"         { return Invoke-MacroOcrImage -Rest $rest }
    "ocr-find-text"     { return Invoke-MacroOcrFindText -Rest $rest }
    "ocr-click"         { return Invoke-MacroOcrClick -Rest $rest }
    # ── v0.9.0 OCR+UIA fusion + screenshot diff ─────────────────────────────
    "ocr-uia-fuse"      { return Invoke-MacroOcrUiaFuse -Rest $rest }
    "screenshot-diff"   { return Invoke-MacroScreenshotDiff -Rest $rest }
    "click-and-verify-screen" { return Invoke-MacroClickAndVerifyScreen -Rest $rest }
    # ── v1.0.0 OCR+UIA invoke (Name 없어도 invoke) ───────────────────────────
    "ocr-uia-invoke"    { return Invoke-MacroOcrUiaInvoke -Rest $rest }
    # ── v1.1.0 smart-click history learning ──────────────────────────────────
    "history"           { return Invoke-MacroHistory -Rest $rest }
    # ── v1.2.0 hit-test 가드 + safe-type ─────────────────────────────────────
    "coord-profile"     { return Invoke-MacroCoordProfile -Rest $rest }
    "coord-map"         { return Invoke-MacroCoordMap -Rest $rest }
    "coord-anchor"      { return Invoke-MacroCoordAnchor -Rest $rest }
    "hit-test"          { return Invoke-MacroHitTest -Rest $rest }
    "hit-test-batch"    { return Invoke-MacroHitTestBatch -Rest $rest }
    "hit-scan"          { return Invoke-MacroHitScan -Rest $rest }
    "point-plan"        { return Invoke-MacroPointPlan -Rest $rest }
    "target-validate"   { return Invoke-MacroTargetValidate -Rest $rest }
    "safe-type"         { return Invoke-MacroSafeType -Rest $rest }
    # ── v1.3.0 Electron CDP (DOM 직접 제어) ─────────────────────────────────
    "cdp-detect"        { return Invoke-MacroCdpDetect -Rest $rest }
    "cdp-eval"          { return Invoke-MacroCdpEval -Rest $rest }
    "cdp-type"          { return Invoke-MacroCdpType -Rest $rest }
    "cdp-click"         { return Invoke-MacroCdpClick -Rest $rest }
    "cdp-smart-find"    { return Invoke-MacroCdpSmartFind -Rest $rest }
    "cdp-smart-type-find" { return Invoke-MacroCdpSmartTypeFind -Rest $rest }
    "cdp-smart-click"   { return Invoke-MacroCdpSmartClick -Rest $rest }
    "cdp-smart-type"    { return Invoke-MacroCdpSmartType -Rest $rest }
    # ── v1.4.0 6 missing items ──────────────────────────────────────────────
    "cdp-deep-find"     { return Invoke-MacroCdpDeepFind -Rest $rest }
    "cdp-prosemirror-insert" { return Invoke-MacroCdpProseMirrorInsert -Rest $rest }
    "ime-paste"         { return Invoke-MacroImePaste -Rest $rest }
    "safe-type-ime"     { return Invoke-MacroSafeTypeIme -Rest $rest }
    "modal-detect"      { return Invoke-MacroModalDetect -Rest $rest }
    "recovery-plan"     { return Invoke-MacroRecoveryPlan -Rest $rest }
    "recovery-run"      { return Invoke-MacroRecoveryRun -Rest $rest }
    "precision-validate" { return Invoke-MacroPrecisionValidate -Rest $rest }
    "benchmark"         { return Invoke-MacroBenchmark -Rest $rest }
    "release-notes"     { return Invoke-MacroReleaseNotes -Rest $rest }
    # ── Windows-MCP 동등 기능 (일부는 surface 등록만, 본체 미구현) ─────────
    "clipboard"     { return Invoke-MacroClipboard -Rest $rest }
    # 아래 매크로들은 dispatcher 에 광고돼 있으나 본체 미구현 (v2.1.1 정직 처리).
    # 호출 시 raw 런타임 에러 대신 표준 not_implemented envelope 반환.
    "process"       { return _Macro-NotImplemented -Macro "process" -Hint "프로세스 조회/종료는 미구현. 위험 작업이라 게이트 설계 후 별도 구현 필요." }
    "registry"      { return _Macro-NotImplemented -Macro "registry" -Hint "레지스트리 읽기/쓰기는 미구현. 쓰기는 고위험이라 신중한 게이트 필요." }
    "notify"        { return _Macro-NotImplemented -Macro "notify" -Hint "토스트 알림은 미구현." }
    "multi-select"  { return _Macro-NotImplemented -Macro "multi-select" -Hint "다중 선택은 미구현." }
    "multi-edit"    { return _Macro-NotImplemented -Macro "multi-edit" -Hint "다중 편집은 미구현." }
    "scrape"        { return _Macro-NotImplemented -Macro "scrape" -Hint "스크레이프는 미구현. CDP/OCR 매크로로 대체 가능." }
    "dom-snapshot"  { return _Macro-NotImplemented -Macro "dom-snapshot" -Hint "DOM 스냅샷은 미구현. cdp-deep-find / cdp-eval 로 대체 가능." }
    "app-launch"    { return Invoke-MacroAppLaunch -Rest $rest }
    "app-close"     { return Invoke-MacroAppClose -Rest $rest }
    "with-app"      { return Invoke-MacroWithApp -Rest $rest }
    "click-and-verify" { return Invoke-MacroClickAndVerify -Rest $rest }
    "auto-do"       { return Invoke-MacroAutoDo -Rest $rest }
    default {
      Write-Notice -Level "ERROR" -Message "알 수 없는 매크로: $sub. 사용 가능: version, safety-classify, daemon, mouse-verify, click-label, double-click-label, right-click-label, click-id, click-point, fill-label, focus-window, focus-verify, wait-window, wait-label, find-label, list-affordances, shortcut, goal, session, self-test, trajectory, ensure-helper, vision-find, vision-click, vision-click-precise, icon-find, icon-click, screenshot, windows, log-tail, diagnose-lag, cleanup, clipboard, process, registry, notify, multi-select, multi-edit, scrape, dom-snapshot, metrics, perf, health-detail, health-quick, app-launch, app-close, with-app, click-and-verify, auto-do, native-health, native-windows, native-screenshot, type-native, shortcut-native, uia-click-label, uia-invoke, uia-set-value, uia-toggle, workflow-plan, workflow-run, smart-plan, app-profile, task-preset, task-plan, task-run, form-plan, form-run, smart-click, watch, ocr-screen, ocr-image, ocr-find-text, ocr-click, ocr-uia-fuse, screenshot-diff, click-and-verify-screen, ocr-uia-invoke, history, coord-profile, coord-map, coord-anchor, hit-test, hit-test-batch, hit-scan, point-plan, target-validate, safe-type, cdp-detect, cdp-eval, cdp-type, cdp-click, cdp-smart-find, cdp-smart-type-find, cdp-smart-click, cdp-smart-type, cdp-deep-find, cdp-prosemirror-insert, ime-paste, safe-type-ime, modal-detect, recovery-plan, recovery-run, precision-validate, benchmark, release-notes"
      throw "Unknown macro: $sub"
    }
  }
}

function _Read-OptValue { param([string[]]$Rest, [string]$Name)
  for ($i = 0; $i -lt $Rest.Count; $i++) {
    if ($Rest[$i] -eq $Name -and ($i + 1) -lt $Rest.Count) { return $Rest[$i+1] }
  }
  return $null
}

function _Read-AllOptValues { param([string[]]$Rest, [string]$Name)
  $values = New-Object System.Collections.ArrayList
  for ($i = 0; $i -lt $Rest.Count; $i++) {
    if ($Rest[$i] -eq $Name -and ($i + 1) -lt $Rest.Count) {
      [void]$values.Add($Rest[$i+1])
      $i++
    }
  }
  return @($values)
}

function _Read-Switch { param([string[]]$Rest, [string]$Name)
  # cucp.execution-sensitive-ceiling/v1: trusted child context never comes from argv.
  if ($Name -eq '--confirm-sensitive') {
    $ceiling = Get-Variable -Name 'CUCP_EXECUTION_SENSITIVE_CEILING' -Scope Global -ErrorAction SilentlyContinue
    if ($null -ne $ceiling -and ($ceiling.Value -isnot [bool] -or -not $ceiling.Value -or
        -not ($ceiling.Options -band [System.Management.Automation.ScopedItemOptions]::Constant))) {
      return $false
    }
  }
  return ($Rest -contains $Name)
}

# ----------------------------------------------------------------------------
# _Macro-NotImplemented (v2.1.1)
# ----------------------------------------------------------------------------
# 일부 매크로 (process / registry / notify / multi-select / multi-edit /
# scrape / dom-snapshot) 는 dispatcher 에는 광고돼 있으나 본체 구현이 없다
# (외부 업데이트본 병합 과정의 미완성 surface). 과거에는 호출 시 "함수를 인식할
# 수 없습니다" 같은 raw 런타임 에러가 났는데, 이는 (1) 사용자에게 불친절하고
# (2) 마치 내부 버그처럼 보이며 (3) 광고된 surface 와 실제 동작이 어긋나는
# 정합성 문제였다. 이 헬퍼로 깔끔한 미구현 안내 + 표준 envelope (exit 1) 를
# 반환해 "광고했지만 아직 없음" 을 정직하게 노출한다.
function _Macro-NotImplemented {
  param([string]$Macro, [string]$Hint = "")
  $payload = [pscustomobject]@{
    schema = "cucp.not-implemented/v1"
    status = "not_implemented"
    macro = $Macro
    summary = "매크로 '$Macro' 는 이 버전에서 아직 구현되지 않았습니다 (surface 에는 등록됨)."
    hint = $Hint
    next_action = "다른 매크로로 대체하거나, 이 기능이 필요하면 별도 구현 요청. 'cucp macro' 로 사용 가능 목록 확인."
  }
  if ($Brief) {
    [Console]::Out.WriteLine("not_implemented $Macro")
  } else {
    [Console]::Out.WriteLine(($payload | ConvertTo-Json -Depth 6))
  }
  return 1
}

function _Read-StandaloneConfirmation {
  param([string[]]$Rest)
  # Arity-aware consent is evaluated from this invocation's original argv.
  # An immutable parent ceiling can restrict it, never grant it by itself.
  $ceiling = Get-Variable -Name 'CUCP_EXECUTION_SENSITIVE_CEILING' -Scope Global -ErrorAction SilentlyContinue
  if ($null -ne $ceiling -and ($ceiling.Value -isnot [bool] -or -not $ceiling.Value -or
      -not ($ceiling.Options -band [System.Management.Automation.ScopedItemOptions]::Constant))) { return $false }
  $result = _Invoke-LegacyCompatibility -Operation 'execution-confirmation' -Arguments @{original_argv=@($Rest)}
  if ($null -eq $result -or $result.confirmed -isnot [bool]) { throw 'Invalid startup confirmation result.' }
  return [bool]$result.confirmed
}

function _Invoke-LegacyCompatibility {
  param([ValidateSet('execution-confirmation','safety-classify','coord-map','workflow-plan-from-parsed','task-preset-prepare','task-preset-complete','task-plan-prepare','task-plan-assemble','task-plan-complete','form-plan-prepare','form-plan-complete','smart-plan-advance','app-profile-advance')][string]$Operation, [hashtable]$Arguments, [switch]$PreserveInvalidArguments)
  # Compatibility only: pure logic now lives in bounded C# kernels. No shell or desktop calls.
  $native = $env:CUCP_NATIVE_HOST
  if (-not $native) { $native = Join-Path $PSScriptRoot '..\pcucp-next\bin\native\PcuCp.NativeHost.exe' }
  $native = [System.IO.Path]::GetFullPath($native)
  if (-not (Test-Path -LiteralPath $native -PathType Leaf)) {
    throw 'Matching native runtime missing. Publish pcucp-next/packaging/publish_native.py or set CUCP_NATIVE_HOST to the matching executable/DLL.'
  }
  $psi = New-Object System.Diagnostics.ProcessStartInfo
  $entry = if ($Operation -eq 'execution-confirmation') { 'legacy-execution-confirmation' } else { 'legacy-compat' }
  $extension = [System.IO.Path]::GetExtension($native).ToLowerInvariant()
  if ($extension -eq '.dll') {
    $dotnet = Get-Command dotnet.exe -CommandType Application -ErrorAction Stop
    if ($native.Contains('"') -or $native.Contains("`r") -or $native.Contains("`n")) { throw 'Invalid native DLL path' }
    $psi.FileName = $dotnet.Source
    $psi.Arguments = '"' + $native + '" ' + $entry
  } elseif ($extension -eq '.exe') {
    $psi.FileName = $native
    $psi.Arguments = $entry
  } else { throw 'CUCP_NATIVE_HOST must be an executable or DLL, never a shell script.' }
  $payload = @{schema='cucp.legacy-compat/v1'; operation=$Operation; args=$Arguments; culture=[Globalization.CultureInfo]::CurrentCulture.Name} | ConvertTo-Json -Depth 24 -Compress
  $utf8 = New-Object System.Text.UTF8Encoding($false, $true)
  $bytes = $utf8.GetBytes($payload)
  $requestLimit = if ($Operation -eq 'execution-confirmation') { 33554432 } else { 1048576 }
  if ($bytes.Length -gt $requestLimit) {
    if ($Operation -eq 'execution-confirmation') { throw 'Execution confirmation request exceeds 32 MiB.' }
    throw 'Legacy compatibility request exceeds 1 MiB.'
  }
  $psi.UseShellExecute = $false
  $psi.CreateNoWindow = $true
  $psi.RedirectStandardInput = $true
  $psi.RedirectStandardOutput = $true
  $psi.RedirectStandardError = $true
  $psi.StandardOutputEncoding = $utf8
  $psi.StandardErrorEncoding = $utf8
  $process = New-Object System.Diagnostics.Process
  $process.StartInfo = $psi
  try {
    [void]$process.Start()
    $stdout = $process.StandardOutput.ReadToEndAsync()
    $stderr = $process.StandardError.ReadToEndAsync()
    $process.StandardInput.BaseStream.Write($bytes, 0, $bytes.Length)
    $process.StandardInput.Close()
    if (-not $process.WaitForExit(15000)) {
      try { $process.Kill() } catch { }
      throw 'Legacy compatibility operation timed out; no retry was attempted.'
    }
    $out = $stdout.GetAwaiter().GetResult()
    $err = $stderr.GetAwaiter().GetResult()
    if ($out.Length -gt 16777216 -or $err.Length -gt 65536) { throw 'Legacy compatibility response exceeds the protocol budget.' }
    $response = $out | ConvertFrom-Json -ErrorAction Stop
    if ($process.ExitCode -ne 0 -or $response.status -ne 'ok' -or $null -eq $response.data) {
      $nativeErrors = @($response.errors)
      if ($PreserveInvalidArguments -and $process.ExitCode -ne 0 -and $response.schema -eq 'pcucp.native/v1' -and $response.kind -eq 'legacy-compat' -and $response.status -eq 'error' -and $nativeErrors.Count -eq 1 -and $nativeErrors[0].code -eq 'invalid_arguments' -and $nativeErrors[0].message -is [string]) {
        throw $nativeErrors[0].message
      }
      throw ('Legacy compatibility operation failed; rebuild matching native runtime. ' + ($response.errors | ConvertTo-Json -Compress))
    }
    return $response.data
  } finally { $process.Dispose() }
}

function _Classify-SafetyFromText {
  param([string]$Text, [string]$MacroName)
  $result = _Invoke-LegacyCompatibility -Operation 'safety-classify' -Arguments @{text=$Text; macro=$MacroName}
  if ($result.schema -ne 'cucp.safety-classify/v1' -or $result.status -ne 'ok' -or $result.requires_explicit_confirmation -isnot [bool] -or $result.blocked_by_default -isnot [bool]) {
    throw 'Invalid safety classification response; live control remains blocked.'
  }
  return $result
}

function Invoke-MacroSafetyClassify {
  param([string[]]$Rest)
  $jsonOnly = _Read-Switch -Rest $Rest -Name "--json-only"
  $macro = _Read-OptValue -Rest $Rest -Name "--macro"
  $parts = New-Object System.Collections.ArrayList
  foreach ($v in @(_Read-AllOptValues -Rest $Rest -Name "--text")) { if ($null -ne $v) { [void]$parts.Add("$v") } }
  foreach ($v in @(_Read-AllOptValues -Rest $Rest -Name "--step")) { if ($null -ne $v) { [void]$parts.Add("$v") } }
  foreach ($v in @(_Read-AllOptValues -Rest $Rest -Name "--command")) { if ($null -ne $v) { [void]$parts.Add("$v") } }
  if ($parts.Count -eq 0) {
    $skipValue = @{"--text"=$true; "--step"=$true; "--command"=$true; "--macro"=$true}
    $skip = @{"--json-only"=$true}
    $skipNext = $false
    foreach ($a in @($Rest)) {
      if ($skipNext) { $skipNext = $false; continue }
      if ($skip.ContainsKey($a)) { continue }
      if ($skipValue.ContainsKey($a)) { $skipNext = $true; continue }
      [void]$parts.Add("$a")
    }
  }
  $text = (@($parts) -join " ")
  if (-not $macro) {
    $parsed = _Parse-WorkflowStepTokens -Step $text
    if ($parsed.ok -and $parsed.tokens.Count -ge 2 -and $parsed.tokens[0] -eq "macro") { $macro = "$($parsed.tokens[1])" }
  }
  $payload = _Classify-SafetyFromText -Text $text -MacroName $macro
  if ($Brief -and -not $jsonOnly) {
    [Console]::Out.WriteLine("ok safety-classify risk=$($payload.risk_level) score=$($payload.risk_score) confirm=$($payload.requires_explicit_confirmation)")
  } else {
    [Console]::Out.WriteLine(($payload | ConvertTo-Json -Depth 10))
  }
  return 0
}

function _Ensure-NativeDesktopTypes {
  if ("CUCP.NativeDesktop" -as [type]) { return }
  Add-Type -AssemblyName System.Windows.Forms
  Add-Type @"
using System;
using System.Runtime.InteropServices;

namespace CUCP {
  public static class NativeDesktop {
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
    [DllImport("user32.dll")] public static extern bool ShowWindowAsync(IntPtr hWnd, int nCmdShow);
    [DllImport("user32.dll")] public static extern bool IsIconic(IntPtr hWnd);
    [DllImport("user32.dll")] public static extern bool BringWindowToTop(IntPtr hWnd);
    [DllImport("user32.dll")] public static extern bool SetCursorPos(int X, int Y);
    [DllImport("user32.dll")] public static extern void mouse_event(uint dwFlags, uint dx, uint dy, uint dwData, UIntPtr dwExtraInfo);
  }
}
"@
}

function _Native-FindWindow {
  param([string]$Name)
  if (-not $Name) { return $null }
  $candidates = @(_Enumerate-Win32Windows -Match $Name | Where-Object { $_.visible })
  if ($candidates.Count -eq 0) { return $null }
  $needle = $Name.ToLowerInvariant()
  $ranked = $candidates | Sort-Object `
    @{ Expression = { if ($_.title -and $_.title.ToLowerInvariant() -eq $needle) { 0 } elseif ($_.process -and $_.process.ToLowerInvariant() -eq $needle) { 1 } else { 2 } } }, `
    @{ Expression = { if ($_.minimized) { 1 } else { 0 } } }
  return ($ranked | Select-Object -First 1)
}

function _Native-FocusWindow {
  param([string]$Name)
  _Ensure-NativeDesktopTypes
  $win = _Native-FindWindow -Name $Name
  if (-not $win) { return $null }
  $hwnd = [IntPtr]([int64]$win.hwnd)
  if ([CUCP.NativeDesktop]::IsIconic($hwnd)) {
    [CUCP.NativeDesktop]::ShowWindowAsync($hwnd, 9) | Out-Null
    Start-Sleep -Milliseconds 150
  } else {
    [CUCP.NativeDesktop]::ShowWindowAsync($hwnd, 5) | Out-Null
  }
  [CUCP.NativeDesktop]::BringWindowToTop($hwnd) | Out-Null
  [CUCP.NativeDesktop]::SetForegroundWindow($hwnd) | Out-Null
  Start-Sleep -Milliseconds 250
  return $win
}

function _Native-SendShortcut {
  param([string]$Keys)
  if (-not $Keys) { throw "shortcut keys required" }
  _Ensure-NativeDesktopTypes
  $parts = @($Keys.ToLowerInvariant().Split("+") | Where-Object { $_ -ne "" })
  if ($parts.Count -eq 0) { throw "shortcut keys required" }
  $mods = ""
  $key = $parts[-1]
  if ($parts -contains "ctrl" -or $parts -contains "control") { $mods += "^" }
  if ($parts -contains "shift") { $mods += "+" }
  if ($parts -contains "alt") { $mods += "%" }
  $named = @{
    "enter"="{ENTER}"; "return"="{ENTER}"; "tab"="{TAB}"; "esc"="{ESC}"; "escape"="{ESC}";
    "space"=" "; "backspace"="{BACKSPACE}"; "delete"="{DELETE}"; "del"="{DELETE}";
    "up"="{UP}"; "down"="{DOWN}"; "left"="{LEFT}"; "right"="{RIGHT}";
    "home"="{HOME}"; "end"="{END}"; "pgup"="{PGUP}"; "pageup"="{PGUP}";
    "pgdn"="{PGDN}"; "pagedown"="{PGDN}"
  }
  if ($key -match '^f([1-9]|1[0-2])$') { $sendKey = "{" + $key.ToUpperInvariant() + "}" }
  elseif ($named.ContainsKey($key)) { $sendKey = $named[$key] }
  elseif ($key.Length -eq 1) { $sendKey = $key }
  else { $sendKey = "{" + $key.ToUpperInvariant() + "}" }
  [System.Windows.Forms.SendKeys]::SendWait($mods + $sendKey)
}

function _Native-SetClipboard {
  param([string]$Text)
  _Ensure-NativeDesktopTypes
  [System.Windows.Forms.Clipboard]::SetText($Text)
}

function _Native-ClickPoint {
  param([int]$X, [int]$Y, [string]$Button = "left", [int]$Clicks = 1)
  _Ensure-NativeDesktopTypes
  [CUCP.NativeDesktop]::SetCursorPos($X, $Y) | Out-Null
  Start-Sleep -Milliseconds 80
  $down = 0x0002; $up = 0x0004
  if ($Button -eq "right") { $down = 0x0008; $up = 0x0010 }
  elseif ($Button -eq "middle") { $down = 0x0020; $up = 0x0040 }
  for ($i = 0; $i -lt [Math]::Max(1, $Clicks); $i++) {
    [CUCP.NativeDesktop]::mouse_event($down,0,0,0,[UIntPtr]::Zero)
    Start-Sleep -Milliseconds 60
    [CUCP.NativeDesktop]::mouse_event($up,0,0,0,[UIntPtr]::Zero)
    Start-Sleep -Milliseconds 80
  }
}

function _Native-HitTestPoint {
  param(
    [int]$X,
    [int]$Y,
    [int]$TargetHwnd,
    [string]$TargetMatch
  )
  if (-not (_Ensure-Win32Loaded)) { throw "Win32 load failed" }
  $win = [CucpWin32]::WindowFromScreenPoint($X, $Y)
  if (-not $win) {
    return [pscustomobject]@{
      status = "partial"
      reason = "no_window_at_coords"
      x = $X
      y = $Y
      child_hwnd = 0
      root_hwnd = 0
      root_title = ""
      child_title = ""
      root_class = ""
      process_id = 0
      process_name = ""
      target_hwnd = $TargetHwnd
      target_match = $TargetMatch
      matched = $false
      match_reason = "no_window_at_coords"
      uia_skipped = $true
      source = "wrapper_win32_fast"
    }
  }

  $matched = $true
  $matchReason = "no_target_specified"
  if ($TargetHwnd -gt 0) {
    $matched = ([int64]$win.Hwnd -eq [int64]$TargetHwnd)
    $matchReason = if ($matched) { "hwnd_match" } else { "hwnd_mismatch" }
  } elseif ($TargetMatch) {
    $needle = $TargetMatch.ToLowerInvariant()
    $title = if ($win.Title) { "$($win.Title)".ToLowerInvariant() } else { "" }
    $proc = if ($win.ProcessName) { "$($win.ProcessName)".ToLowerInvariant() } else { "" }
    $matched = ($title.Contains($needle) -or $proc.Contains($needle))
    $matchReason = if ($matched) { "title_or_process_match" } else { "title_mismatch" }
  }
  $status = "ok"
  if ((($TargetHwnd -gt 0) -or $TargetMatch) -and -not $matched) { $status = "partial" }

  return [pscustomobject]@{
    status = $status
    x = $X
    y = $Y
    child_hwnd = [int64]$win.ChildHwnd
    root_hwnd = [int64]$win.Hwnd
    root_title = "$($win.Title)"
    child_title = ""
    root_class = "$($win.ClassName)"
    process_id = [int]$win.Pid
    process_name = "$($win.ProcessName)"
    target_hwnd = $TargetHwnd
    target_match = $TargetMatch
    matched = [bool]$matched
    match_reason = $matchReason
    uia_skipped = $true
    source = "wrapper_win32_fast"
  }
}

function _CoordProfile-MonitorObject {
  param($Monitor)
  if (-not $Monitor) { return $null }
  return [pscustomobject]@{
    device = "$($Monitor.DeviceName)"
    primary = [bool]$Monitor.Primary
    rect = [pscustomobject]@{
      x = [int]$Monitor.X
      y = [int]$Monitor.Y
      width = [int]$Monitor.Width
      height = [int]$Monitor.Height
    }
    work_rect = [pscustomobject]@{
      x = [int]$Monitor.WorkX
      y = [int]$Monitor.WorkY
      width = [int]$Monitor.WorkWidth
      height = [int]$Monitor.WorkHeight
    }
    dpi = [pscustomobject]@{
      x = [int]$Monitor.DpiX
      y = [int]$Monitor.DpiY
      scale_x = [double]$Monitor.ScaleX
      scale_y = [double]$Monitor.ScaleY
    }
  }
}

function _CoordProfile-WindowFromPrecheck {
  param($Precheck)
  if (-not $Precheck -or -not $Precheck.root_hwnd -or [int64]$Precheck.root_hwnd -le 0) { return $null }
  $wins = @(_Enumerate-Win32Windows)
  foreach ($w in $wins) {
    if ([int64]$w.hwnd -eq [int64]$Precheck.root_hwnd) { return $w }
  }
  return [pscustomobject]@{
    hwnd = [int64]$Precheck.root_hwnd
    title = "$($Precheck.root_title)"
    class = "$($Precheck.root_class)"
    pid = [int]$Precheck.process_id
    process = "$($Precheck.process_name)"
    visible = $true
    minimized = $false
    foreground = $false
    rect = $null
  }
}

function _Build-CoordProfile {
  param(
    [bool]$HasPoint,
    [int]$X,
    [int]$Y,
    [int64]$TargetHwnd,
    [string]$TargetMatch
  )
  $sw = [System.Diagnostics.Stopwatch]::StartNew()
  if (-not (_Ensure-Win32Loaded)) {
    $sw.Stop()
    return [pscustomobject]@{
      schema = "cucp.coord-profile/v1"
      status = "partial"
      reason = "win32_load_failed"
      elapsed_ms = [int]$sw.Elapsed.TotalMilliseconds
    }
  }

  $virtualRaw = [CucpWin32]::GetVirtualScreenInfo()
  $virtual = [pscustomobject]@{
    x = [int]$virtualRaw.X
    y = [int]$virtualRaw.Y
    width = [int]$virtualRaw.Width
    height = [int]$virtualRaw.Height
    right = [int]($virtualRaw.X + $virtualRaw.Width)
    bottom = [int]($virtualRaw.Y + $virtualRaw.Height)
    monitor_count = [int]$virtualRaw.MonitorCount
    same_display_format = [bool]$virtualRaw.SameDisplayFormat
  }
  $monitors = @([CucpWin32]::EnumerateMonitors() | ForEach-Object { _CoordProfile-MonitorObject -Monitor $_ })
  $point = if ($HasPoint) { [pscustomobject]@{ x = $X; y = $Y } } else { $null }
  $insideVirtual = $null
  $pointMonitor = $null
  $pointHit = $null
  if ($HasPoint) {
    $insideVirtual = ($X -ge $virtual.x -and $X -lt $virtual.right -and $Y -ge $virtual.y -and $Y -lt $virtual.bottom)
    try { $pointMonitor = _CoordProfile-MonitorObject -Monitor ([CucpWin32]::MonitorFromScreenPointInfo($X,$Y)) } catch { }
    try { $pointHit = _Native-HitTestPoint -X $X -Y $Y -TargetHwnd ([int]$TargetHwnd) -TargetMatch $TargetMatch } catch { }
  }

  $targetWindow = $null
  if ($TargetHwnd -gt 0) {
    foreach ($w in @(_Enumerate-Win32Windows)) {
      if ([int64]$w.hwnd -eq [int64]$TargetHwnd) { $targetWindow = $w; break }
    }
  }
  if (-not $targetWindow -and $TargetMatch) { $targetWindow = _Native-FindWindow -Name $TargetMatch }
  if (-not $targetWindow -and $pointHit) { $targetWindow = _CoordProfile-WindowFromPrecheck -Precheck $pointHit }

  $targetRect = $null
  $targetMonitor = $null
  $windowDpi = $null
  if ($targetWindow) {
    $targetRect = $targetWindow.rect
    try { $targetMonitor = _CoordProfile-MonitorObject -Monitor ([CucpWin32]::MonitorFromWindowInfo([IntPtr]([int64]$targetWindow.hwnd))) } catch { }
    try {
      $dpiValue = [CucpWin32]::GetWindowDpiValue([IntPtr]([int64]$targetWindow.hwnd))
      if ([int]$dpiValue -gt 0) {
        $windowDpi = [pscustomobject]@{
          dpi = [int]$dpiValue
          scale = [Math]::Round(([double]$dpiValue / 96.0), 4)
        }
      }
    } catch { }
  }

  $pointInTarget = $null
  $pointWindowRelative = $null
  $edgeDistance = $null
  if ($HasPoint -and $targetRect) {
    $right = [int]$targetRect.x + [int]$targetRect.width
    $bottom = [int]$targetRect.y + [int]$targetRect.height
    $pointInTarget = ($X -ge [int]$targetRect.x -and $X -lt $right -and $Y -ge [int]$targetRect.y -and $Y -lt $bottom)
    $relX = $X - [int]$targetRect.x
    $relY = $Y - [int]$targetRect.y
    $pointWindowRelative = [pscustomobject]@{
      x = [int]$relX
      y = [int]$relY
      norm_x = if ([int]$targetRect.width -gt 0) { [Math]::Round(([double]$relX / [double]$targetRect.width), 6) } else { $null }
      norm_y = if ([int]$targetRect.height -gt 0) { [Math]::Round(([double]$relY / [double]$targetRect.height), 6) } else { $null }
    }
    $edgeDistance = [pscustomobject]@{
      left = [int]($X - [int]$targetRect.x)
      top = [int]($Y - [int]$targetRect.y)
      right = [int]($right - $X - 1)
      bottom = [int]($bottom - $Y - 1)
      min = [int]([Math]::Min([Math]::Min($X - [int]$targetRect.x, $Y - [int]$targetRect.y), [Math]::Min($right - $X - 1, $bottom - $Y - 1)))
    }
  }

  $warnings = New-Object System.Collections.ArrayList
  $risk = "low"
  if ($HasPoint -and -not $insideVirtual) {
    $risk = "high"
    [void]$warnings.Add("point_outside_virtual_screen")
  }
  if ($HasPoint -and $targetRect -and -not $pointInTarget) {
    $risk = "high"
    [void]$warnings.Add("point_outside_target_window")
  }
  if ($HasPoint -and $edgeDistance -and [int]$edgeDistance.min -ge 0 -and [int]$edgeDistance.min -lt 4 -and $risk -ne "high") {
    $risk = "medium"
    [void]$warnings.Add("point_near_target_window_edge")
  }
  if ($targetMonitor -and ($targetMonitor.dpi.scale_x -ne 1.0 -or $targetMonitor.dpi.scale_y -ne 1.0)) {
    if ($risk -eq "low") { $risk = "medium" }
    [void]$warnings.Add("non_100_percent_dpi_scale")
  }
  if ([int]$virtual.monitor_count -gt 1) {
    if ($risk -eq "low") { $risk = "medium" }
    [void]$warnings.Add("multi_monitor_coordinates")
  }
  if ($HasPoint -and $pointMonitor -and $targetMonitor -and $pointMonitor.device -and $targetMonitor.device -and $pointMonitor.device -ne $targetMonitor.device) {
    $risk = "high"
    [void]$warnings.Add("point_monitor_differs_from_target_window_monitor")
  }
  if ($pointHit -and (($TargetMatch) -or ($TargetHwnd -gt 0)) -and -not [bool]$pointHit.matched) {
    $risk = "high"
    [void]$warnings.Add("win32_hit_test_target_mismatch")
  }

  $signatureParts = New-Object System.Collections.ArrayList
  [void]$signatureParts.Add("vs=$($virtual.x),$($virtual.y),$($virtual.width),$($virtual.height)")
  foreach ($m in @($monitors)) {
    [void]$signatureParts.Add("m=$($m.device):$($m.rect.x),$($m.rect.y),$($m.rect.width),$($m.rect.height):$($m.dpi.x)x$($m.dpi.y)")
  }
  if ($targetWindow) { [void]$signatureParts.Add("target=$([int64]$targetWindow.hwnd)") }
  $signature = (($signatureParts | ForEach-Object { "$_" }) -join "|")

  $sw.Stop()
  return [pscustomobject]@{
    schema = "cucp.coord-profile/v1"
    status = "ok"
    point = $point
    has_point = [bool]$HasPoint
    coordinate_risk = $risk
    warnings = @($warnings)
    virtual_screen = $virtual
    monitors = @($monitors)
    point_inside_virtual_screen = $insideVirtual
    point_monitor = $pointMonitor
    target_window = if ($targetWindow) {
      [pscustomobject]@{
        hwnd = [int64]$targetWindow.hwnd
        title = "$($targetWindow.title)"
        process = "$($targetWindow.process)"
        class = "$($targetWindow.class)"
        foreground = [bool]$targetWindow.foreground
        rect = $targetRect
      }
    } else { $null }
    target_monitor = $targetMonitor
    target_window_dpi = $windowDpi
    point_inside_target_window = $pointInTarget
    point_window_relative = $pointWindowRelative
    edge_distance_to_target = $edgeDistance
    hit_test = $pointHit
    coord_signature = $signature
    elapsed_ms = [int]$sw.Elapsed.TotalMilliseconds
    next_step = if ($HasPoint) { "Use point-plan for micro-refined click planning; if coordinate_risk is high, re-ground with app-profile or smart-plan before live control." } else { "Use this profile to understand DPI/monitor layout before planning coordinate clicks." }
  }
}

function Invoke-MacroCoordProfile {
  param([string[]]$Rest)
  $xRaw = _Read-OptValue -Rest $Rest -Name "--x"
  $yRaw = _Read-OptValue -Rest $Rest -Name "--y"
  $hasPoint = ($null -ne $xRaw -and $null -ne $yRaw)
  $x = 0
  $y = 0
  if ($hasPoint) { $x = [int]$xRaw; $y = [int]$yRaw }
  $tm = _Read-OptValue -Rest $Rest -Name "--target-match"
  if (-not $tm) { $tm = _Read-OptValue -Rest $Rest -Name "--match" }
  if (-not $tm) { $tm = _Read-OptValue -Rest $Rest -Name "--window" }
  $th = [int64](_Read-OptValue -Rest $Rest -Name "--target-hwnd")
  $jsonOnly = _Read-Switch -Rest $Rest -Name "--json-only"
  $profile = _Build-CoordProfile -HasPoint $hasPoint -X $x -Y $y -TargetHwnd $th -TargetMatch $tm
  if ($Brief -and -not $jsonOnly) {
    [Console]::Out.WriteLine("$($profile.status) coord-profile risk=$($profile.coordinate_risk) monitors=$($profile.virtual_screen.monitor_count) warnings=$(@($profile.warnings).Count) elapsed_ms=$($profile.elapsed_ms)")
  } else {
    [Console]::Out.WriteLine(($profile | ConvertTo-Json -Depth 12))
  }
  if ($profile.status -eq "ok") { return 0 }
  return 2
}

function _CoordMap-ResolveWindow {
  param([int64]$TargetHwnd, [string]$TargetMatch)
  if ($TargetHwnd -gt 0) {
    foreach ($w in @(_Enumerate-Win32Windows)) {
      if ([int64]$w.hwnd -eq [int64]$TargetHwnd) { return $w }
    }
  }
  if ($TargetMatch) { return (_Native-FindWindow -Name $TargetMatch) }
  return $null
}

function _Build-CoordMap {
  param(
    [string]$From,
    [double]$X,
    [double]$Y,
    [double]$NormX,
    [double]$NormY,
    [bool]$HasNorm,
    [int64]$TargetHwnd,
    [string]$TargetMatch
  )
  $sw = [System.Diagnostics.Stopwatch]::StartNew()
  if (-not (_Ensure-Win32Loaded)) {
    $sw.Stop()
    return [pscustomobject]@{ schema="cucp.coord-map/v1"; status="partial"; reason="win32_load_failed"; elapsed_ms=[int]$sw.Elapsed.TotalMilliseconds }
  }
  if (-not $From) { $From = "screen" }
  $From = "$From".ToLowerInvariant()
  $virtualRaw = [CucpWin32]::GetVirtualScreenInfo()
  $virtual = [pscustomobject]@{
    x = [int]$virtualRaw.X
    y = [int]$virtualRaw.Y
    width = [int]$virtualRaw.Width
    height = [int]$virtualRaw.Height
    right = [int]($virtualRaw.X + $virtualRaw.Width)
    bottom = [int]($virtualRaw.Y + $virtualRaw.Height)
    monitor_count = [int]$virtualRaw.MonitorCount
  }

  $win = _CoordMap-ResolveWindow -TargetHwnd $TargetHwnd -TargetMatch $TargetMatch
  if (-not $win -and $From -eq "screen") {
    try {
      $hit = _Native-HitTestPoint -X ([int][Math]::Round($X)) -Y ([int][Math]::Round($Y)) -TargetHwnd 0 -TargetMatch $null
      if ($hit -and [int64]$hit.root_hwnd -gt 0) { $win = _CoordProfile-WindowFromPrecheck -Precheck $hit }
    } catch { }
  }
  $result = _Invoke-LegacyCompatibility -Operation 'coord-map' -Arguments @{
    from=$From; x=$X; y=$Y; norm_x=$NormX; norm_y=$NormY; has_norm=$HasNorm
    target_hwnd=$TargetHwnd; target_match=$TargetMatch; virtual_screen=$virtual; selected_window=$win
  }
  if ($result.schema -ne 'cucp.coord-map/v1' -or $result.status -notin @('ok','partial')) {
    throw 'Invalid coordinate mapping response; no action was attempted.'
  }
  # Discovery remains local to the compatibility adapter; pure pixel math is C#.
  if ($result.status -eq 'ok' -and $result.screen_point) {
    $profile = _Build-CoordProfile -HasPoint $true -X $result.screen_point.x -Y $result.screen_point.y -TargetHwnd ([int64]$win.hwnd) -TargetMatch $null
    $result.coordinate_profile = $profile
    if ($profile -and $profile.coordinate_risk -eq 'high') {
      $result.warnings += 'coordinate_profile_high_risk'
      foreach ($warning in @($profile.warnings)) { if ($warning) { $result.warnings += "$warning" } }
    }
  }
  $sw.Stop()
  $result.elapsed_ms = [int]$sw.Elapsed.TotalMilliseconds
  return $result
}

function Invoke-MacroCoordMap {
  param([string[]]$Rest)
  $from = _Read-OptValue -Rest $Rest -Name "--from"
  if (-not $from) { $from = _Read-OptValue -Rest $Rest -Name "--mode" }
  if (-not $from) { $from = "screen" }
  $xRaw = _Read-OptValue -Rest $Rest -Name "--x"
  $yRaw = _Read-OptValue -Rest $Rest -Name "--y"
  $normXRaw = _Read-OptValue -Rest $Rest -Name "--norm-x"
  $normYRaw = _Read-OptValue -Rest $Rest -Name "--norm-y"
  $hasNorm = ($null -ne $normXRaw -and $null -ne $normYRaw)
  if ((-not $hasNorm) -and ($null -eq $xRaw -or $null -eq $yRaw)) { throw "macro coord-map requires --x/--y or --norm-x/--norm-y" }
  $x = if ($null -ne $xRaw) { [double]$xRaw } else { 0.0 }
  $y = if ($null -ne $yRaw) { [double]$yRaw } else { 0.0 }
  $normX = if ($hasNorm) { [double]$normXRaw } else { 0.0 }
  $normY = if ($hasNorm) { [double]$normYRaw } else { 0.0 }
  $tm = _Read-OptValue -Rest $Rest -Name "--target-match"
  if (-not $tm) { $tm = _Read-OptValue -Rest $Rest -Name "--match" }
  if (-not $tm) { $tm = _Read-OptValue -Rest $Rest -Name "--window" }
  $th = [int64](_Read-OptValue -Rest $Rest -Name "--target-hwnd")
  $jsonOnly = _Read-Switch -Rest $Rest -Name "--json-only"
  $payload = _Build-CoordMap -From $from -X $x -Y $y -NormX $normX -NormY $normY -HasNorm $hasNorm -TargetHwnd $th -TargetMatch $tm
  if ($Brief -and -not $jsonOnly) {
    $sp = if ($payload.screen_point) { "$($payload.screen_point.x),$($payload.screen_point.y)" } else { "none" }
    [Console]::Out.WriteLine("$($payload.status) coord-map from=$from screen=$sp inside=$($payload.inside_window) warnings=$(@($payload.warnings).Count) elapsed_ms=$($payload.elapsed_ms)")
  } else {
    [Console]::Out.WriteLine(($payload | ConvertTo-Json -Depth 12))
  }
  if ($payload.status -eq "ok") { return 0 }
  return 2
}

function _Precision-EncodeWire($Value) {
  if($null -eq $Value){return @{kind='scalar';value=$null}}
  if($Value -is [string] -or $Value -is [ValueType]){return @{kind='scalar';value=$Value}}
  if($Value -is [System.Collections.IDictionary]){return @{kind='object';properties=@(foreach($key in $Value.Keys){@{name=[string]$key;value=(_Precision-EncodeWire $Value[$key])}})}}
  if($Value -is [System.Collections.IEnumerable]){return @{kind='array';items=@(foreach($item in $Value){_Precision-EncodeWire $item})}}
  return @{kind='object';properties=@(foreach($p in $Value.PSObject.Properties){@{name=$p.Name;value=(_Precision-EncodeWire $p.Value)}})}
}

function _Precision-Require($Condition,[string]$Message) {
  if (-not $Condition) { $failure=New-Object InvalidOperationException -ArgumentList $Message;$failure.Data['precision_protocol']=$true;throw $failure }
}

function _Precision-Fields($Value,[string[]]$Names) {
  _Precision-Require ($null -ne $Value -and $Value -isnot [array] -and $Value -isnot [string] -and $Value -isnot [ValueType]) 'Expected an precision protocol object.'
  $properties=@($Value.PSObject.Properties)
  _Precision-Require ($properties.Count -eq $Names.Count -and @($properties | Where-Object {$_.Name -cnotin $Names}).Count -eq 0) 'Unexpected precision protocol fields.'
}

function _Precision-DecodeWire($Wire) {
  _Precision-Require ($null -ne $Wire -and $Wire.kind -is [string]) 'Missing precision wire tag.'
  switch -CaseSensitive ($Wire.kind) {
    'scalar' {
      _Precision-Fields $Wire @('kind','value')
      _Precision-Require ($null -eq $Wire.value -or $Wire.value -is [string] -or $Wire.value -is [ValueType]) 'Invalid scalar wire value.'
      return ,$Wire.value
    }
    'array' {
      _Precision-Fields $Wire @('kind','items');_Precision-Require ($Wire.items -is [array]) 'Wire array items must be an array.'
      $items=New-Object Collections.ArrayList
      foreach($item in $Wire.items){[void]$items.Add((_Precision-DecodeWire $item))}
      return ,([object[]]$items.ToArray())
    }
    'object' {
      _Precision-Fields $Wire @('kind','properties');_Precision-Require ($Wire.properties -is [array]) 'Wire object properties must be an array.'
      $object=[ordered]@{}
      foreach($property in $Wire.properties){
        _Precision-Fields $property @('name','value');_Precision-Require ($property.name -is [string] -and -not $object.Contains($property.name)) 'Invalid or duplicate wire property.'
        $object[$property.name]=_Precision-DecodeWire $property.value
      }
      return ,([pscustomobject]$object)
    }
    default {throw 'Unknown precision wire kind.'}
  }
}

function _Precision-WriteChunks($Writer,[long]$Id,[string]$Target,$Value) {
  $utf8=New-Object Text.UTF8Encoding($false,$true)
  $bytes=$utf8.GetBytes((ConvertTo-Json -InputObject $Value -Depth 100 -Compress))
  for($offset=0;$offset -lt $bytes.Length;$offset+=49152){
    $count=[Math]::Min(49152,$bytes.Length-$offset)
    $frame=[ordered]@{kind='part';id=$Id;data=[Convert]::ToBase64String($bytes,$offset,$count)}
    if($Target){$frame['target']=$Target}
    $Writer.WriteLine((ConvertTo-Json -InputObject $frame -Compress))
  }
  $end=[ordered]@{kind='end';id=$Id};if($Target){$end['target']=$Target}
  $Writer.WriteLine((ConvertTo-Json -InputObject $end -Compress));$Writer.Flush()
}

function _Precision-StartProcess {
  param([switch]$Storage)
  $command=if($Storage){"legacy-precision-storage"}else{"legacy-precision-session"}
  $native=$env:CUCP_NATIVE_HOST
  if(-not $native){$native=Join-Path $PSScriptRoot '..\pcucp-next\bin\native\PcuCp.NativeHost.exe'}
  $native=[IO.Path]::GetFullPath($native)
  if(-not (Test-Path -LiteralPath $native -PathType Leaf)){throw 'Matching native precision runtime missing.'}
  $psi=New-Object Diagnostics.ProcessStartInfo
  switch([IO.Path]::GetExtension($native).ToLowerInvariant()){
    '.dll' {if($native.Contains('"') -or $native.Contains("`r") -or $native.Contains("`n")){throw 'Invalid native DLL path.'};$psi.FileName=(Get-Command dotnet.exe -CommandType Application -ErrorAction Stop).Source;$psi.Arguments='"'+$native+'" '+$command}
    '.exe' {$psi.FileName=$native;$psi.Arguments=$command}
    default {throw 'Native precision runtime must be an executable or DLL.'}
  }
  $utf8=New-Object Text.UTF8Encoding($false,$true)
  $psi.UseShellExecute=$false;$psi.CreateNoWindow=$true;$psi.RedirectStandardInput=$true;$psi.RedirectStandardOutput=$true;$psi.RedirectStandardError=$true
  $psi.StandardOutputEncoding=$utf8;$psi.StandardErrorEncoding=$utf8
  $process=New-Object Diagnostics.Process;$process.StartInfo=$psi
  [void]$process.Start()
  return $process
}

function _Precision-ReadMessage($Reader,[long]$ExpectedId){
  $buffer=New-Object IO.MemoryStream;$target=$null
  try{
    while($true){
      $line=$Reader.ReadLine();if($null -eq $line){throw 'Precision session closed; terminal outcome may be uncertain. No write is retried.'}
      if($line.Length -gt 70000){throw 'Precision output frame exceeds its bound.'}
      $frame=$line|ConvertFrom-Json -ErrorAction Stop
      if($frame.kind -ceq 'part'){_Precision-Fields $frame @('kind','target','id','data')}elseif($frame.kind -ceq 'end'){_Precision-Fields $frame @('kind','target','id')}else{throw ('Invalid precision output frame: '+$line.Substring(0,[Math]::Min(2048,$line.Length)))}
      _Precision-Require ($frame.id -is [int] -or $frame.id -is [long]) 'Invalid precision frame id.'
      _Precision-Require ([long]$frame.id -eq $ExpectedId -and $frame.target -is [string]) 'Precision message does not match outstanding sequence.'
      if($null -eq $target){$target=$frame.target}else{_Precision-Require ($target -ceq $frame.target) 'Interleaved precision messages.'}
      if($frame.kind -ceq 'end'){break}
      _Precision-Require ($frame.data -is [string]) 'Invalid precision frame data.'
      $bytes=[Convert]::FromBase64String($frame.data);_Precision-Require ($bytes.Length -le 49152) 'Oversized precision data chunk.'
      $buffer.Write($bytes,0,$bytes.Length)
    }
    $wire=(New-Object Text.UTF8Encoding($false,$true)).GetString($buffer.ToArray())|ConvertFrom-Json -ErrorAction Stop
    return [pscustomobject]@{target=$target;id=$ExpectedId;value=(_Precision-DecodeWire $wire)}
  }finally{$buffer.Dispose()}
}

function _Precision-Reply($Writer,[long]$Id,$Value,$ErrorMessage){
  $reply=if($null -ne $ErrorMessage){@{state='error';message=$ErrorMessage}}else{@{state='ok';value=$Value}}
  _Precision-WriteChunks $Writer $Id '' (_Precision-EncodeWire $reply)
}

function _Precision-AssertArgv($Actual,[string[]]$Expected){
  _Precision-Require ($Actual -is [array] -and $Actual.Count -eq $Expected.Count) 'Invalid precision argv shape.'
  for($i=0;$i -lt $Expected.Count;$i++){_Precision-Require ($Actual[$i] -is [string] -and $Actual[$i] -ceq $Expected[$i]) 'Precision argv changed.'}
}

function _Precision-ReadEffect($Effect,$State){
  _Precision-Fields $Effect @('kind','args');_Precision-Require ($Effect.kind -is [string]) 'Invalid precision read kind.'
  $p=$Effect.args;$rest=$State.rest
  if($Effect.kind -ceq 'json-string'){
    _Precision-Fields $p @('value')
    return [Management.Automation.LanguagePrimitives]::ConvertTo($p.value,[string],[Globalization.CultureInfo]::InvariantCulture)
  }
  $x=[int](_Read-OptValue -Rest $rest -Name '--x');$y=[int](_Read-OptValue -Rest $rest -Name '--y')
  $tm=_Read-OptValue -Rest $rest -Name '--target-match';if(-not $tm){$tm=_Read-OptValue -Rest $rest -Name '--match'};if(-not $tm){$tm=_Read-OptValue -Rest $rest -Name '--window'}
  $th=[int64](_Read-OptValue -Rest $rest -Name '--target-hwnd')
  if($Effect.kind -cin @('coord-map','hit-test','coord-profile')){
    $fields=@('x','y','target_hwnd','target_match');if($Effect.kind -eq 'coord-map'){$fields+=@('from','norm_x','norm_y','has_norm')};if($Effect.kind -eq 'coord-profile'){$fields+='has_point'}
    _Precision-Fields $p $fields
    _Precision-Require (($p.x -is [int] -or $p.x -is [long]) -and $p.x -ge [int]::MinValue -and $p.x -le [int]::MaxValue -and ($p.y -is [int] -or $p.y -is [long]) -and $p.y -ge [int]::MinValue -and $p.y -le [int]::MaxValue -and ($p.target_hwnd -is [int] -or $p.target_hwnd -is [long]) -and $p.target_match -is [string]) 'Invalid precision target types.'
    _Precision-Require ($p.x -eq $x -and $p.y -eq $y -and [int64]$p.target_hwnd -eq $th -and $p.target_match -ceq [string]$tm) 'Precision target changed.'
  }
  switch -CaseSensitive ($Effect.kind){
    'coord-map' {
      _Precision-Require ($State.operation -eq 'coord-anchor' -and $State.reads -eq 0 -and $p.from -ceq 'screen' -and $p.has_norm -is [bool] -and -not $p.has_norm -and $p.norm_x -eq 0 -and $p.norm_y -eq 0) 'Invalid coordinate-map read.'
      return _Build-CoordMap -From 'screen' -X $x -Y $y -NormX 0 -NormY 0 -HasNorm $false -TargetHwnd $th -TargetMatch $tm
    }
    'hit-test' {
      _Precision-Require ($State.operation -eq 'point-plan' -and $State.reads -eq 0) 'Invalid hit-test order.'
      $reply=_Native-HitTestPoint -X $x -Y $y -TargetHwnd $th -TargetMatch $tm;$State.precheck=$reply;return $reply
    }
    'coord-profile' {
      _Precision-Require ($State.operation -eq 'point-plan' -and $State.reads -eq 1 -and $p.has_point -is [bool] -and $p.has_point) 'Invalid coordinate-profile order.'
      $reply=_Build-CoordProfile -HasPoint $true -X $x -Y $y -TargetHwnd $th -TargetMatch $tm;$State.profile=$reply;return $reply
    }
    'history-lines' {
      _Precision-Fields $p @('path');_Precision-Require ($p.path -is [string] -and $p.path -ceq $State.history_file -and $State.operation -eq 'coord-anchor' -and $State.reads -eq 1 -and $rest -notcontains '--no-history') 'Invalid history read.'
      return ,([object[]]@(_Precision-HistoryLines -Path $State.history_file))
    }
    {$_ -cin @('hit-scan','point-plan-child','cache-read')} {
      $radiusRaw=_Read-OptValue -Rest $rest -Name '--radius';$stepRaw=_Read-OptValue -Rest $rest -Name '--step';$ttlRaw=_Read-OptValue -Rest $rest -Name '--cache-ttl'
      $radius=if($null -ne $radiusRaw -and "$radiusRaw" -ne ''){[int]$radiusRaw}else{6};$radius=[Math]::Min(64,[Math]::Max(0,$radius))
      $step=if($null -ne $stepRaw -and "$stepRaw" -ne ''){[int]$stepRaw}else{2};if($step -le 0){$step=2};$step=[Math]::Min(16,$step)
      $inset=[int](_Read-OptValue -Rest $rest -Name '--click-inset');if($inset -le 0){$inset=2}
      $ttl=if($null -ne $ttlRaw -and "$ttlRaw" -ne ''){[int]$ttlRaw}else{$State.cache_seconds};$ttl=[Math]::Max(0,$ttl);if($rest -contains '--no-cache'){$ttl=0}
      if($Effect.kind -ceq 'point-plan-child'){
        _Precision-Require ($State.operation -eq 'target-validate' -and $State.reads -eq 0) 'Invalid child planner order.'
        $argv=@('--x',"$x",'--y',"$y",'--radius',"$radius",'--step',"$step",'--click-inset',"$inset",'--cache-ttl',"$ttl")
        if($tm){$argv+=@('--target-match',$tm)};if($th -gt 0){$argv+=@('--target-hwnd',"$th")};if($rest -contains '--no-cache'){$argv+='--no-cache'}
        _Precision-Fields $p @('argv');_Precision-AssertArgv $p.argv $argv
        return _TargetValidate-InvokePointPlanJson -PointPlanArgs $argv
      }
      _Precision-Require ($State.operation -eq 'point-plan' -and $State.reads -in @(2,3) -and ((-not $tm -and $th -le 0) -or [bool]$State.precheck.matched)) 'Target guard forbids this read.'
      if($Effect.kind -ceq 'cache-read'){
        _Precision-Fields $p @('directory','key','max_age_seconds')
        _Precision-Require ($State.reads -eq 2 -and $p.directory -is [string] -and $p.directory -ceq $State.cache_dir -and $p.key -is [string] -and ($p.max_age_seconds -is [int] -or $p.max_age_seconds -is [long]) -and $p.max_age_seconds -ge [int]::MinValue -and $p.max_age_seconds -le [int]::MaxValue -and $p.max_age_seconds -eq $ttl) 'Invalid cache read.'
        $key=_PointPlan-CacheKey -X $x -Y $y -Radius $radius -Step $step -ClickInset $inset -TargetHwnd $th -TargetMatch $tm -Precheck $State.precheck -CoordSignature ([string]$State.profile.coord_signature)
        _Precision-Require ($p.key -ceq $key) 'Cache key changed.'
        $reply=_PointPlan-ReadCache -Key $key -MaxAgeSeconds $ttl
        $State.cache_key=$key;$State.cache_hit=[bool]($reply -and $reply.Json)
        return ,$reply
      }
      $argv=@('-Action','hit-scan','-X',"$x",'-Y',"$y",'-ClickInset',"$inset",'-ScanRadius',"$radius",'-ScanStep',"$step")
      if($tm){$argv+=@('-TargetMatch',$tm)};if($th -gt 0){$argv+=@('-TargetHwnd',"$th")}
      _Precision-Fields $p @('argv');_Precision-AssertArgv $p.argv $argv
      return Invoke-NativeHelper -ArgList $argv
    }
    default {_Precision-Require $false 'Unsupported precision read effect.'}
  }
}

function _Invoke-LegacyPrecisionSession {
  param([string]$Operation,[hashtable]$Arguments,[switch]$Storage)
  $planner=$Operation -in @('coord-anchor','point-plan','target-validate') -and -not $Storage
  $state=@{operation=$Operation;rest=@($Arguments.rest);cache_seconds=[int]$Arguments.cache_seconds;history_file=[string]$Arguments.history_file;history_max=[int]$Arguments.history_max;cache_dir=[string]$Arguments.cache_dir;reads=0;precheck=$null;profile=$null;planner=$planner;cache_hit=$false;cache_key=$null}
  $startupArgs=$Arguments
  $schema=if($Storage){'cucp.precision-storage/v1'}else{'cucp.precision-session/v1'}
  $startup=@{schema=$schema;operation=$Operation;args=(_Precision-EncodeWire $startupArgs);culture=[Globalization.CultureInfo]::CurrentCulture.Name}
  $startupJson=ConvertTo-Json -InputObject $startup -Depth 100 -Compress
  _Precision-Require ($startupJson.Length -le 4194304) 'Precision startup exceeds its bound.'
  $process=_Precision-StartProcess -Storage:$Storage;$writer=$null
  try{
    $stderr=$process.StandardError.ReadToEndAsync()
    $writer=New-Object IO.StreamWriter -ArgumentList @($process.StandardInput.BaseStream,(New-Object Text.UTF8Encoding($false,$true)));$writer.AutoFlush=$true
    $writer.WriteLine($startupJson);$id=1;$prepared=$null;$rendered=$null;$successJson=$null;$failureJson=$null;$serialized=$null
    while($true){
      $message=_Precision-ReadMessage $process.StandardOutput $id;$id++
      if($message.target -ceq 'error'){throw [string]$message.value.error}
      if($message.target -ceq 'read'){
        $reply=$null;$errorText=$null
        try{$reply=_Precision-ReadEffect $message.value $state}catch{if($_.Exception.Data.Contains("precision_protocol")){throw};$errorText=$_.Exception.Message}
        if($message.value.kind -cne 'json-string'){$state.reads++}
        _Precision-Reply $writer $message.id $reply $errorText;continue
      }
      if($message.target -cin @('complete','prepare')){
        $prepared=$message.value
        _Precision-Fields $prepared @('state','payload','exit','brief','json_depth','queries','effects')
        # Legacy cache hits keep the stored object's schema, including no schema.
        # Accept that only after the matching observed read and with no writes.
        $cacheCompletion=$Operation -ceq 'point-plan' -and $message.target -ceq 'complete' -and $state.reads -eq 3 -and $state.cache_hit -and $prepared.payload.from_cache -is [bool] -and $prepared.payload.from_cache -and $prepared.payload.cache_key -ceq $state.cache_key -and $prepared.effects -is [array] -and $prepared.effects.Count -eq 0
        _Precision-Require ($prepared.state -ceq 'complete' -and (-not $planner -or $prepared.payload.schema -ceq "cucp.$Operation/v1" -or $cacheCompletion) -and $prepared.exit -in @(0,1,2) -and $prepared.json_depth -in @(2,4,8,12,14,18,32,64,100) -and $prepared.effects -is [array] -and $prepared.effects.Count -le 1) 'Invalid precision completion.'
        $rendered=if(-not $planner){$null}elseif($null -ne $prepared.brief){[string]$prepared.brief}else{$prepared.payload|ConvertTo-Json -Depth ([int]$prepared.json_depth)}
        if($message.target -ceq 'complete'){_Precision-Require ($prepared.effects.Count -eq 0) 'Uncommitted precision effect.';break}
        _Precision-Require ($planner -and $prepared.effects.Count -eq 1) 'Missing precision terminal effect.'
        $Rest=$Arguments.rest
        $effect=$prepared.effects[0]
        if($effect.kind -ceq 'history-append'){
          _Precision-Require ($Operation -eq 'coord-anchor' -and ($Rest -contains '--record-history' -or $Rest -contains '--learn-history') -and $Rest -notcontains '--no-history' -and $effect.args.path -ceq $state.history_file -and $effect.args.max -eq $state.history_max -and $effect.bind -ceq 'reuse_history.recorded') 'Invalid terminal history effect.'
          $serialized=$effect.args.record|ConvertTo-Json -Compress -Depth 10
          $prepared.payload.reuse_history.recorded=$true;$successJson=$prepared.payload|ConvertTo-Json -Depth ([int]$prepared.json_depth)
          $prepared.payload.reuse_history.recorded=$false;$failureJson=$prepared.payload|ConvertTo-Json -Depth ([int]$prepared.json_depth)
        }elseif($effect.kind -ceq 'cache-write'){
          _Precision-Require ($Operation -eq 'point-plan' -and $effect.args.directory -ceq $state.cache_dir -and $effect.args.key -ceq $prepared.payload.cache_key -and $effect.bind -ceq 'payload' -and $prepared.payload.cache_ttl_seconds -gt 0) 'Invalid terminal cache effect.'
          $serialized=$prepared.payload|ConvertTo-Json -Depth 14
        }else{throw 'Unknown precision terminal effect.'}
        _Precision-Reply $writer $message.id @{serialized=$serialized} $null;continue
      }
      if($message.target -ceq 'commit-ready'){
        _Precision-Require ($null -ne $prepared -and $null -ne $serialized) 'Unexpected precision commit request.'
        _Precision-Fields $message.value @('receipt')
        $hash=[Security.Cryptography.SHA256]::Create();try{$expected=([BitConverter]::ToString($hash.ComputeHash([Text.Encoding]::UTF8.GetBytes($serialized)))).Replace('-','').ToLowerInvariant()}finally{$hash.Dispose()}
        _Precision-Require ($message.value.receipt -is [string] -and $message.value.receipt -ceq $expected) 'Precision commit receipt differs from rendered bytes.'
        _Precision-Reply $writer $message.id @{receipt=$expected} $null;continue
      }
      if($message.target -ceq 'committed'){
        _Precision-Require ($null -ne $prepared) 'Unexpected precision commit outcome.';_Precision-Fields $message.value @('recorded')
        if($prepared.effects[0].kind -ceq 'history-append'){
          _Precision-Require ($message.value.recorded -is [bool]) 'Missing history append outcome.'
          $prepared.payload.reuse_history.recorded=$message.value.recorded
          if($null -eq $prepared.brief){$rendered=if($message.value.recorded){$successJson}else{$failureJson}}
        }else{_Precision-Require ($null -eq $message.value.recorded) 'Unexpected cache append outcome.'}
        break
      }
      throw 'Unknown precision session message.'
    }
    $writer.Close();$process.WaitForExit()
    _Precision-Require ($process.ExitCode -eq [int]$prepared.exit) 'Precision session failed; no terminal write is retried.'
    return [pscustomobject]@{state=$prepared;console=$rendered}
  }finally{if($writer){$writer.Dispose()};try{if(-not $process.HasExited){$process.Kill()}}catch{};$process.Dispose()}
}

function _Invoke-LegacyPrecision {
  param([ValidateSet('coord-anchor','point-plan','target-validate')][string]$Operation,[string[]]$Rest)
  $arguments=@{rest=@($Rest);cache_seconds=[int]$CacheSeconds;brief=[bool]$Brief;elapsed_ms=0;now=(Get-Date).ToString('o');history_file=[string]$Script:AnchorHistoryFile;history_max=[int]$Script:AnchorHistoryMax;cache_dir=[string]$Script:CacheDir}
  $completed=_Invoke-LegacyPrecisionSession -Operation $Operation -Arguments $arguments
  [Console]::Out.WriteLine($completed.console)
  return [int]$completed.state.exit
}

function _Invoke-LegacyPrecisionValue {
  param([string]$Operation,[hashtable]$Arguments,[switch]$Storage)
  $completed=_Invoke-LegacyPrecisionSession -Operation $Operation -Arguments $Arguments -Storage:$Storage
  return ,$completed.state.payload
}

function _Precision-HistoryLines {param([string]$Path) $result=_Invoke-LegacyPrecisionValue -Storage -Operation 'history-lines' -Arguments @{history_file=$Path};return @($result)}

function _AnchorHistory-Read {param([int]$Last=500) $result=_Invoke-LegacyPrecisionValue -Storage -Operation 'history-file-read' -Arguments @{history_file=[string]$Script:AnchorHistoryFile;last=$Last};return @($result)}

function _AnchorHistory-NormDistance {param($A,$B) _Invoke-LegacyPrecisionValue -Operation 'history-distance' -Arguments @{a=$A;b=$B}}

function _AnchorHistory-Append {
  param($Record)
  if(-not $Record){return $false}
  try{$line=$Record|ConvertTo-Json -Compress -Depth 10;return [bool](_Invoke-LegacyPrecisionValue -Storage -Operation 'history-append' -Arguments @{history_file=[string]$Script:AnchorHistoryFile;maximum=[int]$Script:AnchorHistoryMax;serialized=$line})}catch{return $false}
}

function _AnchorHistory-Score {param($Record,[double]$Tolerance=0.012) _Invoke-LegacyPrecisionValue -Storage -Operation 'history-file-score' -Arguments @{history_file=[string]$Script:AnchorHistoryFile;record=$Record;tolerance=$Tolerance}}

function Invoke-MacroCoordAnchor {param([string[]]$Rest) _Invoke-LegacyPrecision -Operation 'coord-anchor' -Rest $Rest}

function _Native-Screenshot {
  param([string]$OutPath, [string]$Window)
  if (-not $OutPath) { throw "screenshot requires --out" }
  Add-Type -AssemblyName System.Windows.Forms
  Add-Type -AssemblyName System.Drawing
  $rect = $null
  if ($Window) {
    $win = _Native-FindWindow -Name $Window
    if (-not $win) { throw "window not found for screenshot: $Window" }
    $rect = $win.rect
  } else {
    $rect = [pscustomobject]@{ x = 0; y = 0; width = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds.Width; height = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds.Height }
  }
  $x = [int]$rect.x; $y = [int]$rect.y; $w = [int]$rect.width; $h = [int]$rect.height
  if ($x -lt 0) { $w += $x; $x = 0 }
  if ($y -lt 0) { $h += $y; $y = 0 }
  if ($w -le 0 -or $h -le 0) { throw "invalid screenshot rect" }
  $dir = Split-Path -Parent $OutPath
  if ($dir -and -not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
  $bmp = New-Object System.Drawing.Bitmap($w, $h)
  $gfx = [System.Drawing.Graphics]::FromImage($bmp)
  try {
    $gfx.CopyFromScreen($x, $y, 0, 0, (New-Object System.Drawing.Size($w, $h)))
    $bmp.Save($OutPath, [System.Drawing.Imaging.ImageFormat]::Png)
  } finally {
    $gfx.Dispose()
    $bmp.Dispose()
  }
  return [pscustomobject]@{ path = $OutPath; x = $x; y = $y; width = $w; height = $h; window = $Window }
}

function Invoke-MacroScreenshot {
  param([string[]]$Rest)
  $out = _Read-OptValue -Rest $Rest -Name "--out"
  $window = _Read-OptValue -Rest $Rest -Name "--window"
  if (-not $out) { throw "macro screenshot requires --out" }
  $shot = _Native-Screenshot -OutPath $out -Window $window
  _Trajectory-Append -Kind "screenshot" -Payload @{ path = $shot.path; window = $window; source = "native"; width = $shot.width; height = $shot.height }
  if ($Brief) { [Console]::Out.WriteLine(("ok screenshot '{0}' {1}x{2} source=native" -f $shot.path, $shot.width, $shot.height)) }
  else { [Console]::Out.WriteLine(($shot | ConvertTo-Json -Depth 4)) }
  return 0
}

function Invoke-MacroListAffordances {
  # macro list-affordances -- read-only enumeration of clickable/labeled elements.
  # Backwards compatible top-level fields kept: status, observation_id,
  # focused_window, from_cache, affordance_count, affordances.
  # NEW: also returns a cucp.observation/v1 envelope under `_envelope`
  # when --json-only is used so newer agents can rely on the unified shape.
  param([string[]]$Rest)
  $match = _Read-OptValue -Rest $Rest -Name "--match"
  $window = _Read-OptValue -Rest $Rest -Name "--window"
  $limit = [int](_Read-OptValue -Rest $Rest -Name "--limit")
  $jsonOnly = _Read-Switch -Rest $Rest -Name "--json-only"
  if ($limit -le 0) { $limit = 50 }
  if (-not $match) { $match = $window }

  $sw = [System.Diagnostics.Stopwatch]::StartNew()
  $shot = Invoke-Appshot -Match $match -Semantic:$true
  if (-not $shot) {
    $sw.Stop()
    if ($Brief -and -not $jsonOnly) {
      [Console]::Out.WriteLine("partial list-affordances appshot_failed match='$match'")
    } else {
      $err = _New-ObservationEnvelope `
        -Kind "list-affordances" -Status "partial" `
        -ElapsedMs ([int]$sw.Elapsed.TotalMilliseconds) `
        -Sources @("appshot") `
        -Data ([pscustomobject]@{ match = $match; window = $window; limit = $limit }) `
        -RecoverableErrors @([pscustomobject]@{
          code = "appshot_failed"
          message = "observe appshot returned no usable artifact"
          recommended_action = "Run 'cucp macro ensure-helper' or verify '$match' exists with 'cucp macro windows'."
        })
      [Console]::Out.WriteLine(($err | ConvertTo-Json -Depth 8))
    }
    return 2
  }

  $items = @()
  if ($shot.Grounded) {
    foreach ($g in $shot.Grounded) {
      if (-not $g.text -or -not $g.rect) { continue }
      if ($Window -and $g.window -and ($g.window.ToLowerInvariant() -notmatch [regex]::Escape($Window.ToLowerInvariant()))) { continue }
      $center = Get-ElementCenter -Element $g
      $items += [pscustomobject]@{
        affordance_id = $g.affordance_id
        text = $g.text
        role = $g.role
        window = $g.window
        center = $center
        confidence = $g.confidence
        sources = $g.sources
      }
      if ($items.Count -ge $limit) { break }
    }
  }
  $sw.Stop()
  $elapsed = [int]$sw.Elapsed.TotalMilliseconds

  $sourceTags = @("appshot")
  if ($shot.Grounded -and $shot.Grounded.Count -gt 0) { $sourceTags += "uia" }
  if ($shot.FromCache) { $sourceTags += "cache" }

  $cacheMeta = [pscustomobject]@{
    hit = [bool]$shot.FromCache
    age_ms = $null
    max_age_ms = ($CacheSeconds * 1000)
    key = "appshot::match=$match"
    reason = if ($shot.FromCache) { "cache_fresh" } else { "live_capture" }
  }

  $foreground = $null
  if ($shot.FocusedWindow) { $foreground = [pscustomobject]@{ title = $shot.FocusedWindow } }

  # Backwards-compatible top-level shape for legacy parsers.
  $payload = [pscustomobject]@{
    status = "ok"
    schema = "cucp.list-affordances/v2"
    observation_id = $shot.ObservationId
    focused_window = $shot.FocusedWindow
    from_cache = [bool]$shot.FromCache
    affordance_count = $items.Count
    affordances = $items
    elapsed_ms = $elapsed
    sources = $sourceTags
    cache = $cacheMeta
    _envelope = (_New-ObservationEnvelope `
      -Kind "list-affordances" -Status "ok" `
      -ElapsedMs $elapsed `
      -Sources $sourceTags `
      -ObservationId $shot.ObservationId `
      -Foreground $foreground `
      -Data ([pscustomobject]@{
        affordance_count = $items.Count
        match = $match
        window = $window
        limit = $limit
        affordances = $items
      }) `
      -Cache $cacheMeta `
      -Confidence "high")
  }
  if ($Brief -and -not $jsonOnly) {
    [Console]::Out.WriteLine("ok list-affordances count=$($items.Count) win='$($shot.FocusedWindow)' cached=$([bool]$shot.FromCache) elapsed_ms=$elapsed")
  } else {
    [Console]::Out.WriteLine(($payload | ConvertTo-Json -Depth 8))
  }
  return 0
}

function Invoke-MacroClickId {
  param([string[]]$Rest, [switch]$Double, [switch]$RightClick)
  $id = _Read-OptValue -Rest $Rest -Name "--id"
  $match = _Read-OptValue -Rest $Rest -Name "--match"
  $window = _Read-OptValue -Rest $Rest -Name "--window"
  if (-not $id) { throw "macro click-id requires --id" }
  if (-not $AllowLiveControl) { throw "macro click-id requires -AllowLiveControl" }
  if (-not $match) { $match = $window }

  $shot = Invoke-Appshot -Match $match -Semantic:$true -NoCache
  if (-not $shot) { throw "appshot failed" }
  $el = Find-AffordanceById -Appshot $shot -Id $id
  if (-not $el) {
    Write-Notice -Level "ERROR" -Message "affordance_id를 찾지 못했습니다: '$id'. macro list-affordances로 현재 목록 확인하세요."
    throw "affordance_id not found: $id"
  }
  $center = Get-ElementCenter -Element $el
  $cucpArgs = @("act", "click", "--x", "$($center.X)", "--y", "$($center.Y)", "--after", $shot.ObservationId)
  if ($el.window) { $cucpArgs += @("--target-window", $el.window) }
  $r = Invoke-Cucp -ArgList $cucpArgs
  if ($Brief) {
    if ($r.ExitCode -eq 0) { [Console]::Out.WriteLine("ok click-id '$id' @($($center.X),$($center.Y))") }
    else { [Console]::Out.WriteLine("err click-id '$id' exit=$($r.ExitCode)") }
  }
  return $r.ExitCode
}

function Invoke-MacroWaitLabel {
  param([string[]]$Rest)
  $label = _Read-OptValue -Rest $Rest -Name "--label"
  $window = _Read-OptValue -Rest $Rest -Name "--window"
  $match = _Read-OptValue -Rest $Rest -Name "--match"
  $timeout = [int](_Read-OptValue -Rest $Rest -Name "--timeout-ms")
  $interval = [int](_Read-OptValue -Rest $Rest -Name "--interval-ms")
  if (-not $label) { throw "macro wait-label requires --label" }
  if (-not $match) { $match = $window }
  if ($timeout -le 0) { $timeout = 10000 }
  if ($interval -le 0) { $interval = 600 }

  $deadline = (Get-Date).AddMilliseconds($timeout)
  $attempts = 0
  while ((Get-Date) -lt $deadline) {
    $attempts++
    # bypass cache: this is a polling loop
    $shot = Invoke-Appshot -Match $match -Semantic:$true -NoCache
    if ($shot) {
      $el = Find-Element -Appshot $shot -Label $label -Window $window
      if ($el) {
        if ($Brief) { [Console]::Out.WriteLine("ok wait-label '$label' attempts=$attempts") }
        else { Write-Notice -Level "OK" -Message "라벨 발견: '$label' (attempts=$attempts)" }
        return 0
      }
    }
    Start-Sleep -Milliseconds $interval
  }
  if ($Brief) { [Console]::Out.WriteLine("err wait-label '$label' timeout") }
  Write-Notice -Level "ERROR" -Message "라벨을 찾지 못했습니다: '$label' (timeout=${timeout}ms, attempts=$attempts)"
  return 1
}

function Invoke-MacroFindLabel {param([string[]]$Rest) return _Invoke-LegacyInteractionFamily -Operation 'find-label' -Rest $Rest -ScriptPath $PSCommandPath}

function Invoke-MacroClickLabel {param([string[]]$Rest,[switch]$Double,[switch]$RightClick) return _Invoke-LegacyInteractionFamily -Operation 'click-label' -Rest $Rest -ScriptPath $PSCommandPath -Double ([bool]$Double) -RightClick ([bool]$RightClick)}

function Invoke-MacroFillLabel {
  param([string[]]$Rest)
  $label  = _Read-OptValue -Rest $Rest -Name "--label"
  $text   = _Read-OptValue -Rest $Rest -Name "--text"
  $window = _Read-OptValue -Rest $Rest -Name "--window"
  $match  = _Read-OptValue -Rest $Rest -Name "--match"
  $role   = _Read-OptValue -Rest $Rest -Name "--role"
  $clear  = _Read-Switch -Rest $Rest -Name "--clear"
  $enter  = _Read-Switch -Rest $Rest -Name "--enter"
  if (-not $label) { throw "macro fill-label requires --label" }
  if ($null -eq $text) { throw "macro fill-label requires --text" }
  if (-not $match) { $match = $window }
  if (-not $AllowLiveControl) { throw "macro fill-label requires -AllowLiveControl" }

  $shot = Invoke-Appshot -Match $match -Semantic:$true -NoCache
  if (-not $shot) { throw "appshot failed" }

  $el = Find-Element -Appshot $shot -Label $label -Window $window -Role $role
  if (-not $el) { throw "Label not found: $label" }

  $center = Get-ElementCenter -Element $el
  $cucpArgs = @("act", "type", "--text", $text, "--x", "$($center.X)", "--y", "$($center.Y)", "--after", $shot.ObservationId)
  if ($el.window) { $cucpArgs += @("--target-window", $el.window) }
  if ($clear) { $cucpArgs += "--clear" }
  if ($enter) { $cucpArgs += "--enter" }
  $r = Invoke-Cucp -ArgList $cucpArgs
  if ($Brief) {
    if ($r.ExitCode -eq 0) { Write-Output "ok fill-label '$label'" }
    else { Write-Output "err fill-label '$label' exit=$($r.ExitCode)" }
  }
  return $r.ExitCode
}

function Invoke-MacroFocusWindow {
  param([string[]]$Rest)
  $name = _Read-OptValue -Rest $Rest -Name "--name"
  if (-not $name) { throw "macro focus-window requires --name" }
  if (-not $AllowLiveControl) { throw "macro focus-window requires -AllowLiveControl" }
  $win = _Native-FocusWindow -Name $name
  $exit = if ($win) { 0 } else { 1 }
  if ($Brief) {
    if ($exit -eq 0) {
      Write-Output "ok focus '$name' source=native title='$($win.title)'"
    } else {
      # Provide a deterministic recovery hint when focus fails. Most common
      # cause is that the requested window is not running. Probe with Win32.
      $cands = _Enumerate-Win32Windows -Match $name
      $visible = @($cands | Where-Object { $_.visible -and -not $_.minimized })
      $hint = if ($visible.Count -gt 0) {
        "candidate window present (pid=$($visible[0].pid)); use 'cucp -AllowLiveControl macro focus-verify --name `"$name`"' to confirm foreground."
      } else {
        "no visible window matches '$name'. Use 'cucp macro app-launch --name `"$name`"' first."
      }
      Write-Output "err focus '$name' exit=$exit hint=$hint"
    }
  }
  return $exit
}

function Invoke-MacroWaitWindow {
  param([string[]]$Rest)
  $title = _Read-OptValue -Rest $Rest -Name "--title"
  $timeout = [int](_Read-OptValue -Rest $Rest -Name "--timeout-ms")
  $interval = [int](_Read-OptValue -Rest $Rest -Name "--interval-ms")
  $noFallback = _Read-Switch -Rest $Rest -Name "--no-win32-fallback"
  if (-not $title) { throw "macro wait-window requires --title" }
  if ($timeout -le 0) { $timeout = 10000 }
  if ($interval -le 0) { $interval = 500 }

  $deadline = (Get-Date).AddMilliseconds($timeout)
  $attempts = 0
  $lastSource = ""
  while ((Get-Date) -lt $deadline) {
    $attempts++
    $r = Invoke-Cucp -ArgList @("observe", "windows", "--match", $title) -CaptureJson
    if ($r.Json -and $r.Json.status -eq "ok") {
      $items = $r.Json.artifacts | Where-Object { $_.type -eq "windows" } | ForEach-Object { $_.items }
      if ($items -and $items.Count -gt 0) {
        $lastSource = "helper"
        if ($Brief) { [Console]::Out.WriteLine("ok wait-window '$title' source=helper attempts=$attempts") }
        else { Write-Notice -Level "OK" -Message "윈도우 발견(helper): '$title' (attempts=$attempts)" }
        return 0
      }
    }
    # Win32 EnumWindows fallback: helper가 false-empty를 줄 때도 결정적으로 잡음
    if (-not $noFallback) {
      $w32 = _Enumerate-Win32Windows -Match $title
      $visible = @($w32 | Where-Object { $_.visible -and -not $_.minimized })
      if ($visible.Count -gt 0) {
        $first = $visible | Select-Object -First 1
        $lastSource = "win32"
        if ($Brief) { [Console]::Out.WriteLine(("ok wait-window '{0}' source=win32 attempts={1} title='{2}' pid={3}" -f `
          $title, $attempts, $first.title, $first.pid)) }
        else { Write-Notice -Level "OK" -Message ("윈도우 발견(win32 fallback): '$title' pid=$($first.pid) attempts=$attempts") }
        return 0
      }
    }
    Start-Sleep -Milliseconds $interval
  }
  # On timeout, attach evidence about what we *did* see, so the operator
  # can decide whether to retry, narrow, or change source.
  $lastWin32 = if (-not $noFallback) { @(_Enumerate-Win32Windows -Match $null | Where-Object { $_.visible }) } else { @() }
  $sample = ($lastWin32 | Select-Object -First 5 | ForEach-Object { "'$($_.title)'" }) -join ", "
  if ($Brief) { [Console]::Out.WriteLine(("partial wait-window '{0}' timeout attempts={1} visible_count={2}" -f $title, $attempts, $lastWin32.Count)) }
  Write-Notice -Level "ERROR" -Message "윈도우를 찾지 못했습니다: '$title' (timeout=${timeout}ms, attempts=$attempts). 현재 보이는 창 샘플: $sample"
  return 2
}

function Invoke-MacroShortcut {
  param([string[]]$Rest)
  $keys = _Read-OptValue -Rest $Rest -Name "--keys"
  if (-not $keys) { throw "macro shortcut requires --keys" }
  if (-not $AllowLiveControl) { throw "macro shortcut requires -AllowLiveControl" }
  try {
    _Native-SendShortcut -Keys $keys
    $exit = 0
  } catch {
    Write-Notice -Level "ERROR" -Message "shortcut 실패: $($_.Exception.Message)"
    $exit = 1
  }
  if ($Brief) {
    if ($exit -eq 0) { Write-Output "ok shortcut '$keys' source=native" } else { Write-Output "err shortcut '$keys' exit=$exit" }
  }
  return $exit
}

function Invoke-MacroClipboard {
  param([string[]]$Rest)
  $text = _Read-OptValue -Rest $Rest -Name "--set"
  if ($null -eq $text) { $text = _Read-OptValue -Rest $Rest -Name "--text" }
  $paste = _Read-Switch -Rest $Rest -Name "--paste"
  $get = _Read-Switch -Rest $Rest -Name "--get"
  if ($get) {
    _Ensure-NativeDesktopTypes
    $value = [System.Windows.Forms.Clipboard]::GetText()
    if ($Brief) { [Console]::Out.WriteLine("ok clipboard get length=$($value.Length)") } else { [Console]::Out.WriteLine($value) }
    return 0
  }
  if ($null -eq $text) { throw "macro clipboard requires --set <text>, --text <text>, or --get" }
  if (-not $AllowLiveControl) { throw "macro clipboard set/paste requires -AllowLiveControl" }
  _Native-SetClipboard -Text $text
  if ($paste) {
    Start-Sleep -Milliseconds 100
    _Native-SendShortcut -Keys "ctrl+v"
  }
  _Trajectory-Append -Kind "clipboard" -Payload @{ set_length = $text.Length; pasted = [bool]$paste; source = "native" }
  if ($Brief) { [Console]::Out.WriteLine("ok clipboard set length=$($text.Length) paste=$([bool]$paste) source=native") }
  return 0
}

function Invoke-MacroGoal {
  param([string[]]$Rest)
  $objective = _Read-OptValue -Rest $Rest -Name "--objective"
  $maxSteps = [int](_Read-OptValue -Rest $Rest -Name "--max-steps")
  $maxPhase = [int](_Read-OptValue -Rest $Rest -Name "--max-phase-ms")
  $provider = _Read-OptValue -Rest $Rest -Name "--provider"
  $verifyLabel = _Read-OptValue -Rest $Rest -Name "--verify-label"
  $verifyWindow = _Read-OptValue -Rest $Rest -Name "--verify-window"
  $verifyTimeout = [int](_Read-OptValue -Rest $Rest -Name "--verify-timeout-ms")
  $dryRun = _Read-Switch -Rest $Rest -Name "--dry-run"

  if (-not $objective) { throw "macro goal requires --objective" }
  if ($maxSteps -le 0) { $maxSteps = 60 }
  if ($maxPhase -le 0) { $maxPhase = 600000 }
  if (-not $provider) { $provider = "heuristic" }
  if ($verifyTimeout -le 0) { $verifyTimeout = 8000 }

  if ($dryRun) {
    $cucpArgs = @("l5", "capability", "--objective", $objective, "--provider", $provider, "--max-phase-ms", "$maxPhase")
    Write-Notice -Level "INFO" -Message "Goal 드라이런: $objective"
    $r = Invoke-Cucp -ArgList $cucpArgs
    return $r.ExitCode
  }

  if (-not $AllowLiveControl) { throw "macro goal (live) requires -AllowLiveControl" }

  Write-Notice -Level "WARN" -Message "Goal 자율 실행 시작: $objective (max-steps=$maxSteps)"
  $cucpArgs = @("l5", "run", "--objective", $objective, "--provider", $provider,
            "--allow-control", "--max-steps", "$maxSteps", "--max-phase-ms", "$maxPhase")
  $runResult = Invoke-Cucp -ArgList $cucpArgs
  $runOk = ($runResult.ExitCode -eq 0)

  # Self-verification phase: if user provided a verify-label, poll for it.
  $verifyOk = $true
  if ($verifyLabel) {
    Write-Notice -Level "INFO" -Message "자가 검증: '$verifyLabel' 등장 대기 (timeout=${verifyTimeout}ms)"
    $verifyArgs = @("macro", "wait-label", "--label", $verifyLabel, "--timeout-ms", "$verifyTimeout")
    if ($verifyWindow) { $verifyArgs += @("--window", $verifyWindow) }
    # call our own wrapper recursively to reuse appshot/find-label logic
    $verifyOutput = & $PSCommandPath @verifyArgs
    $verifyOk = ($LASTEXITCODE -eq 0)
  }

  if ($Brief) {
    if ($runOk -and $verifyOk) { [Console]::Out.WriteLine("ok goal '$objective'") }
    elseif (-not $runOk) { [Console]::Out.WriteLine("err goal '$objective' run-exit=$($runResult.ExitCode)") }
    else { [Console]::Out.WriteLine("err goal '$objective' verify-failed label='$verifyLabel'") }
  }

  if (-not $runOk) { return $runResult.ExitCode }
  if (-not $verifyOk) { return 2 }
  return 0
}

function Invoke-MacroSelfTest {param([string[]]$Rest) return _Invoke-LegacyDiagnosticFamily -Operation 'self-test' -Rest $Rest}



function Invoke-MacroTrajectory {
  param([string[]]$Rest)
  $action = if ($Rest.Count -ge 1) { $Rest[0] } else { "show" }
  $last = [int](_Read-OptValue -Rest $Rest -Name "--last")
  if ($last -le 0) { $last = 20 }
  switch ($action) {
    "show" {
      $entries = _Trajectory-Read -Last $last
      $payload = [pscustomobject]@{
        status = "ok"
        count = (@($entries)).Count
        path = $Script:TrajectoryFile
        entries = $entries
      }
      if ($Brief) {
        [Console]::Out.WriteLine(("ok trajectory count={0}" -f $payload.count))
      } else {
        [Console]::Out.WriteLine(($payload | ConvertTo-Json -Depth 6))
      }
      return 0
    }
    "clear" {
      _Trajectory-Clear
      Write-Notice -Level "OK" -Message "trajectory 초기화"
      if ($Brief) { [Console]::Out.WriteLine("ok trajectory cleared") }
      return 0
    }
    "tail" {
      # Same as show but returns only the most recent entry's summary line
      $entries = _Trajectory-Read -Last 1
      if ($entries.Count -eq 0) {
        if ($Brief) { [Console]::Out.WriteLine("err trajectory empty") } else { [Console]::Out.WriteLine("{}") }
        return 1
      }
      [Console]::Out.WriteLine(($entries[0] | ConvertTo-Json -Compress -Depth 6))
      return 0
    }
    default {
      Write-Notice -Level "ERROR" -Message "trajectory 하위 명령: show | tail | clear"
      return 1
    }
  }
}

function Invoke-MacroEnsureHelper {
  param([string[]]$Rest)
  $waitMs = [int](_Read-OptValue -Rest $Rest -Name "--wait-ms")
  if ($waitMs -le 0) { $waitMs = 8000 }
  $ok = _Helper-Ensure -WaitMs $waitMs
  $report = [pscustomobject]@{
    status = if ($ok) { "ok" } else { "fail" }
    helper_running = $ok
  }
  if ($Brief) {
    [Console]::Out.WriteLine(("{0} helper running={1}" -f $report.status, $ok))
  } else {
    [Console]::Out.WriteLine(($report | ConvertTo-Json))
  }
  if ($ok) { return 0 } else { return 1 }
}

# ============================================================================
# Vision grounding via codex CLI
# ============================================================================
# When UIA + OCR fusion can't find a label (custom UI, browser canvas, game
# elements, dialogs without accessibility tree), this calls the local `codex`
# CLI with --image and --output-schema to get a structured (x,y) coordinate.
# This is the bridge that lets cucp + Codex match Claude Computer Use on
# arbitrary UIs while keeping our determinism on standard Win32/UIA ones.
# ============================================================================

function _Get-VisionWorkDir {
  $dir = Join-Path $Script:CacheDir "vision"
  if (-not (Test-Path -LiteralPath $dir)) {
    New-Item -ItemType Directory -Path $dir -Force | Out-Null
  }
  return $dir
}

function _Find-CodexCli {
  # On Windows, prefer .cmd / .exe over the bare entrypoint (where.exe returns
  # multiple matches and the first is often a Unix-style script that can't be
  # spawned directly via Process.Start).
  $cmd = Get-Command "codex.exe" -ErrorAction SilentlyContinue
  if ($cmd) { return $cmd.Source }
  $cmd = Get-Command "codex.cmd" -ErrorAction SilentlyContinue
  if ($cmd) { return $cmd.Source }
  $cmd = Get-Command "codex" -ErrorAction SilentlyContinue
  if ($cmd) {
    $src = $cmd.Source
    if ($src -and ($src.EndsWith(".exe") -or $src.EndsWith(".cmd") -or $src.EndsWith(".bat"))) {
      return $src
    }
    # Try sibling .cmd
    $cmdSibling = $src + ".cmd"
    if (Test-Path -LiteralPath $cmdSibling) { return $cmdSibling }
  }
  return $null
}

function _Quote-NativeWindowsArgument {
  param([AllowEmptyString()][string]$Value)
  # Windows CRT argv escaping, not cmd.exe shell escaping.
  $escaped = [regex]::Replace($Value, '(\\*)"', '$1$1\"')
  $escaped = [regex]::Replace($escaped, '(\\+)$', '$1$1')
  return '"' + $escaped + '"'
}

function _Invoke-CodexVision {
  <#
    Send a screenshot + question to codex CLI and parse a {found,x,y,confidence,reasoning}
    JSON response. Returns a pscustomobject or $null on failure.
  #>
  param(
    [Parameter(Mandatory)] [string]$ScreenshotPath,
    [Parameter(Mandatory)] [string]$Description,
    [int]$ImageWidth = 1920,
    [int]$ImageHeight = 1080,
    [int]$TimeoutMs = 90000,
    [string]$Model
  )

  $codex = _Find-CodexCli
  if (-not $codex) {
    Write-WrapperLog -Message "vision: codex CLI not found"
    return [pscustomobject]@{ status = "error"; reason = "codex CLI not found in PATH" }
  }

  if (-not (Test-Path -LiteralPath $ScreenshotPath)) {
    return [pscustomobject]@{ status = "error"; reason = "screenshot not found: $ScreenshotPath" }
  }

  $work = _Get-VisionWorkDir
  $stamp = (Get-Date).ToString("yyyyMMdd-HHmmss-fff")
  $schemaPath = Join-Path $work "schema-$stamp.json"
  $outPath    = Join-Path $work "out-$stamp.json"

  $schema = @{
    type = "object"
    required = @("found", "x", "y", "confidence", "reasoning")
    additionalProperties = $false
    properties = @{
      found = @{ type = "boolean" }
      x = @{ type = "integer" }
      y = @{ type = "integer" }
      confidence = @{ type = "string"; enum = @("high","medium","low") }
      reasoning = @{ type = "string"; maxLength = 200 }
    }
  } | ConvertTo-Json -Depth 5
  [System.IO.File]::WriteAllText($schemaPath, $schema, [System.Text.UTF8Encoding]::new($false))

  $prompt = @"
You are a Windows GUI grounding model. The attached image is a $ImageWidth x $ImageHeight screenshot of the user's desktop.

Find: $Description

Return ONLY a single JSON object that matches the provided output schema.
- found: true if you can identify the element, false otherwise
- x, y: integer pixel coordinates of the element's center, in the $ImageWidth x $ImageHeight image space
- confidence: "high" | "medium" | "low"
- reasoning: short one-sentence justification

Do NOT include markdown fences, prose, or explanations outside the JSON object.
"@

  Write-WrapperLog -Message "vision: codex exec for '$Description' (cli=$codex)"
  try {
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.UseShellExecute = $false
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.CreateNoWindow = $true
    $psi.StandardOutputEncoding = [System.Text.Encoding]::UTF8
    $psi.StandardErrorEncoding = [System.Text.Encoding]::UTF8

    # Optional provider adapter only. Batch wrappers interpret metacharacters;
    # require a native executable rather than evaluating untrusted text in cmd.
    if (-not $codex.EndsWith(".exe", [StringComparison]::OrdinalIgnoreCase)) {
      return [pscustomobject]@{ status = "error"; reason = "vision provider requires a native codex.exe; .cmd/.bat shell wrappers are disabled" }
    }
    $nativeArgs = @("exec", "--image", $ScreenshotPath, "--output-schema", $schemaPath,
      "--output-last-message", $outPath, "--skip-git-repo-check")
    if ($Model) { $nativeArgs += @("--model", $Model) }
    $nativeArgs += @($prompt)
    $psi.FileName = $codex
    $psi.Arguments = (@($nativeArgs | ForEach-Object { _Quote-NativeWindowsArgument -Value $_ }) -join " ")


    $proc = [System.Diagnostics.Process]::Start($psi)
    $stdoutTask = $proc.StandardOutput.ReadToEndAsync()
    $stderrTask = $proc.StandardError.ReadToEndAsync()
    $exited = $proc.WaitForExit($TimeoutMs)
    if (-not $exited) {
      try { $proc.Kill() } catch { }
      try { [void]$proc.WaitForExit(3000) } catch { }
      Write-WrapperLog -Message "vision: codex TIMEOUT after ${TimeoutMs}ms"
      return [pscustomobject]@{ status = "error"; reason = "codex exec timeout" }
    }
    $rawOut = $stdoutTask.GetAwaiter().GetResult()
    $rawErr = $stderrTask.GetAwaiter().GetResult()

    if ($proc.ExitCode -ne 0) {
      Write-WrapperLog -Message "vision: codex exit=$($proc.ExitCode) err=$rawErr"
      return [pscustomobject]@{ status = "error"; reason = "codex exec failed (exit=$($proc.ExitCode))"; stderr = $rawErr }
    }

    if (-not (Test-Path -LiteralPath $outPath)) {
      return [pscustomobject]@{ status = "error"; reason = "codex did not write output file" }
    }
    $rawJson = Get-Content -LiteralPath $outPath -Raw -Encoding UTF8
    try {
      $parsed = $rawJson | ConvertFrom-Json -ErrorAction Stop
    } catch {
      return [pscustomobject]@{ status = "error"; reason = "codex output is not valid JSON"; raw = $rawJson }
    }

    if (-not $parsed.found) {
      return [pscustomobject]@{ status = "not_found"; reasoning = $parsed.reasoning; raw = $parsed }
    }

    return [pscustomobject]@{
      status = "ok"
      x = [int]$parsed.x
      y = [int]$parsed.y
      confidence = "$($parsed.confidence)"
      reasoning = "$($parsed.reasoning)"
      raw = $parsed
    }
  } catch {
    return [pscustomobject]@{ status = "error"; reason = $_.Exception.Message }
  }
}

function Invoke-MacroVisionFind {
  param([string[]]$Rest)
  # v2.0.0 — vision LLM token budget gate (공통 헬퍼). 한도 초과 시 exit 3.
  $gate = _Vision-GateOrRecord -Macro "vision-find" -EstimatedTokens 1000
  if ($null -ne $gate) { return $gate }
  $description = _Read-OptValue -Rest $Rest -Name "--describe"
  $screenshot = _Read-OptValue -Rest $Rest -Name "--screenshot"
  $model = _Read-OptValue -Rest $Rest -Name "--model"
  $timeoutMs = [int](_Read-OptValue -Rest $Rest -Name "--timeout-ms")
  if ($timeoutMs -le 0) { $timeoutMs = 90000 }
  if (-not $description) { throw "macro vision-find requires --describe" }

  # If no screenshot given, capture one via wrapper
  if (-not $screenshot) {
    $shotDir = _Get-VisionWorkDir
    $screenshot = Join-Path $shotDir ("vision-shot-" + (Get-Date).ToString("yyyyMMddHHmmssfff") + ".png")
    $shotArgs = @("observe", "screenshot", "--out", $screenshot)
    $r = Invoke-Cucp -ArgList $shotArgs -CaptureJson
    if ($r.ExitCode -ne 0 -or -not (Test-Path -LiteralPath $screenshot)) {
      throw "vision-find could not capture screenshot via wrapper (exit=$($r.ExitCode))"
    }
  }

  $result = _Invoke-CodexVision -ScreenshotPath $screenshot -Description $description -TimeoutMs $timeoutMs -Model $model
  $payload = [pscustomobject]@{
    status = $result.status
    description = $description
    screenshot = $screenshot
    x = $result.x
    y = $result.y
    confidence = $result.confidence
    reasoning = $result.reasoning
    reason = $result.reason
  }

  _Trajectory-Append -Kind "vision_find" -Payload @{
    description = $description
    status = "$($result.status)"
    x = $result.x
    y = $result.y
    confidence = "$($result.confidence)"
  }

  if ($Brief) {
    if ($result.status -eq "ok") {
      [Console]::Out.WriteLine("ok vision-find @($($result.x),$($result.y)) conf=$($result.confidence)")
    } elseif ($result.status -eq "not_found") {
      [Console]::Out.WriteLine("err vision-find not_found")
    } else {
      [Console]::Out.WriteLine("err vision-find $($result.reason)")
    }
  } else {
    [Console]::Out.WriteLine(($payload | ConvertTo-Json -Depth 6))
  }
  if ($result.status -eq "ok") { return 0 } else { return 1 }
}

function Invoke-MacroVisionClick {
  param([string[]]$Rest)
  # v2.0.0 — vision LLM token budget gate (공통 헬퍼). 한도 초과 시 exit 3.
  $gate = _Vision-GateOrRecord -Macro "vision-click" -EstimatedTokens 1500
  if ($null -ne $gate) { return $gate }
  $description = _Read-OptValue -Rest $Rest -Name "--describe"
  $window = _Read-OptValue -Rest $Rest -Name "--window"
  $verifyLabel = _Read-OptValue -Rest $Rest -Name "--verify-label"
  $verifyTimeout = [int](_Read-OptValue -Rest $Rest -Name "--verify-timeout-ms")
  $model = _Read-OptValue -Rest $Rest -Name "--model"
  if (-not $description) { throw "macro vision-click requires --describe" }
  if ($verifyTimeout -le 0) { $verifyTimeout = 5000 }
  if (-not $AllowLiveControl) { throw "macro vision-click requires -AllowLiveControl" }

  # 1) capture screenshot via wrapper (creates an observation_id we can use for --after)
  $shotDir = _Get-VisionWorkDir
  $shotPath = Join-Path $shotDir ("click-shot-" + (Get-Date).ToString("yyyyMMddHHmmssfff") + ".png")
  $shotArgs = @("observe", "screenshot", "--out", $shotPath)
  $shotResult = Invoke-Cucp -ArgList $shotArgs -CaptureJson
  if ($shotResult.ExitCode -ne 0) { throw "vision-click could not capture screenshot" }
  $obsId = $null
  if ($shotResult.Json -and $shotResult.Json.observation -and $shotResult.Json.observation.id) {
    $obsId = $shotResult.Json.observation.id
  }
  if (-not $obsId) {
    # Fallback: appshot to get observation_id explicitly
    $shot = Invoke-Appshot -Match $window -Semantic:$false -NoCache
    if ($shot) { $obsId = $shot.ObservationId }
  }
  if (-not $obsId) { throw "vision-click could not establish observation_id" }

  # 2) Ask codex to find coordinates
  $result = _Invoke-CodexVision -ScreenshotPath $shotPath -Description $description -Model $model
  if ($result.status -ne "ok") {
    if ($Brief) { [Console]::Out.WriteLine("err vision-click $($result.status)") }
    Write-Notice -Level "ERROR" -Message "vision-click 좌표 추론 실패: $($result.reason)$($result.reasoning)"
    return 1
  }

  # 3) Click via wrapper
  $clickArgs = @("act", "click", "--x", "$($result.x)", "--y", "$($result.y)", "--after", $obsId)
  if ($window) { $clickArgs += @("--target-window", $window) }
  $r = Invoke-Cucp -ArgList $clickArgs

  _Trajectory-Append -Kind "vision_click" -Payload @{
    description = $description
    x = $result.x
    y = $result.y
    confidence = "$($result.confidence)"
    observation_id = $obsId
    exit = $r.ExitCode
  }

  # 4) Optional verification: a label must appear after the click
  $verifyOk = $true
  if ($r.ExitCode -eq 0 -and $verifyLabel) {
    $waitArgs = @("macro", "wait-label", "--label", $verifyLabel, "--timeout-ms", "$verifyTimeout")
    if ($window) { $waitArgs += @("--window", $window) }
    $verifyExit = & $PSCommandPath @waitArgs
    $verifyOk = ($LASTEXITCODE -eq 0)
  }

  if ($Brief) {
    if ($r.ExitCode -eq 0 -and $verifyOk) {
      [Console]::Out.WriteLine("ok vision-click @($($result.x),$($result.y)) conf=$($result.confidence)")
    } elseif ($r.ExitCode -ne 0) {
      [Console]::Out.WriteLine("err vision-click click-exit=$($r.ExitCode)")
    } else {
      [Console]::Out.WriteLine("err vision-click verify-failed label='$verifyLabel'")
    }
  }
  if ($r.ExitCode -ne 0) { return $r.ExitCode }
  if (-not $verifyOk) { return 2 }
  return 0
}

# ============================================================================
# Operational metrics + health-detail
# ============================================================================
# These give Codex (and any caller) a deterministic, machine-parseable health
# snapshot suitable for production dashboards and CI gates. Reads ONLY from
# durable artifacts written by the wrapper itself (no helper round-trips).
# ============================================================================

function Invoke-MacroMetrics {
  param([string[]]$Rest)
  $traj = _Trajectory-Read -Last 500
  $obsCount = (@($traj | Where-Object { $_.kind -eq "observation" })).Count
  $clickCount = (@($traj | Where-Object { $_.kind -eq "click" })).Count
  $visionFindCount = (@($traj | Where-Object { $_.kind -eq "vision_find" })).Count
  $visionClickCount = (@($traj | Where-Object { $_.kind -eq "vision_click" })).Count

  # Click success rate from trajectory (exit==0)
  $clickEntries = @($traj | Where-Object { $_.kind -eq "click" })
  $clickOk = (@($clickEntries | Where-Object { [int]$_.exit -eq 0 })).Count
  $clickRate = if ($clickEntries.Count -gt 0) { [Math]::Round(($clickOk / $clickEntries.Count) * 100, 1) } else { 0 }

  # Cache hit ratio
  $obsEntries = @($traj | Where-Object { $_.kind -eq "observation" })
  $cachedHits = (@($obsEntries | Where-Object { $_.from_cache -eq $true })).Count
  $cacheRate = if ($obsEntries.Count -gt 0) { [Math]::Round(($cachedHits / $obsEntries.Count) * 100, 1) } else { 0 }

  # Vision usage
  $visionUsed = $visionFindCount + $visionClickCount

  # Audit log size
  $logSize = if (Test-Path $Script:WrapperLog) { (Get-Item $Script:WrapperLog).Length } else { 0 }
  $cacheCount = (Get-ChildItem -LiteralPath $Script:CacheDir -Filter "appshot-*.json" -ErrorAction SilentlyContinue).Count

  $metrics = [pscustomobject]@{
    status = "ok"
    collected_at = (Get-Date).ToString("o")
    counters = [pscustomobject]@{
      observations = $obsCount
      clicks = $clickCount
      vision_finds = $visionFindCount
      vision_clicks = $visionClickCount
      total_actions = $clickCount + $visionClickCount
    }
    rates = [pscustomobject]@{
      click_success_pct = $clickRate
      cache_hit_pct = $cacheRate
    }
    storage = [pscustomobject]@{
      audit_log_bytes = $logSize
      cache_files = $cacheCount
      cache_dir = $Script:CacheDir
      trajectory_path = $Script:TrajectoryFile
    }
    config = [pscustomobject]@{
      cache_seconds = $CacheSeconds
      invoke_timeout_ms = $InvokeTimeoutMs
      cli_path = $Script:CliPath
    }
  }

  if ($Brief) {
    [Console]::Out.WriteLine(("ok metrics obs={0} clicks={1} vision={2} click_success={3}% cache_hit={4}%" -f `
      $obsCount, $clickCount, $visionUsed, $clickRate, $cacheRate))
  } else {
    [Console]::Out.WriteLine(($metrics | ConvertTo-Json -Depth 6))
  }
  return 0
}

function _New-ObservationEnvelope {
  <#
    Unified observation envelope used by macro windows / find-label / list-affordances /
    health-quick / focus-verify. Provides consistent shape so Codex can rely on
    a single schema regardless of which underlying source served the data.

    Fields:
      schema             : "cucp.observation/v1"
      kind               : "windows" | "find-label" | "list-affordances" | "context" | etc
      status             : "ok" | "partial" | "error"
      collected_at       : ISO8601
      elapsed_ms         : total wall clock for this observation
      sources            : array of strings (any of: win32, helper, uia, ocr,
                           screenshot, cache, vision, fallback)
      provenance         : per-field source map (e.g. {foreground:"win32", items:"win32"})
      observation_id     : (optional) underlying CUCP observation id when relevant
      foreground         : focused/active window summary (title, hwnd, pid, process)
      active_hwnd        : authoritative HWND of foreground window
      focused_title      : foreground title for quick consumption
      desktop            : @{ width, height } if known
      windows            : normalized list (or null if not applicable)
      data               : kind-specific payload object
      cache              : @{ hit, age_ms, max_age_ms, key, reason }
      stale              : bool — true if any contributing data is older than its budget
      confidence         : "high" | "medium" | "low" (overall observation confidence)
      warnings           : non-fatal soft issues
      recoverable_errors : array of @{ code, message, recommended_action }
      degraded_helper_empty : bool — true when helper returned empty but win32 has data
  #>
  param(
    [string]$Kind,
    [string]$Status = "ok",
    [int]$ElapsedMs = 0,
    [string[]]$Sources = @(),
    $Provenance = $null,
    [string]$ObservationId,
    $Foreground = $null,
    $Windows = $null,
    $Data = $null,
    $Cache = $null,
    [bool]$Stale = $false,
    [string]$Confidence = "high",
    [string[]]$Warnings = @(),
    $RecoverableErrors = @(),
    [bool]$DegradedHelperEmpty = $false,
    $Desktop = $null
  )
  $fgTitle = ""
  $activeHwnd = 0
  if ($Foreground) {
    $fgTitle = "$($Foreground.title)"
    if ($null -ne $Foreground.hwnd) { $activeHwnd = [int64]$Foreground.hwnd }
  }
  return [pscustomobject]@{
    schema = "cucp.observation/v1"
    kind = $Kind
    status = $Status
    collected_at = (Get-Date).ToString("o")
    elapsed_ms = $ElapsedMs
    sources = @($Sources)
    provenance = $Provenance
    observation_id = $ObservationId
    foreground = $Foreground
    active_hwnd = $activeHwnd
    focused_title = $fgTitle
    desktop = $Desktop
    windows = $Windows
    data = $Data
    cache = $Cache
    stale = $Stale
    confidence = $Confidence
    warnings = @($Warnings)
    recoverable_errors = @($RecoverableErrors)
    degraded_helper_empty = $DegradedHelperEmpty
  }
}

function _Get-DesktopSize {
  if (-not (_Ensure-Win32Loaded)) { return $null }
  try {
    Add-Type -AssemblyName System.Windows.Forms -ErrorAction SilentlyContinue
    $primary = [System.Windows.Forms.Screen]::PrimaryScreen
    if ($primary) {
      return [pscustomobject]@{
        width = [int]$primary.Bounds.Width
        height = [int]$primary.Bounds.Height
      }
    }
  } catch { }
  return $null
}

function Invoke-MacroWindows {
  # macro windows -- unified, read-only window enumeration.
  #
  # Sources:
  #   win32   : authoritative top-level enumeration via EnumWindows (deterministic)
  #   helper  : optional CUCP helper round-trip (--rich), adds app-id/role hints
  #
  # Failure semantics:
  #   - helper missing/empty + win32 has data => degraded_helper_empty=true,
  #     status remains "ok" because Win32 evidence is authoritative for foreground.
  #   - helper present + win32 empty (rare; secure desktop) => status="partial",
  #     recoverable_errors lists "helper_empty" or "no_visible_windows".
  #
  # Flags:
  #   --match <s>          case-insensitive substring of title/process
  #   --rich               also call helper `observe windows` for richer fields
  #   --include-hidden     include hidden/minimized windows
  #   --json-only          suppress brief output, JSON envelope only
  param([string[]]$Rest)
  $match = _Read-OptValue -Rest $Rest -Name "--match"
  $rich  = _Read-Switch  -Rest $Rest -Name "--rich"
  $hidden = _Read-Switch -Rest $Rest -Name "--include-hidden"
  $jsonOnly = _Read-Switch -Rest $Rest -Name "--json-only"

  $sw = [System.Diagnostics.Stopwatch]::StartNew()
  $win32 = _Enumerate-Win32Windows -Match $match
  if (-not $hidden) {
    $win32 = @($win32 | Where-Object { $_.visible -and -not $_.minimized })
  }
  $win32Ms = [int]$sw.Elapsed.TotalMilliseconds

  $helperItems = @()
  $helperOk = $null
  $helperMs = $null
  $helperReason = ""
  $sources = @("win32")
  if ($rich) {
    $h = [System.Diagnostics.Stopwatch]::StartNew()
    $argsRich = @("observe","windows")
    if ($match) { $argsRich += @("--match", $match) }
    $r = Invoke-Cucp -ArgList $argsRich -CaptureJson
    $h.Stop()
    $helperMs = [int]$h.Elapsed.TotalMilliseconds
    if ($r.ExitCode -eq 0 -and $r.Json -and $r.Json.status -eq "ok") {
      $helperOk = $true
      $art = $r.Json.artifacts | Where-Object { $_.type -eq "windows" } | Select-Object -First 1
      if ($art -and $art.items) { $helperItems = $art.items }
      $sources += "helper"
    } else {
      $helperOk = $false
      $statusStr = if ($r.Json) { "$($r.Json.status)" } else { "no-json" }
      $helperReason = "exit=$($r.ExitCode) status=$statusStr"
    }
  }

  # Foreground (Win32 authoritative)
  $foreground = $win32 | Where-Object { $_.foreground } | Select-Object -First 1
  $foregroundObj = $null
  if ($foreground) {
    $foregroundObj = [pscustomobject]@{
      title = $foreground.title
      hwnd = $foreground.hwnd
      pid = $foreground.pid
      process = $foreground.process
      class = $foreground.class
      rect = $foreground.rect
    }
  }

  # Build provenance + warnings + recovery hints
  $helperStatusStr = "skipped"
  if ($rich) {
    if ($helperOk) { $helperStatusStr = "ok" } else { $helperStatusStr = "degraded" }
  }
  $itemsSrcStr = "win32"
  if ($rich -and $helperItems.Count -gt 0) { $itemsSrcStr = "win32+helper" }
  $provenance = [pscustomobject]@{
    foreground = "win32"
    items = $itemsSrcStr
    helper_status = $helperStatusStr
  }

  $warnings = New-Object System.Collections.ArrayList
  $recoverable = New-Object System.Collections.ArrayList
  $degraded = $false
  $status = "ok"

  if ($rich -and $helperOk -eq $true -and $helperItems.Count -eq 0 -and $win32.Count -gt 0) {
    $degraded = $true
    [void]$warnings.Add("degraded_helper_empty: helper returned 0 windows but win32 sees $($win32.Count). Using win32 evidence.")
  }

  if ($rich -and $helperOk -eq $false) {
    [void]$warnings.Add("helper_unavailable: $helperReason. Using win32 only.")
    [void]$recoverable.Add([pscustomobject]@{
      code = "helper_unavailable"
      message = $helperReason
      recommended_action = "Run 'cucp macro ensure-helper' or proceed with win32-only enumeration."
    })
  }

  if ($win32.Count -eq 0) {
    if ($match) {
      $status = "partial"
      [void]$recoverable.Add([pscustomobject]@{
        code = "no_window"
        message = "no top-level visible window matches '$match'"
        recommended_action = "Verify the app is running, or call without --match to list everything, or use --include-hidden."
      })
    } else {
      $status = "partial"
      [void]$recoverable.Add([pscustomobject]@{
        code = "no_visible_windows"
        message = "no visible top-level windows found (locked/secure desktop?)"
        recommended_action = "Re-try after unlocking the workstation or use --include-hidden."
      })
    }
  }

  # Cache metadata: this macro doesn't read from cache itself but exposes shape
  # for downstream consumers. Indicate cold path.
  $cache = [pscustomobject]@{
    hit = $false
    age_ms = $null
    max_age_ms = 0
    key = if ($match) { "windows::match=$match" } else { "windows::all" }
    reason = "live_enumerate"
  }

  $envelope = _New-ObservationEnvelope `
    -Kind "windows" `
    -Status $status `
    -ElapsedMs $win32Ms `
    -Sources $sources `
    -Provenance $provenance `
    -Foreground $foregroundObj `
    -Windows $win32 `
    -Data ([pscustomobject]@{
      match = $match
      fast = (-not $rich)
      include_hidden = [bool]$hidden
      helper_elapsed_ms = $helperMs
      helper_ok = $helperOk
      helper_reason = $helperReason
      helper_count = $helperItems.Count
      helper_items = $helperItems
      count = $win32.Count
    }) `
    -Cache $cache `
    -Confidence "high" `
    -Warnings $warnings.ToArray() `
    -RecoverableErrors $recoverable.ToArray() `
    -DegradedHelperEmpty $degraded `
    -Desktop (_Get-DesktopSize)

  if ($Brief -and -not $jsonOnly) {
    $tag = if ($degraded) { "ok-fallback" } elseif ($status -ne "ok") { $status } else { "ok" }
    $fgT = if ($foregroundObj) { $foregroundObj.title } else { "" }
    [Console]::Out.WriteLine(("{0} windows count={1} foreground='{2}' sources={3} elapsed_ms={4}" -f `
      $tag, $win32.Count, $fgT, ($sources -join "+"), $win32Ms))
  } else {
    [Console]::Out.WriteLine(($envelope | ConvertTo-Json -Depth 8))
  }

  if ($status -eq "ok") { return 0 } elseif ($status -eq "partial") { return 2 } else { return 1 }
}

function Invoke-MacroFocusVerify {
  # macro focus-verify --name <substring> [--timeout-ms <n>]
  # Live macro: requests focus via wrapper "app switch" then verifies via
  # Win32 GetForegroundWindow. Returns ok only if foreground actually matches.
  # Reports clear partial/error evidence with recommended next step on mismatch.
  param([string[]]$Rest)
  $name = _Read-OptValue -Rest $Rest -Name "--name"
  $timeout = [int](_Read-OptValue -Rest $Rest -Name "--timeout-ms")
  if (-not $name) { throw "macro focus-verify requires --name" }
  if (-not $AllowLiveControl) { throw "macro focus-verify requires -AllowLiveControl" }
  if ($timeout -le 0) { $timeout = 3000 }

  $beforeFg = ""
  $bf = _Enumerate-Win32Windows -Match $null
  $bfWin = $bf | Where-Object { $_.foreground } | Select-Object -First 1
  if ($bfWin) { $beforeFg = $bfWin.title }

  $sw = [System.Diagnostics.Stopwatch]::StartNew()
  $focusWin = _Native-FocusWindow -Name $name
  $switchExit = if ($focusWin) { 0 } else { 1 }

  $needle = $name.ToLowerInvariant()
  $afterFg = ""
  $verified = $false
  $deadline = (Get-Date).AddMilliseconds($timeout)
  while ((Get-Date) -lt $deadline) {
    $cur = _Enumerate-Win32Windows -Match $null
    $win = $cur | Where-Object { $_.foreground } | Select-Object -First 1
    if ($win) {
      $afterFg = $win.title
      $tt = $afterFg.ToLowerInvariant()
      $pp = if ($win.process) { $win.process.ToLowerInvariant() } else { "" }
      if ($tt.IndexOf($needle) -ge 0 -or $pp.IndexOf($needle) -ge 0) {
        $verified = $true
        break
      }
    }
    Start-Sleep -Milliseconds 150
  }
  $sw.Stop()

  $status = if ($verified) { "ok" } else { "partial" }
  $reason = if ($verified) { "" } else { "foreground='$afterFg' did not match '$name'" }
  $next = ""
  if (-not $verified) {
    $candidates = _Enumerate-Win32Windows -Match $name
    if ($candidates.Count -gt 0) {
      $first = $candidates | Select-Object -First 1
      $next = "candidate window found pid=$($first.pid) title='$($first.title)'. Try `macro app-launch --name '$name'` if not yet running, or pass exact title fragment."
    } else {
      $next = "no window matches '$name'. Use `macro app-launch --name '$name'` or `macro windows --rich` to inspect."
    }
  }

  $payload = [pscustomobject]@{
    status = $status
    collected_at = (Get-Date).ToString("o")
    requested = $name
    before_foreground = $beforeFg
    after_foreground = $afterFg
    switch_exit = $switchExit
    verified = $verified
    elapsed_ms = [int]$sw.Elapsed.TotalMilliseconds
    timeout_ms = $timeout
    reason = $reason
    recommended_action = $next
  }

  if ($Brief) {
    if ($verified) {
      [Console]::Out.WriteLine(("ok focus-verify '{0}' foreground='{1}' elapsed_ms={2}" -f $name, $afterFg, [int]$sw.Elapsed.TotalMilliseconds))
    } else {
      [Console]::Out.WriteLine(("partial focus-verify '{0}' foreground='{1}' reason='{2}' elapsed_ms={3}" -f $name, $afterFg, $reason, [int]$sw.Elapsed.TotalMilliseconds))
    }
  } else {
    [Console]::Out.WriteLine(($payload | ConvertTo-Json -Depth 6))
  }

  if ($verified) { return 0 } else { return 2 }
}

function Invoke-MacroHealthQuick {param([string[]]$Rest) return _Invoke-LegacyDiagnosticFamily -Operation 'health-quick' -Rest $Rest}

function Invoke-MacroLogTail {param([string[]]$Rest) return _Invoke-LegacyDiagnosticFamily -Operation 'log-tail' -Rest $Rest}

function Invoke-MacroDiagnoseLag {param([string[]]$Rest) return _Invoke-LegacyDiagnosticFamily -Operation 'diagnose-lag' -Rest $Rest}

function Invoke-MacroCleanup {
  # macro cleanup --dry-run | --execute
  #     [--older-than-minutes <n>] [--keep-latest <n>] [--max-files <n>] [--max-mb <n>]
  #     [--include-trajectory] [--include-screenshots]
  #
  # Path safety: ONLY removes files inside the verified roots:
  #   $env:TEMP\computer-use-control-plane\wrapper-cache
  #   $env:TEMP\computer-use-control-plane\screenshots (only with --include-screenshots)
  # And only if their resolved full path is descendant of those roots and
  # the filename matches expected wrapper-emitted patterns:
  #   appshot-*.json, appshot-fresh-*.json, invoke-*.json, invoke-*.stderr.txt,
  #   *.png (under screenshots/ only), trajectory.ndjson.bak (only with --include-trajectory)
  #
  # Default policy: --older-than-minutes 30, --keep-latest 50.
  # Refuses to operate outside the verified root. CUCP temp folders are
  # NEVER touched (out of scope for this CUCP-only macro).
  param([string[]]$Rest)
  $execute = _Read-Switch -Rest $Rest -Name "--execute"
  $dryRun  = _Read-Switch -Rest $Rest -Name "--dry-run"
  $jsonOnly = _Read-Switch -Rest $Rest -Name "--json-only"
  $olderMin = [int](_Read-OptValue -Rest $Rest -Name "--older-than-minutes")
  $keepLatest = [int](_Read-OptValue -Rest $Rest -Name "--keep-latest")
  $maxFiles = [int](_Read-OptValue -Rest $Rest -Name "--max-files")
  $maxMb = [int](_Read-OptValue -Rest $Rest -Name "--max-mb")
  $includeTraj = _Read-Switch -Rest $Rest -Name "--include-trajectory"
  $includeShots = _Read-Switch -Rest $Rest -Name "--include-screenshots"

  if (-not $execute) { $dryRun = $true }   # default to dry-run
  if ($execute -and $dryRun) {
    Write-Notice -Level "ERROR" -Message "macro cleanup: --dry-run and --execute are mutually exclusive"
    return 1
  }
  if ($olderMin -le 0) { $olderMin = 30 }
  if ($keepLatest -lt 0) { $keepLatest = 50 }

  $auditRoot = $Script:AuditDir
  $cacheRoot = $Script:CacheDir
  $shotsRoot = Join-Path $auditRoot "screenshots"

  # Path-safety: roots must be inside %TEMP% and named "computer-use-control-plane*"
  $tempRoot = [System.IO.Path]::GetFullPath($env:TEMP)
  $auditFull = ""
  $cacheFull = ""
  try { $auditFull = [System.IO.Path]::GetFullPath($auditRoot) } catch { }
  try { $cacheFull = [System.IO.Path]::GetFullPath($cacheRoot) } catch { }
  $rootSafe = ($auditFull.StartsWith($tempRoot, [System.StringComparison]::OrdinalIgnoreCase) -and `
               $cacheFull.StartsWith($auditFull, [System.StringComparison]::OrdinalIgnoreCase) -and `
               (Split-Path -Leaf $auditFull) -like "computer-use-control-plane*")
  if (-not $rootSafe) {
    Write-Notice -Level "ERROR" -Message "macro cleanup: refused, paths failed safety check (audit=$auditFull cache=$cacheFull)"
    return 1
  }

  # Collect candidates: (path, length, lastWrite, group)
  $candidates = New-Object System.Collections.ArrayList
  if (Test-Path -LiteralPath $cacheRoot) {
    Get-ChildItem -LiteralPath $cacheRoot -File -ErrorAction SilentlyContinue | ForEach-Object {
      $name = $_.Name
      if ($name -like "appshot-*.json" -or $name -like "appshot-fresh-*.json" -or `
          $name -like "invoke-*.json" -or $name -like "invoke-*.stderr.txt") {
        [void]$candidates.Add([pscustomobject]@{
          group = "wrapper-cache"
          path = $_.FullName
          name = $name
          length = [int64]$_.Length
          last_write = $_.LastWriteTime
        })
      }
    }
  }
  if ($includeShots -and (Test-Path -LiteralPath $shotsRoot)) {
    Get-ChildItem -LiteralPath $shotsRoot -File -Filter "*.png" -ErrorAction SilentlyContinue | ForEach-Object {
      [void]$candidates.Add([pscustomobject]@{
        group = "screenshots"
        path = $_.FullName
        name = $_.Name
        length = [int64]$_.Length
        last_write = $_.LastWriteTime
      })
    }
  }
  if ($includeTraj) {
    $tj = Join-Path $auditRoot "trajectory.ndjson.bak"
    if (Test-Path -LiteralPath $tj) {
      $fi = Get-Item -LiteralPath $tj
      [void]$candidates.Add([pscustomobject]@{
        group = "trajectory-bak"
        path = $fi.FullName
        name = $fi.Name
        length = [int64]$fi.Length
        last_write = $fi.LastWriteTime
      })
    }
  }

  $cutoff = (Get-Date).AddMinutes(-1 * $olderMin)

  # Per-group: sort newest first, keep top N, mark eligible the rest IF older than cutoff
  $byGroup = @{}
  foreach ($c in $candidates) {
    if (-not $byGroup.ContainsKey($c.group)) { $byGroup[$c.group] = New-Object System.Collections.ArrayList }
    [void]$byGroup[$c.group].Add($c)
  }
  $eligible = New-Object System.Collections.ArrayList
  $kept = New-Object System.Collections.ArrayList
  foreach ($g in $byGroup.Keys) {
    $sorted = $byGroup[$g] | Sort-Object -Property last_write -Descending
    $idx = 0
    foreach ($c in $sorted) {
      if ($idx -lt $keepLatest) { [void]$kept.Add($c); $idx++; continue }
      if ($c.last_write -lt $cutoff) {
        [void]$eligible.Add($c)
      } else {
        [void]$kept.Add($c)
      }
      $idx++
    }
  }

  if ($maxFiles -gt 0 -and $eligible.Count -gt $maxFiles) {
    $eligible = $eligible | Sort-Object -Property last_write | Select-Object -First $maxFiles
  }
  if ($maxMb -gt 0) {
    $byteLimit = [int64]$maxMb * 1MB
    $running = [int64]0
    $bounded = New-Object System.Collections.ArrayList
    foreach ($c in ($eligible | Sort-Object -Property last_write)) {
      if ($running + $c.length -le $byteLimit) {
        [void]$bounded.Add($c)
        $running += $c.length
      }
    }
    $eligible = $bounded
  }

  $eligibleCount = ($eligible | Measure-Object).Count
  $eligibleBytes = ($eligible | Measure-Object -Property length -Sum).Sum
  if (-not $eligibleBytes) { $eligibleBytes = 0 }

  $deleted = 0
  $deletedBytes = [int64]0
  $errors = New-Object System.Collections.ArrayList
  if ($execute) {
    foreach ($c in $eligible) {
      # Final safety check: still inside cacheRoot or shotsRoot
      $full = ""
      try { $full = [System.IO.Path]::GetFullPath($c.path) } catch { continue }
      $okPath = ($full.StartsWith($cacheFull, [System.StringComparison]::OrdinalIgnoreCase) -or `
                 ($includeShots -and $full.StartsWith([System.IO.Path]::GetFullPath($shotsRoot), [System.StringComparison]::OrdinalIgnoreCase)) -or `
                 ($includeTraj  -and $full.StartsWith($auditFull, [System.StringComparison]::OrdinalIgnoreCase) -and (Split-Path -Leaf $full) -eq "trajectory.ndjson.bak"))
      if (-not $okPath) {
        [void]$errors.Add("skipped_unsafe_path: $full")
        continue
      }
      try {
        Remove-Item -LiteralPath $c.path -Force -ErrorAction Stop
        $deleted++
        $deletedBytes += $c.length
      } catch {
        [void]$errors.Add("$($c.path): $($_.Exception.Message)")
      }
    }
  }

  $payload = [pscustomobject]@{
    schema = "cucp.cleanup/v1"
    status = "ok"
    mode = if ($execute) { "execute" } else { "dry-run" }
    audit_root = $auditFull
    cache_root = $cacheFull
    older_than_minutes = $olderMin
    keep_latest_per_group = $keepLatest
    max_files = $maxFiles
    max_mb = $maxMb
    include_trajectory = [bool]$includeTraj
    include_screenshots = [bool]$includeShots
    candidate_count = ($candidates | Measure-Object).Count
    eligible_count = $eligibleCount
    eligible_bytes = $eligibleBytes
    kept_count = ($kept | Measure-Object).Count
    deleted_count = $deleted
    deleted_bytes = $deletedBytes
    errors = @($errors)
    sample_eligible = ($eligible | Select-Object -First 5 | ForEach-Object { $_.path })
  }

  if ($Brief -and -not $jsonOnly) {
    $tag = if ($execute) { "ok cleanup execute" } else { "ok cleanup dry-run" }
    [Console]::Out.WriteLine(("{0} candidates={1} eligible={2} eligible_mb={3} deleted={4} errors={5}" -f `
      $tag,
      ($candidates | Measure-Object).Count,
      $eligibleCount,
      [Math]::Round($eligibleBytes / 1MB, 1),
      $deleted,
      ($errors | Measure-Object).Count))
  } else {
    [Console]::Out.WriteLine(($payload | ConvertTo-Json -Depth 6))
  }
  if ($errors.Count -gt 0) { return 2 }
  return 0
}

function Invoke-MacroIconFind {param([string[]]$Rest) return _Invoke-LegacyInteractionFamily -Operation 'icon-find' -Rest $Rest -ScriptPath $PSCommandPath}

function Invoke-MacroIconClick {param([string[]]$Rest) return _Invoke-LegacyInteractionFamily -Operation 'icon-click' -Rest $Rest -ScriptPath $PSCommandPath}

function _Crop-Bitmap {
  # Internal helper: crop a PNG screenshot to a rect, save under cache dir,
  # return the new path. Used by vision-click-precise.
  param([string]$SourcePath, [int]$X, [int]$Y, [int]$W, [int]$H)
  if (-not (Test-Path -LiteralPath $SourcePath)) { return $null }
  try {
    Add-Type -AssemblyName System.Drawing -ErrorAction SilentlyContinue
    $src = [System.Drawing.Image]::FromFile($SourcePath)
    try {
      # Clamp rect to image bounds.
      $X = [Math]::Max(0, $X); $Y = [Math]::Max(0, $Y)
      if ($X + $W -gt $src.Width)  { $W = $src.Width  - $X }
      if ($Y + $H -gt $src.Height) { $H = $src.Height - $Y }
      if ($W -le 0 -or $H -le 0) { return $null }
      $rect = New-Object System.Drawing.Rectangle $X, $Y, $W, $H
      $bmp = New-Object System.Drawing.Bitmap $W, $H
      $g = [System.Drawing.Graphics]::FromImage($bmp)
      try {
        $g.DrawImage($src, (New-Object System.Drawing.Rectangle 0, 0, $W, $H), $rect, [System.Drawing.GraphicsUnit]::Pixel)
      } finally { $g.Dispose() }
      $cropDir = Join-Path $Script:CacheDir "vision-crops"
      if (-not (Test-Path -LiteralPath $cropDir)) { New-Item -ItemType Directory -Path $cropDir -Force | Out-Null }
      $cropPath = Join-Path $cropDir ("crop-" + [guid]::NewGuid().ToString("N") + ".png")
      $bmp.Save($cropPath, [System.Drawing.Imaging.ImageFormat]::Png)
      $bmp.Dispose()
      return [pscustomobject]@{ path = $cropPath; x = $X; y = $Y; w = $W; h = $H }
    } finally { $src.Dispose() }
  } catch {
    Write-WrapperLog -Message "crop failed: $($_.Exception.Message)"
    return $null
  }
}

function Invoke-MacroVisionClickPrecise {
  # macro vision-click-precise --describe <text> [--window <s>]
  #   [--crop-size <px>] [--verify-label <text>] [--verify-timeout-ms <n>]
  #
  # Two-stage vision pipeline for SMALL targets (toolbar icons, send arrows,
  # close [X], etc.) that single-shot vision-click misses:
  #
  #   Stage 1: full-screen vision -> approximate (x1, y1).
  #   Stage 2: crop a (crop_size x crop_size) tile centered on (x1, y1),
  #            re-run vision on the crop -> refined (rx, ry) within crop.
  #            Final coord = (x1 - crop/2 + rx, y1 - crop/2 + ry).
  #
  # This sharply improves accuracy on tiny UI without burning extra
  # full-screen screenshots.
  #
  # Live: gates on -AllowLiveControl. observation_id + --after enforced.
  param([string[]]$Rest)
  $description = _Read-OptValue -Rest $Rest -Name "--describe"
  $window = _Read-OptValue -Rest $Rest -Name "--window"
  $verifyLabel = _Read-OptValue -Rest $Rest -Name "--verify-label"
  $verifyTimeout = [int](_Read-OptValue -Rest $Rest -Name "--verify-timeout-ms")
  $cropSize = [int](_Read-OptValue -Rest $Rest -Name "--crop-size")
  $model = _Read-OptValue -Rest $Rest -Name "--model"
  if (-not $description) { throw "macro vision-click-precise requires --describe" }
  if (-not $AllowLiveControl) { throw "macro vision-click-precise requires -AllowLiveControl" }
  if ($verifyTimeout -le 0) { $verifyTimeout = 5000 }
  if ($cropSize -le 0) { $cropSize = 320 }

  $sw = [System.Diagnostics.Stopwatch]::StartNew()

  # Stage 1: full-screen vision via existing observe pipeline
  $shot = Invoke-Appshot -Match $window -Semantic:$true -NoCache
  if (-not $shot -or -not $shot.ScreenshotPath) {
    if ($Brief) { [Console]::Out.WriteLine("partial vision-click-precise stage1_screenshot_missing") }
    return 2
  }
  $screenshot = $shot.ScreenshotPath
  $stage1 = _Invoke-CodexVision -ScreenshotPath $screenshot -Description $description -TimeoutMs 60000 -Model $model
  if (-not $stage1 -or $stage1.status -ne "ok" -or -not $stage1.found) {
    if ($Brief) { [Console]::Out.WriteLine("partial vision-click-precise stage1_not_found") }
    return 2
  }
  $x1 = [int]$stage1.x
  $y1 = [int]$stage1.y

  # Stage 2: crop around (x1, y1) and re-run vision for refined coord
  $half = [int]($cropSize / 2)
  $crop = _Crop-Bitmap -SourcePath $screenshot -X ($x1 - $half) -Y ($y1 - $half) -W $cropSize -H $cropSize
  $finalX = $x1
  $finalY = $y1
  $stage2Used = $false
  if ($crop) {
    $stage2 = _Invoke-CodexVision -ScreenshotPath $crop.path -Description $description -TimeoutMs 60000 -Model $model
    if ($stage2 -and $stage2.status -eq "ok" -and $stage2.found) {
      $finalX = [int]$crop.x + [int]$stage2.x
      $finalY = [int]$crop.y + [int]$stage2.y
      $stage2Used = $true
    }
    # Cleanup crop file (keep small disk footprint)
    Remove-Item -LiteralPath $crop.path -Force -ErrorAction SilentlyContinue
  }

  # Click with --after using the screenshot's observation_id
  $args = @("act","click","--x","$finalX","--y","$finalY","--after",$shot.ObservationId)
  if ($window) { $args += @("--target-window", $window) }
  $r = Invoke-Cucp -ArgList $args

  # Optional verify
  $verifyOk = $true
  if ($r.ExitCode -eq 0 -and $verifyLabel) {
    $waitArgs = @("macro","wait-label","--label",$verifyLabel,"--timeout-ms","$verifyTimeout")
    if ($window) { $waitArgs += @("--window", $window) }
    $verifyExit = & $PSCommandPath @waitArgs
    $verifyOk = ($LASTEXITCODE -eq 0)
  }
  $sw.Stop()
  $elapsed = [int]$sw.Elapsed.TotalMilliseconds

  if ($Brief) {
    if ($r.ExitCode -eq 0 -and $verifyOk) {
      [Console]::Out.WriteLine(("ok vision-click-precise '{0}' stage1=({1},{2}) final=({3},{4}) crop_used={5} elapsed_ms={6}" -f `
        $description, $x1, $y1, $finalX, $finalY, $stage2Used, $elapsed))
    } else {
      [Console]::Out.WriteLine(("err vision-click-precise '{0}' click_exit={1} verify_ok={2}" -f $description, $r.ExitCode, $verifyOk))
    }
  } else {
    $payload = [pscustomobject]@{
      schema = "cucp.vision-click-precise/v1"
      status = if ($r.ExitCode -eq 0 -and $verifyOk) { "ok" } else { "partial" }
      describe = $description
      window = $window
      stage1 = [pscustomobject]@{ x = $x1; y = $y1; confidence = $stage1.confidence }
      stage2_used = $stage2Used
      crop_size = $cropSize
      final = [pscustomobject]@{ x = $finalX; y = $finalY }
      click_exit = $r.ExitCode
      verify_ok = $verifyOk
      elapsed_ms = $elapsed
    }
    [Console]::Out.WriteLine(($payload | ConvertTo-Json -Depth 6))
  }
  if ($r.ExitCode -ne 0) { return $r.ExitCode }
  if (-not $verifyOk) { return 2 }
  return 0
}

function Invoke-MacroPerf {param([string[]]$Rest) return _Invoke-LegacyDiagnosticFamily -Operation 'perf' -Rest $Rest}

function Invoke-MacroHealthDetail {param([string[]]$Rest) return _Invoke-LegacyDiagnosticFamily -Operation 'health-detail' -Rest $Rest}

# ============================================================================
# App Lifecycle macros (모든 앱 자유자재 운영)
# ============================================================================
# - app-launch: 앱을 어디서든 띄움 (PATH/Start Menu/등록경로/UWP appsfolder)
# - app-close:  PID 또는 이름으로 종료 (graceful → force)
# - with-app:   launch → wait-window → focus → 콜백 → close 라이프사이클
# ============================================================================

function _Resolve-AppPath {
  param([string]$Name)
  # 1) 직접 경로
  if (Test-Path -LiteralPath $Name) { return $Name }
  # 2) PATH에 있는 실행 파일
  $cmd = Get-Command $Name -ErrorAction SilentlyContinue | Where-Object { $_.CommandType -eq "Application" } | Select-Object -First 1
  if ($cmd -and $cmd.Source) { return $cmd.Source }
  # 3) 흔한 시스템 앱 alias
  $aliases = @{
    "notepad"     = "$env:WINDIR\System32\notepad.exe"
    "calc"        = "$env:WINDIR\System32\calc.exe"
    "calculator"  = "$env:WINDIR\System32\calc.exe"
    "explorer"    = "$env:WINDIR\explorer.exe"
    "cmd"         = "$env:WINDIR\System32\cmd.exe"
    "pwsh"        = "$env:WINDIR\System32\WindowsPowerShell\v1.0\powershell.exe"
    "edge"        = "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe"
    "chrome"      = "${env:ProgramFiles}\Google\Chrome\Application\chrome.exe"
    "메모장"      = "$env:WINDIR\System32\notepad.exe"
    "계산기"      = "$env:WINDIR\System32\calc.exe"
    "탐색기"      = "$env:WINDIR\explorer.exe"
  }
  $key = $Name.ToLowerInvariant()
  if ($aliases.ContainsKey($key)) {
    $p = $aliases[$key]
    if (Test-Path -LiteralPath $p) { return $p }
  }
  # 4) Windows App Paths registry (HKLM/HKCU)
  $appPaths = @(
    "HKLM:\Software\Microsoft\Windows\CurrentVersion\App Paths",
    "HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\App Paths",
    "HKCU:\Software\Microsoft\Windows\CurrentVersion\App Paths"
  )
  foreach ($root in $appPaths) {
    if (-not (Test-Path -LiteralPath $root)) { continue }
    $keys = Get-ChildItem -LiteralPath $root -ErrorAction SilentlyContinue |
      Where-Object { $_.PSChildName -match [regex]::Escape($Name) -or $_.PSChildName -eq ($Name + ".exe") }
    foreach ($k in $keys) {
      $val = (Get-ItemProperty -LiteralPath $k.PSPath -ErrorAction SilentlyContinue)."(default)"
      if ($val -and (Test-Path -LiteralPath $val)) { return $val }
    }
  }
  # 5) Start Menu shortcut search (.lnk in user/all-users)
  $shortcuts = @()
  $startMenuRoots = @(
    "$env:APPDATA\Microsoft\Windows\Start Menu\Programs",
    [Environment]::GetFolderPath("CommonPrograms")
  )
  foreach ($root in $startMenuRoots) {
    if (-not (Test-Path -LiteralPath $root)) { continue }
    $shortcuts += Get-ChildItem -LiteralPath $root -Recurse -Filter "*.lnk" -ErrorAction SilentlyContinue |
      Where-Object { $_.BaseName -match [regex]::Escape($Name) }
  }
  if ($shortcuts.Count -gt 0) {
    return $shortcuts[0].FullName
  }
  return $null
}

function Invoke-MacroAppLaunch {
  param([string[]]$Rest)
  $name = _Read-OptValue -Rest $Rest -Name "--name"
  $argstr = _Read-OptValue -Rest $Rest -Name "--args"
  $waitTitle = _Read-OptValue -Rest $Rest -Name "--wait-title"
  $waitTimeout = [int](_Read-OptValue -Rest $Rest -Name "--wait-timeout-ms")
  if (-not $name) { throw "macro app-launch requires --name" }
  if (-not $AllowLiveControl) { throw "macro app-launch requires -AllowLiveControl" }
  if ($waitTimeout -le 0) { $waitTimeout = 8000 }

  $resolved = _Resolve-AppPath -Name $name
  if (-not $resolved) {
    Write-Notice -Level "ERROR" -Message "앱 경로를 찾지 못했습니다: '$name' (PATH/Start Menu/registry/aliases 모두 검색)"
    if ($Brief) { [Console]::Out.WriteLine("err app-launch resolve-failed name='$name'") }
    return 1
  }

  Write-Notice -Level "INFO" -Message "앱 실행: '$name' -> '$resolved'"
  $proc = $null
  try {
    if ($resolved -match '\.lnk$') {
      # Use Shell to launch shortcut
      $proc = Start-Process -FilePath $resolved -PassThru -ErrorAction Stop
    } elseif ($argstr) {
      $proc = Start-Process -FilePath $resolved -ArgumentList $argstr -PassThru -ErrorAction Stop
    } else {
      $proc = Start-Process -FilePath $resolved -PassThru -ErrorAction Stop
    }
  } catch {
    Write-Notice -Level "ERROR" -Message "앱 실행 실패: $($_.Exception.Message)"
    if ($Brief) { [Console]::Out.WriteLine("err app-launch start-failed '$name'") }
    return 1
  }

  $pid_ = if ($proc) { $proc.Id } else { 0 }
  _Trajectory-Append -Kind "app_launch" -Payload @{
    name = $name
    resolved = $resolved
    pid_value = $pid_
  }

  # If --wait-title given, wait for that window to appear
  $titleSeen = $true
  if ($waitTitle) {
    Write-Notice -Level "INFO" -Message "윈도우 등장 대기: '$waitTitle' (timeout=${waitTimeout}ms)"
    $deadline = (Get-Date).AddMilliseconds($waitTimeout)
    $titleSeen = $false
    while ((Get-Date) -lt $deadline) {
      $r = Invoke-Cucp -ArgList @("observe", "windows", "--match", $waitTitle) -CaptureJson
      if ($r.Json -and $r.Json.status -eq "ok") {
        $items = ($r.Json.artifacts | Where-Object { $_.type -eq "windows" }).items
        if ((@($items)).Count -gt 0) { $titleSeen = $true; break }
      }
      Start-Sleep -Milliseconds 400
    }
  }

  if ($Brief) {
    if ($titleSeen) { [Console]::Out.WriteLine("ok app-launch '$name' pid=$pid_ resolved='$resolved'") }
    else { [Console]::Out.WriteLine("err app-launch wait-title-timeout '$waitTitle' pid=$pid_") }
  } else {
    [Console]::Out.WriteLine(([pscustomobject]@{
      status = if ($titleSeen) { "ok" } else { "title_timeout" }
      name = $name
      resolved = $resolved
      pid = $pid_
      title_seen = $titleSeen
      wait_title = $waitTitle
    } | ConvertTo-Json))
  }
  if ($titleSeen) { return 0 } else { return 2 }
}

function Invoke-MacroAppClose {
  param([string[]]$Rest)
  $name = _Read-OptValue -Rest $Rest -Name "--name"
  $pidArg = [int](_Read-OptValue -Rest $Rest -Name "--pid")
  $force = _Read-Switch -Rest $Rest -Name "--force"
  if (-not $name -and $pidArg -le 0) { throw "macro app-close requires --name or --pid" }
  if (-not $AllowLiveControl) { throw "macro app-close requires -AllowLiveControl" }

  $targets = @()
  if ($pidArg -gt 0) {
    $p = Get-Process -Id $pidArg -ErrorAction SilentlyContinue
    if ($p) { $targets += $p }
  } elseif ($name) {
    # Strip .exe if present
    $procName = $name -replace '\.exe$',''
    $targets = @(Get-Process -Name $procName -ErrorAction SilentlyContinue)
  }

  if ((@($targets)).Count -eq 0) {
    if ($Brief) { [Console]::Out.WriteLine("err app-close not_running name='$name' pid=$pidArg") }
    return 1
  }

  $closed = 0
  foreach ($t in $targets) {
    try {
      if ($force) {
        $t.Kill()
        $closed++
      } else {
        # Never turn a bounded graceful-close wait into an implicit kill.
        if ($t.MainWindowHandle -and $t.MainWindowHandle -ne 0) {
          if ($t.CloseMainWindow()) {
            [void]$t.WaitForExit(2000)
            if ($t.HasExited) { $closed++ }
          }
        }

      }
    } catch { }
  }

  _Trajectory-Append -Kind "app_close" -Payload @{
    name = $name
    pid_value = $pidArg
    closed = $closed
    force = [bool]$force
  }

  if ($Brief) { [Console]::Out.WriteLine("ok app-close closed=$closed name='$name'") }
  if ($closed -gt 0) { return 0 } else { return 1 }
}

function Invoke-MacroWithApp {
  param([string[]]$Rest)
  $name = _Read-OptValue -Rest $Rest -Name "--name"
  $waitTitle = _Read-OptValue -Rest $Rest -Name "--wait-title"
  $waitTimeout = [int](_Read-OptValue -Rest $Rest -Name "--wait-timeout-ms")
  $hold = [int](_Read-OptValue -Rest $Rest -Name "--hold-ms")
  $closeAfter = _Read-Switch -Rest $Rest -Name "--close-after"
  $force = _Read-Switch -Rest $Rest -Name "--force"
  if (-not $name) { throw "macro with-app requires --name" }
  if (-not $AllowLiveControl) { throw "macro with-app requires -AllowLiveControl" }
  if ($waitTimeout -le 0) { $waitTimeout = 8000 }
  if ($hold -le 0) { $hold = 1500 }

  # 1) Launch directly (so we get the PID back)
  $resolved = _Resolve-AppPath -Name $name
  if (-not $resolved) {
    Write-Notice -Level "ERROR" -Message "with-app: 앱 경로 없음 '$name'"
    if ($Brief) { [Console]::Out.WriteLine("err with-app resolve-failed '$name'") }
    return 1
  }
  $proc = $null
  try {
    if ($resolved -match '\.lnk$') { $proc = Start-Process -FilePath $resolved -PassThru -ErrorAction Stop }
    else { $proc = Start-Process -FilePath $resolved -PassThru -ErrorAction Stop }
  } catch {
    if ($Brief) { [Console]::Out.WriteLine("err with-app start-failed '$name'") }
    return 1
  }
  $launchPid = if ($proc) { $proc.Id } else { 0 }

  # 2) Wait for window. On Win11 some apps (Notepad, Calculator, Settings)
  # are "launcher" processes that exit immediately and a different PID owns
  # the actual window. We re-locate the owning PID via window observation.
  $titleSeen = $true
  $ownerPid = $launchPid
  if ($waitTitle) {
    $deadline = (Get-Date).AddMilliseconds($waitTimeout)
    $titleSeen = $false
    while ((Get-Date) -lt $deadline) {
      $r = Invoke-Cucp -ArgList @("observe", "windows", "--match", $waitTitle) -CaptureJson
      if ($r.Json -and $r.Json.status -eq "ok") {
        $items = ($r.Json.artifacts | Where-Object { $_.type -eq "windows" }).items
        if ((@($items)).Count -gt 0) {
          $titleSeen = $true
          # Prefer the owner PID reported by the helper (CUCP windows artifact)
          $first = $items | Select-Object -First 1
          if ($first.pid) {
            $ownerPid = [int]$first.pid
          }
          break
        }
      }
      Start-Sleep -Milliseconds 400
    }
  }

  Start-Sleep -Milliseconds $hold

  # 3) Close: try by launchPid first, then by name fallback (UWP/wrapper apps)
  $closeOk = $true
  if ($closeAfter) {
    $closed = $false
    # By PID (use the window-owning PID, not the launcher's)
    try {
      $p = Get-Process -Id $ownerPid -ErrorAction SilentlyContinue
      if ($p -and -not $p.HasExited) {
        if ($force) { $p.Kill() } else {
          if ($p.MainWindowHandle -and $p.MainWindowHandle -ne 0) {
            $p.CloseMainWindow() | Out-Null
            Start-Sleep -Milliseconds 1500
            $p.Refresh()
            if (-not $p.HasExited) { $p.Kill() }
          } else { $p.Kill() }
        }
        Start-Sleep -Milliseconds 500
        $check = Get-Process -Id $ownerPid -ErrorAction SilentlyContinue
        if (-not $check -or $check.HasExited) { $closed = $true }
      } elseif ($p -and $p.HasExited) {
        # launcher already gone (UWP pattern)
        $closed = $false  # need name fallback
      }
    } catch { }
    # Name fallback (UWP shells where launcher exits and another process owns the window)
    if (-not $closed) {
      $procName = $name -replace '\.exe$',''
      $extra = @(Get-Process -Name $procName -ErrorAction SilentlyContinue)
      $killedAny = $false
      foreach ($x in $extra) {
        try {
          if ($force -or -not $x.MainWindowHandle -or $x.MainWindowHandle -eq 0) {
            $x.Kill()
          } else {
            $x.CloseMainWindow() | Out-Null
            Start-Sleep -Milliseconds 1500
            $x.Refresh()
            if (-not $x.HasExited) { $x.Kill() }
          }
          Start-Sleep -Milliseconds 300
          $check = Get-Process -Id $x.Id -ErrorAction SilentlyContinue
          if (-not $check -or $check.HasExited) { $killedAny = $true }
        } catch { }
      }
      if ($killedAny) { $closed = $true }
    }
    $closeOk = $closed
  }

  _Trajectory-Append -Kind "with_app" -Payload @{
    name = $name
    launch_pid = $launchPid
    owner_pid = $ownerPid
    title_seen = $titleSeen
    close_after = [bool]$closeAfter
    closed = $closeOk
  }

  if ($Brief) {
    if ($titleSeen -and $closeOk) { [Console]::Out.WriteLine("ok with-app '$name' launch_pid=$launchPid owner_pid=$ownerPid title_seen=$titleSeen close=$closeOk") }
    elseif (-not $titleSeen) { [Console]::Out.WriteLine("err with-app title-timeout '$waitTitle' pid=$launchPid") }
    else { [Console]::Out.WriteLine("err with-app close-failed launch_pid=$launchPid owner_pid=$ownerPid") }
  }
  if ($titleSeen -and $closeOk) { return 0 } else { return 2 }
}

# ============================================================================
# Click + verify (변화 감지 자가 검증)
# ============================================================================

function _Compute-ImageHash {
  param([string]$Path)
  if (-not (Test-Path -LiteralPath $Path)) { return $null }
  try {
    $bytes = [System.IO.File]::ReadAllBytes($Path)
    $hasher = [System.Security.Cryptography.SHA256]::Create()
    $hash = $hasher.ComputeHash($bytes)
    return ($hash | ForEach-Object { $_.ToString("x2") }) -join ""
  } catch { return $null }
}

function Invoke-MacroClickAndVerify {
  param([string[]]$Rest)
  $label = _Read-OptValue -Rest $Rest -Name "--label"
  $window = _Read-OptValue -Rest $Rest -Name "--window"
  $verifyLabel = _Read-OptValue -Rest $Rest -Name "--verify-label"
  $verifyTimeout = [int](_Read-OptValue -Rest $Rest -Name "--verify-timeout-ms")
  $waitChangeMs = [int](_Read-OptValue -Rest $Rest -Name "--wait-change-ms")
  if (-not $label) { throw "macro click-and-verify requires --label" }
  if (-not $AllowLiveControl) { throw "macro click-and-verify requires -AllowLiveControl" }
  if ($verifyTimeout -le 0) { $verifyTimeout = 5000 }
  if ($waitChangeMs -le 0) { $waitChangeMs = 1500 }

  # 1) Pre-click screenshot for change detection
  $preDir = _Get-VisionWorkDir
  $prePath = Join-Path $preDir ("pre-" + (Get-Date).ToString("yyyyMMddHHmmssfff") + ".png")
  $preArgs = @("observe", "screenshot", "--out", $prePath)
  Invoke-Cucp -ArgList $preArgs -CaptureJson | Out-Null
  $preHash = _Compute-ImageHash -Path $prePath

  # 2) Click via existing click-label macro
  $clickArgs = @("macro", "click-label", "--label", $label)
  if ($window) { $clickArgs += @("--window", $window) }
  $r = Invoke-Cucp -ArgList $clickArgs
  if ($r.ExitCode -ne 0) {
    if ($Brief) { [Console]::Out.WriteLine("err click-and-verify click-failed exit=$($r.ExitCode)") }
    return $r.ExitCode
  }

  # 3) Post-click screenshot - wait for visual change
  Start-Sleep -Milliseconds $waitChangeMs
  $postPath = Join-Path $preDir ("post-" + (Get-Date).ToString("yyyyMMddHHmmssfff") + ".png")
  $postArgs = @("observe", "screenshot", "--out", $postPath)
  Invoke-Cucp -ArgList $postArgs -CaptureJson | Out-Null
  $postHash = _Compute-ImageHash -Path $postPath

  $screenChanged = ($preHash -ne $null -and $postHash -ne $null -and $preHash -ne $postHash)

  # 4) Optional label verification
  $labelVerified = $true
  if ($verifyLabel) {
    $waitArgs = @("macro", "wait-label", "--label", $verifyLabel, "--timeout-ms", "$verifyTimeout")
    if ($window) { $waitArgs += @("--window", $window) }
    $vr = Invoke-Cucp -ArgList $waitArgs
    $labelVerified = ($vr.ExitCode -eq 0)
  }

  _Trajectory-Append -Kind "click_verify" -Payload @{
    label = $label
    window = $window
    screen_changed = $screenChanged
    label_verified = $labelVerified
    pre_hash = $preHash
    post_hash = $postHash
  }

  if ($Brief) {
    if ($screenChanged -and $labelVerified) {
      [Console]::Out.WriteLine("ok click-and-verify '$label' changed=true verified=true")
    } elseif (-not $screenChanged) {
      [Console]::Out.WriteLine("err click-and-verify '$label' no-screen-change")
    } else {
      [Console]::Out.WriteLine("err click-and-verify '$label' label-not-found '$verifyLabel'")
    }
  }
  if ($screenChanged -and $labelVerified) { return 0 } else { return 2 }
}

# ============================================================================
# Native helper 직통 매크로 — 외부 helper / cli.mjs 없이 동작
# ============================================================================
# 이 그룹은 cucp-native-helper.ps1 (Win32 + UIA + Screenshot 직접 호출)을
# child PowerShell로 띄워 결과 JSON을 그대로 stdout으로 토해냅니다.
# windows-mcp / Codex helper / cli.mjs 모두 없어도 동작하는 기본 표면입니다.
#
# - native-health      : helper 자체 health
# - native-windows     : 윈도우 enum (-Match 옵션)
# - native-screenshot  : 전체/영역 PNG 캡처
# - click-point        : 좌표 기반 클릭 (-AllowLiveControl 필요)
# - type-native        : 유니코드 텍스트 입력 (-AllowLiveControl 필요)
# - shortcut-native    : 단축키 (예: ctrl+s)
# - uia-click-label    : UIA tree에서 라벨 찾아 클릭 (-AllowLiveControl 필요)
#
# 모든 actuation 매크로는 -AllowLiveControl 게이트 통과해야 함.
# ============================================================================

function Invoke-MacroNativeHealth {
  param([string[]]$Rest)
  $r = Invoke-NativeHelper -ArgList @("-Action","health")
  if ($Brief) {
    if ($r.Json -and $r.Json.status -eq "ok") {
      $ocrLangs = ""
      if ($r.Json.ocr_languages) { $ocrLangs = ($r.Json.ocr_languages -join ',') }
      [Console]::Out.WriteLine("ok native-health win32=$($r.Json.win32) uia=$($r.Json.uia) ocr=$($r.Json.ocr) ocr_languages=$ocrLangs elapsed_ms=$($r.ElapsedMs)")
    } else {
      [Console]::Out.WriteLine("err native-health helper_unavailable raw=" + $r.Err)
    }
  } else {
    if ($r.Raw) { [Console]::Out.Write($r.Raw) }
  }
  if ($r.Json -and $r.Json.status -eq "ok") { return 0 }
  return 1
}

function Invoke-MacroNativeWindows {
  param([string[]]$Rest)
  $match = _Read-OptValue -Rest $Rest -Name "--match"
  $args = @("-Action","windows")
  if ($match) { $args += @("-Match", $match) }
  $r = Invoke-NativeHelper -ArgList $args
  if ($Brief) {
    if ($r.Json -and $r.Json.status -eq "ok") {
      [Console]::Out.WriteLine("ok native-windows count=$($r.Json.count) elapsed_ms=$($r.ElapsedMs)")
    } else {
      [Console]::Out.WriteLine("err native-windows helper_failed")
    }
  } else {
    if ($r.Raw) { [Console]::Out.Write($r.Raw) }
  }
  return $r.ExitCode
}

function Invoke-MacroNativeScreenshot {
  param([string[]]$Rest)
  # --out-path / --out 둘 다 지원 (PowerShell의 -Out partial match 회피)
  $out = _Read-OptValue -Rest $Rest -Name "--out-path"
  if (-not $out) { $out = _Read-OptValue -Rest $Rest -Name "--out" }
  if (-not $out) {
    $out = Join-Path $Script:CacheDir ("native-shot-" + (Get-Date).ToString("yyyyMMdd-HHmmss-fff") + ".png")
  }
  $args = @("-Action","screenshot","-OutPath",$out)
  $regionX = _Read-OptValue -Rest $Rest -Name "--x"
  $regionY = _Read-OptValue -Rest $Rest -Name "--y"
  $regionW = _Read-OptValue -Rest $Rest -Name "--width"
  $regionH = _Read-OptValue -Rest $Rest -Name "--height"
  if ($regionX) { $args += @("-ScreenshotX", $regionX) }
  if ($regionY) { $args += @("-ScreenshotY", $regionY) }
  if ($regionW) { $args += @("-ScreenshotW", $regionW) }
  if ($regionH) { $args += @("-ScreenshotH", $regionH) }
  $r = Invoke-NativeHelper -ArgList $args
  if ($Brief) {
    if ($r.Json -and $r.Json.status -eq "ok") {
      [Console]::Out.WriteLine("ok native-screenshot path='$($r.Json.out_path)' bytes=$($r.Json.bytes) elapsed_ms=$($r.ElapsedMs)")
    } else {
      [Console]::Out.WriteLine("err native-screenshot")
    }
  } else {
    if ($r.Raw) { [Console]::Out.Write($r.Raw) }
  }
  return $r.ExitCode
}

function Invoke-MacroClickPoint {param([string[]]$Rest) return _Invoke-LegacyInteractionFamily -Operation 'click-point' -Rest $Rest -ScriptPath $PSCommandPath}

function Invoke-MacroTypeNative {
  # macro type-native --text <s> [--clear] [--enter]
  # 유니코드 텍스트 입력 (한글/이모지 OK). -AllowLiveControl 필수.
  param([string[]]$Rest)
  if (-not $AllowLiveControl) { throw "macro type-native requires -AllowLiveControl" }
  $text = _Read-OptValue -Rest $Rest -Name "--text"
  $clear = _Read-Switch -Rest $Rest -Name "--clear"
  $enter = _Read-Switch -Rest $Rest -Name "--enter"
  if (-not $text -and -not $clear -and -not $enter) { throw "macro type-native requires --text or --clear or --enter" }
  $args = @("-Action","type")
  if ($text)  { $args += @("-Text", $text) }
  if ($clear) { $args += "-ClearFirst" }
  if ($enter) { $args += "-PressEnter" }
  $r = Invoke-NativeHelper -ArgList $args
  if ($Brief) {
    if ($r.Json -and $r.Json.status -eq "ok") {
      [Console]::Out.WriteLine("ok type-native length=$($text.Length) clear=$clear enter=$enter elapsed_ms=$($r.ElapsedMs)")
    } else {
      [Console]::Out.WriteLine("err type-native exit=$($r.ExitCode)")
    }
  } else {
    if ($r.Raw) { [Console]::Out.Write($r.Raw) }
  }
  return $r.ExitCode
}

function Invoke-MacroShortcutNative {
  # macro shortcut-native --keys "ctrl+s"
  # 단축키 (외부 helper 없이). -AllowLiveControl 필수.
  param([string[]]$Rest)
  if (-not $AllowLiveControl) { throw "macro shortcut-native requires -AllowLiveControl" }
  $keys = _Read-OptValue -Rest $Rest -Name "--keys"
  if (-not $keys) { throw "macro shortcut-native requires --keys" }
  $r = Invoke-NativeHelper -ArgList @("-Action","shortcut","-Keys",$keys)
  if ($Brief) {
    if ($r.Json -and $r.Json.status -eq "ok") {
      [Console]::Out.WriteLine("ok shortcut-native keys='$keys' elapsed_ms=$($r.ElapsedMs)")
    } else {
      [Console]::Out.WriteLine("err shortcut-native exit=$($r.ExitCode)")
    }
  } else {
    if ($r.Raw) { [Console]::Out.Write($r.Raw) }
  }
  return $r.ExitCode
}

function Invoke-MacroUiaClickLabel {
  # macro uia-click-label --label <text> [--match <window>] [--role <role>] [--button left|right|double]
  # UIA BoundingRectangle 기반 결정론적 클릭. 외부 helper 의존 없음.
  param([string[]]$Rest)
  if (-not $AllowLiveControl) { throw "macro uia-click-label requires -AllowLiveControl" }
  $label = _Read-OptValue -Rest $Rest -Name "--label"
  $match = _Read-OptValue -Rest $Rest -Name "--match"
  $role  = _Read-OptValue -Rest $Rest -Name "--role"
  $btn   = _Read-OptValue -Rest $Rest -Name "--button"
  if (-not $btn) { $btn = "left" }
  if (-not $label) { throw "macro uia-click-label requires --label" }

  $args = @("-Action","uia-click","-Label",$label,"-Button",$btn)
  if ($match) { $args += @("-Match", $match) }
  if ($role)  { $args += @("-Role", $role) }
  $r = Invoke-NativeHelper -ArgList $args
  _Trajectory-Append -Kind "click" -Payload @{
    label = $label
    source = "native_uia_click_label"
    button = $btn
    exit = $r.ExitCode
  }
  if ($Brief) {
    if ($r.Json -and $r.Json.status -eq "ok") {
      [Console]::Out.WriteLine("ok uia-click-label '$label' @($($r.Json.x),$($r.Json.y)) matched='$($r.Json.matched_text)' elapsed_ms=$($r.ElapsedMs)")
    } else {
      $reason = ""
      if ($r.Json -and $r.Json.reason) { $reason = $r.Json.reason }
      [Console]::Out.WriteLine("err uia-click-label '$label' exit=$($r.ExitCode) reason=$reason")
    }
  } else {
    if ($r.Raw) { [Console]::Out.Write($r.Raw) }
  }
  return $r.ExitCode
}

# ============================================================================
# UIA Pattern 직접 호출 매크로 — 마우스 안 움직이는 클릭
# ============================================================================
# `uia-invoke`: InvokePattern으로 버튼 누름 (마우스 이동 없음, 화면 가려져도 OK)
# `uia-set-value`: ValuePattern으로 Edit/ComboBox에 값 즉시 설정 (IME 안 거침)
# `uia-toggle`: TogglePattern으로 체크박스/라디오 상태 전환
#
# 모두 -AllowLiveControl 필수. UIA Pattern 미지원 시 partial(2) 반환
# (좌표 fallback 자동 안 함 — 명시적으로 click-point 사용해야 함).
# ============================================================================

function Invoke-MacroUiaInvoke {
  param([string[]]$Rest)
  if (-not $AllowLiveControl) { throw "macro uia-invoke requires -AllowLiveControl" }
  $label = _Read-OptValue -Rest $Rest -Name "--label"
  $match = _Read-OptValue -Rest $Rest -Name "--match"
  $role  = _Read-OptValue -Rest $Rest -Name "--role"
  if (-not $label) { throw "macro uia-invoke requires --label" }

  $args = @("-Action","uia-invoke","-Label",$label)
  if ($match) { $args += @("-Match", $match) }
  if ($role)  { $args += @("-Role", $role) }
  $r = Invoke-NativeHelper -ArgList $args
  _Trajectory-Append -Kind "click" -Payload @{
    label = $label
    source = "native_uia_invoke"
    method = if ($r.Json) { "$($r.Json.method)" } else { "" }
    mouse_moved = if ($r.Json) { [bool]$r.Json.mouse_moved } else { $true }
    exit = $r.ExitCode
  }
  if ($Brief) {
    if ($r.Json -and $r.Json.status -eq "ok") {
      [Console]::Out.WriteLine("ok uia-invoke '$label' method=$($r.Json.method) mouse_moved=$($r.Json.mouse_moved) elapsed_ms=$($r.ElapsedMs)")
    } else {
      $reason = if ($r.Json -and $r.Json.reason) { $r.Json.reason } else { "" }
      [Console]::Out.WriteLine("partial uia-invoke '$label' reason=$reason exit=$($r.ExitCode)")
    }
  } else {
    if ($r.Raw) { [Console]::Out.Write($r.Raw) }
  }
  return $r.ExitCode
}

function Invoke-MacroUiaSetValue {
  param([string[]]$Rest)
  if (-not $AllowLiveControl) { throw "macro uia-set-value requires -AllowLiveControl" }
  $label = _Read-OptValue -Rest $Rest -Name "--label"
  $value = _Read-OptValue -Rest $Rest -Name "--value"
  $match = _Read-OptValue -Rest $Rest -Name "--match"
  $role  = _Read-OptValue -Rest $Rest -Name "--role"
  if (-not $label) { throw "macro uia-set-value requires --label" }
  if ($null -eq $value) { throw "macro uia-set-value requires --value" }

  $args = @("-Action","uia-set-value","-Label",$label,"-Value",$value)
  if ($match) { $args += @("-Match", $match) }
  if ($role)  { $args += @("-Role", $role) }
  $r = Invoke-NativeHelper -ArgList $args
  if ($Brief) {
    if ($r.Json -and $r.Json.status -eq "ok") {
      [Console]::Out.WriteLine("ok uia-set-value '$label' length=$($r.Json.value_length) keyboard_used=$($r.Json.keyboard_used) elapsed_ms=$($r.ElapsedMs)")
    } else {
      $reason = if ($r.Json -and $r.Json.reason) { $r.Json.reason } else { "" }
      [Console]::Out.WriteLine("partial uia-set-value '$label' reason=$reason exit=$($r.ExitCode)")
    }
  } else {
    if ($r.Raw) { [Console]::Out.Write($r.Raw) }
  }
  return $r.ExitCode
}

function Invoke-MacroUiaToggle {
  param([string[]]$Rest)
  if (-not $AllowLiveControl) { throw "macro uia-toggle requires -AllowLiveControl" }
  $label = _Read-OptValue -Rest $Rest -Name "--label"
  $match = _Read-OptValue -Rest $Rest -Name "--match"
  $role  = _Read-OptValue -Rest $Rest -Name "--role"
  if (-not $label) { throw "macro uia-toggle requires --label" }

  $args = @("-Action","uia-toggle","-Label",$label)
  if ($match) { $args += @("-Match", $match) }
  if ($role)  { $args += @("-Role", $role) }
  $r = Invoke-NativeHelper -ArgList $args
  if ($Brief) {
    if ($r.Json -and $r.Json.status -eq "ok") {
      [Console]::Out.WriteLine("ok uia-toggle '$label' previous=$($r.Json.previous_state) elapsed_ms=$($r.ElapsedMs)")
    } else {
      $reason = if ($r.Json -and $r.Json.reason) { $r.Json.reason } else { "" }
      [Console]::Out.WriteLine("partial uia-toggle '$label' reason=$reason exit=$($r.ExitCode)")
    }
  } else {
    if ($r.Raw) { [Console]::Out.Write($r.Raw) }
  }
  return $r.ExitCode
}

# ============================================================================
# v1.2.0 — hit-test 가드 + safe-type
# ============================================================================
# 라이브 검증에서 발견된 두 사고 ((a) 코드 에디터 의도치 않은 입력, (b) Electron app 전체화면
# → 창모드 변경) 의 본질은 "좌표 클릭 직전 검증 부재". v1.2.0 은 좌표가 의도한
# 윈도우 안인지 Win32 WindowFromPoint 로 검증 + 입력 후 OCR probe 로 진짜 들어갔는지
# 확인하는 안전망 추가.
# ============================================================================

# macro hit-test --x N --y N [--target-match Electron app | --target-hwnd N]
# 좌표가 어떤 윈도우 안인지 확인 (read-only, 클릭 안 함)
function Invoke-MacroHitTest {
  param([string[]]$Rest)
  $x = [int](_Read-OptValue -Rest $Rest -Name "--x")
  $y = [int](_Read-OptValue -Rest $Rest -Name "--y")
  $tm = _Read-OptValue -Rest $Rest -Name "--target-match"
  $th = [int](_Read-OptValue -Rest $Rest -Name "--target-hwnd")
  $clickInset = [int](_Read-OptValue -Rest $Rest -Name "--click-inset")
  $fast = _Read-Switch -Rest $Rest -Name "--fast"
  $noUia = _Read-Switch -Rest $Rest -Name "--no-uia"
  if ($x -le 0 -or $y -le 0) { throw "macro hit-test requires --x and --y" }
  if ($clickInset -le 0) { $clickInset = 3 }

  if ($fast) {
    $swFast = [System.Diagnostics.Stopwatch]::StartNew()
    $fastPayload = _Native-HitTestPoint -X $x -Y $y -TargetHwnd $th -TargetMatch $tm
    $swFast.Stop()
    $fastPayload | Add-Member -NotePropertyName elapsed_ms -NotePropertyValue ([int]$swFast.Elapsed.TotalMilliseconds) -Force
    $exitCode = 0
    if ($fastPayload.status -eq "partial") { $exitCode = 2 }
    if ($Brief) {
      $tag = "ok"
      if ($fastPayload.status -eq "partial") { $tag = "partial" }
      [Console]::Out.WriteLine("$tag hit-test @($x,$y) hwnd=$($fastPayload.root_hwnd) title='$($fastPayload.root_title)' process=$($fastPayload.process_name) matched=$($fastPayload.matched) reason=$($fastPayload.match_reason) uia=skipped source=wrapper_fast elapsed_ms=$($fastPayload.elapsed_ms)")
    } else {
      [Console]::Out.WriteLine(($fastPayload | ConvertTo-Json -Depth 8))
    }
    return $exitCode
  }

  $argList = @("-Action","hit-test","-X","$x","-Y","$y")
  if ($tm) { $argList += @("-TargetMatch", $tm) }
  if ($th -gt 0) { $argList += @("-TargetHwnd", "$th") }
  $argList += @("-ClickInset", "$clickInset")
  if ($fast -or $noUia) { $argList += "-SkipUia" }
  $r = Invoke-NativeHelper -ArgList $argList
  $exitCode = [int]$r.ExitCode

  if ($Brief) {
    if ($r.Json) {
      $tag = "ok"
      if ($r.Json.status -eq "partial") { $tag = "partial" }
      $uiaSuffix = ""
      if ($r.Json.uia_point) {
        $uiaSuffix = " uia_refine=($($r.Json.uia_point.refined_x),$($r.Json.uia_point.refined_y)) role='$($r.Json.uia_point.role)' score=$($r.Json.uia_point.score) source=$($r.Json.uia_point.point_source)"
      } elseif ($r.Json.uia_skipped) {
        $uiaSuffix = " uia=skipped"
      }
      [Console]::Out.WriteLine("$tag hit-test @($x,$y) hwnd=$($r.Json.root_hwnd) title='$($r.Json.root_title)' process=$($r.Json.process_name) matched=$($r.Json.matched) reason=$($r.Json.match_reason)$uiaSuffix")
    } else {
      [Console]::Out.WriteLine("err hit-test @($x,$y) helper_failed exit=$exitCode")
    }
  } else {
    if ($r.Raw) { [Console]::Out.Write($r.Raw) }
  }
  return $exitCode
}

function Invoke-MacroHitTestBatch {
  param([string[]]$Rest)
  $pointSpecs = New-Object System.Collections.ArrayList
  $pointsRaw = _Read-OptValue -Rest $Rest -Name "--points"
  foreach ($p in @(_Read-AllOptValues -Rest $Rest -Name "--point")) { [void]$pointSpecs.Add($p) }
  if ($pointsRaw) {
    foreach ($p in @($pointsRaw -split ';')) {
      if ("$p".Trim()) { [void]$pointSpecs.Add($p) }
    }
  }
  $tm = _Read-OptValue -Rest $Rest -Name "--target-match"
  $th = [int](_Read-OptValue -Rest $Rest -Name "--target-hwnd")
  $maxPoints = [int](_Read-OptValue -Rest $Rest -Name "--max-points")
  if ($maxPoints -le 0) { $maxPoints = 200 }
  if ($pointSpecs.Count -eq 0) { throw "macro hit-test-batch requires --point `"x,y`" or --points `"x,y;x,y`"" }
  if ($pointSpecs.Count -gt $maxPoints) { throw "macro hit-test-batch point count exceeds --max-points ($maxPoints)" }

  $sw = [System.Diagnostics.Stopwatch]::StartNew()
  $results = New-Object System.Collections.ArrayList
  $errors = New-Object System.Collections.ArrayList
  $index = 0
  foreach ($spec in @($pointSpecs)) {
    $index++
    $rawSpec = "$spec"
    if ($rawSpec -notmatch '^\s*(-?\d+)\s*,\s*(-?\d+)\s*$') {
      [void]$errors.Add([pscustomobject]@{
        index = $index
        point = $rawSpec
        code = "bad_point_spec"
        message = "point must be x,y"
      })
      continue
    }
    $x = [int]$Matches[1]
    $y = [int]$Matches[2]
    if ($x -le 0 -or $y -le 0) {
      [void]$errors.Add([pscustomobject]@{
        index = $index
        point = $rawSpec
        code = "invalid_coords"
        message = "x and y must be positive"
      })
      continue
    }
    $hit = _Native-HitTestPoint -X $x -Y $y -TargetHwnd $th -TargetMatch $tm
    $hit | Add-Member -NotePropertyName index -NotePropertyValue $index -Force
    [void]$results.Add($hit)
  }
  $sw.Stop()

  $matchedCount = @($results | Where-Object { $_.matched }).Count
  $partialCount = @($results | Where-Object { $_.status -ne "ok" }).Count
  $safeToAct = ($results.Count -gt 0 -and $errors.Count -eq 0 -and $partialCount -eq 0)
  $status = "ok"
  if (-not $safeToAct) { $status = "partial" }
  $payload = [pscustomobject]@{
    schema = "cucp.hit-test-batch/v1"
    status = $status
    source = "wrapper_win32_fast"
    uia_skipped = $true
    target_hwnd = $th
    target_match = $tm
    point_count = $pointSpecs.Count
    result_count = $results.Count
    matched_count = $matchedCount
    partial_count = $partialCount
    error_count = $errors.Count
    safe_to_act = [bool]$safeToAct
    elapsed_ms = [int]$sw.Elapsed.TotalMilliseconds
    results = @($results)
    errors = @($errors)
  }

  if ($Brief) {
    [Console]::Out.WriteLine("$status hit-test-batch points=$($pointSpecs.Count) matched=$matchedCount partial=$partialCount errors=$($errors.Count) elapsed_ms=$($payload.elapsed_ms)")
  } else {
    [Console]::Out.WriteLine(($payload | ConvertTo-Json -Depth 10))
  }
  if ($status -eq "ok") { return 0 }
  return 2
}

function Invoke-MacroHitScan {
  param([string[]]$Rest)
  $x = [int](_Read-OptValue -Rest $Rest -Name "--x")
  $y = [int](_Read-OptValue -Rest $Rest -Name "--y")
  $tm = _Read-OptValue -Rest $Rest -Name "--target-match"
  $th = [int](_Read-OptValue -Rest $Rest -Name "--target-hwnd")
  $clickInset = [int](_Read-OptValue -Rest $Rest -Name "--click-inset")
  $radiusRaw = _Read-OptValue -Rest $Rest -Name "--radius"
  $stepRaw = _Read-OptValue -Rest $Rest -Name "--step"
  $radius = 0
  $step = 6
  if ($null -ne $radiusRaw -and "$radiusRaw" -ne "") { $radius = [int]$radiusRaw }
  if ($null -ne $stepRaw -and "$stepRaw" -ne "") { $step = [int]$stepRaw }
  if ($x -le 0 -or $y -le 0) { throw "macro hit-scan requires --x and --y" }
  if ($clickInset -le 0) { $clickInset = 3 }
  if ($radius -lt 0) { $radius = 0 }
  if ($step -le 0) { $step = 6 }

  $argList = @("-Action","hit-scan","-X","$x","-Y","$y","-ClickInset","$clickInset","-ScanRadius","$radius","-ScanStep","$step")
  if ($tm) { $argList += @("-TargetMatch", $tm) }
  if ($th -gt 0) { $argList += @("-TargetHwnd", "$th") }
  $r = Invoke-NativeHelper -ArgList $argList
  $exitCode = [int]$r.ExitCode

  if ($Brief) {
    if ($r.Json -and $r.Json.status -eq "ok") {
      $best = $r.Json.best
      $pt = $r.Json.recommended_point
      [Console]::Out.WriteLine("ok hit-scan @($x,$y) best=($($pt.x),$($pt.y)) confidence=$($pt.confidence) role='$($best.role)' score=$($best.final_score) support=$($best.support) source=$($pt.point_source) samples=$($r.Json.sample_count)")
    } elseif ($r.Json) {
      $reason = if ($r.Json.reason) { "$($r.Json.reason)" } else { "no_candidate" }
      [Console]::Out.WriteLine("partial hit-scan @($x,$y) reason=$reason samples=$($r.Json.sample_count) matched=$($r.Json.target_matched_samples)")
    } else {
      [Console]::Out.WriteLine("err hit-scan @($x,$y) helper_failed exit=$exitCode")
    }
  } else {
    if ($r.Raw) { [Console]::Out.Write($r.Raw) }
  }
  return $exitCode
}



function _PointPlan-CacheKey {
  param([int]$X,[int]$Y,[int]$Radius,[int]$Step,[int]$ClickInset,[int]$TargetHwnd,[string]$TargetMatch,$Precheck,[string]$CoordSignature)
  _Invoke-LegacyPrecisionValue -Operation 'cache-key' -Arguments @{x=$X;y=$Y;radius=$Radius;step=$Step;click_inset=$ClickInset;target_hwnd=$TargetHwnd;target_match=$TargetMatch;precheck=$Precheck;coord_signature=$CoordSignature}
}

function _PointPlan-CachePath {param([string]$Key) _Invoke-LegacyPrecisionValue -Storage -Operation 'cache-path' -Arguments @{cache_dir=[string]$Script:CacheDir;key=$Key}}

function _PointPlan-ReadCache {param([string]$Key,[int]$MaxAgeSeconds) if(-not $Key -or $MaxAgeSeconds -le 0){return $null};_Invoke-LegacyPrecisionValue -Storage -Operation 'cache-read' -Arguments @{cache_dir=[string]$Script:CacheDir;key=$Key;max_age_seconds=$MaxAgeSeconds}}

function _PointPlan-WriteCache {param([string]$Key,$Payload) if(-not $Key -or -not $Payload){return};try{$text=$Payload|ConvertTo-Json -Depth 14;$null=_Invoke-LegacyPrecisionValue -Storage -Operation 'cache-write' -Arguments @{cache_dir=[string]$Script:CacheDir;key=$Key;serialized=$text}}catch{}}

function Invoke-MacroPointPlan {param([string[]]$Rest) _Invoke-LegacyPrecision -Operation 'point-plan' -Rest $Rest}

function _TargetValidate-ConfidenceRank {param([string]$Confidence) _Invoke-LegacyPrecisionValue -Operation 'confidence-rank' -Arguments @{value=$Confidence}}

function _TargetValidate-SizeClass {param($Rect,[int]$Area) _Invoke-LegacyPrecisionValue -Operation 'size-class' -Arguments @{rect=$Rect;area=$Area}}

function _TargetValidate-PointEdgeDistance {param($Point,$Rect) _Invoke-LegacyPrecisionValue -Operation 'edge-distance' -Arguments @{point=$Point;rect=$Rect}}

function _TargetValidate-InvokePointPlanJson {
  param([string[]]$PointPlanArgs)
  $writer=New-Object IO.StringWriter;$previous=[Console]::Out;$exitCode=1
  try{
    [Console]::SetOut($writer)
    try{$exitCode=Invoke-MacroPointPlan -Rest (@($PointPlanArgs)+@('--json-only'))}
    catch{$exitCode=if($_.Exception.Message -match 'AllowLiveControl|Live (desktop )?control|Live click|requires -AllowLiveControl|Coordinate-based act|requires --after|Label not found|affordance_id not found'){3}else{1}}
  }finally{[Console]::SetOut($previous)}
  $raw=$writer.ToString().Replace("`r`n","`n");$writer.Dispose();if($raw.EndsWith("`n")){$raw=$raw.Substring(0,$raw.Length-1)}
  _Invoke-LegacyPrecisionValue -Operation 'child-plan-envelope' -Arguments @{raw_lines=@($raw -split "`n");exit_code=[int]$exitCode}
}

function Invoke-MacroTargetValidate {param([string[]]$Rest) _Invoke-LegacyPrecision -Operation 'target-validate' -Rest $Rest}

# macro safe-type --text "..." --target-match <unique window title> | --target-hwnd N
# [--click-x N --click-y N] [--enter | --ctrl-enter] [--max-attempts N]
# Legacy --probe/--skip-probe arguments remain accepted but no text is inserted as a probe.
# Only focus preparation is retried; uncertain clicks or text insertion are never replayed.
function Invoke-MacroSafeType {param([string[]]$Rest) return _Invoke-LegacyInteractionFamily -Operation 'safe-type' -Rest $Rest -ScriptPath $PSCommandPath}

# ============================================================================
# v1.3.0 — Electron CDP wrapper macros
# ============================================================================
# DOM 직접 제어로 Electron app / VS Code / Slack 같은 Electron 앱의 좌표 무관 actuation.
# 활성화 가이드: references/cdp-setup.md
# ============================================================================

function Test-CdpPortQuick {
  param([int]$Port = 9222, [int]$TimeoutMs = 120)
  # v1.5.0 Phase 4: in-memory TTL cache (1초)
  # 같은 wrapper invocation 안에서 cdp-detect 와 그 직후 cdp-* 매크로가
  # 같은 port 를 재확인할 때 TCP socket 생성 비용 (~30-120ms) 회피.
  if (-not $Script:CdpPortCache) { $Script:CdpPortCache = @{} }
  $now = [DateTime]::UtcNow.Ticks
  if ($Script:CdpPortCache.ContainsKey($Port)) {
    $entry = $Script:CdpPortCache[$Port]
    if ($entry.expires_ticks -gt $now) {
      return [bool]$entry.open
    } else {
      [void]$Script:CdpPortCache.Remove($Port)
    }
  }
  $client = New-Object System.Net.Sockets.TcpClient
  $handle = $null
  $isOpen = $false
  try {
    $iar = $client.BeginConnect("127.0.0.1", $Port, $null, $null)
    $handle = $iar.AsyncWaitHandle
    if (-not $handle.WaitOne($TimeoutMs, $false)) { $isOpen = $false }
    else {
      $client.EndConnect($iar)
      $isOpen = [bool]$client.Connected
    }
  } catch {
    $isOpen = $false
  } finally {
    try { if ($handle) { $handle.Close() } } catch { }
    try { $client.Close() } catch { }
    try { $client.Dispose() } catch { }
  }
  $Script:CdpPortCache[$Port] = @{
    open = $isOpen
    expires_ticks = [DateTime]::UtcNow.AddMilliseconds(1000).Ticks
  }
  return $isOpen
}





# macro cdp-detect [--port N]
# 9222 포트 + 페이지 목록 (read-only)


# macro cdp-eval --expr "<javascript>" [--expr-b64 <base64>] [--page-match Electron app] [--port 9222]
# Arbitrary JavaScript can mutate a page; use the same live-control boundary as other actions.


# macro cdp-type --selector "<css>" --text "<msg>" [--page-match Electron app] [--port 9222]
#                [--press-enter] [--clear-first]
# DOM selector 의 element 에 focus + value set + dispatchEvent.
# -AllowLiveControl 필수 (실제 actuation).


# macro cdp-click --selector "<css>" [--page-match Electron app] [--port 9222]
# DOM selector 의 element.click(). 마우스 좌표 안 씀.
# -AllowLiveControl 필수.


# macro cdp-smart-click --text "<visible label>" [--page-match Electron app] [--port 9222]
# DOM visible text / aria-label / title / placeholder 기반 element.click().






# macro cdp-smart-type --label "<field label>" --text "<msg>" [--page-match Electron app] [--port 9222]
# DOM visible label / placeholder 기반 input/contenteditable 직접 입력.


# ============================================================================
# v1.1.0 — macro history: smart-click 학습 데이터 조회/관리
# ============================================================================
# 사용법:
#   macro history show [--label X] [--last N]    — 최근 N건 (또는 특정 라벨)
#   macro history stats                          — 전체 통계 (성공률, strategy 분포)
#   macro history clear                          — 학습 데이터 삭제
# ============================================================================
function Invoke-MacroHistory {
  param([string[]]$Rest)
  $action = "show"
  if ($Rest.Count -ge 1) { $action = $Rest[0] }
  switch ($action) {
    "show" {
      $label = _Read-OptValue -Rest $Rest -Name "--label"
      $lastN = [int](_Read-OptValue -Rest $Rest -Name "--last")
      if ($lastN -le 0) { $lastN = 20 }
      if (-not (Test-Path -LiteralPath $Script:HistoryFile)) {
        if ($Brief) { [Console]::Out.WriteLine("ok history empty file=none") }
        else { [Console]::Out.WriteLine('{"status":"ok","records":[]}') }
        return 0
      }
      $all = @(Get-Content -LiteralPath $Script:HistoryFile -Encoding UTF8)
      if (-not $all) { $all = @() }
      $records = @()
      for ($i = $all.Count - 1; $i -ge 0 -and $records.Count -lt $lastN; $i--) {
        try {
          $rec = $all[$i] | ConvertFrom-Json -ErrorAction Stop
          if ($label -and "$($rec.label)" -ne $label) { continue }
          $records += $rec
        } catch { continue }
      }
      if ($Brief) {
        [Console]::Out.WriteLine("ok history count=$($records.Count) label='$label' last=$lastN")
        foreach ($r in $records) {
          $okStr = if ($r.success) { "ok" } else { "fail" }
          [Console]::Out.WriteLine("  $okStr label='$($r.label)' match='$($r.match)' strategy=$($r.strategy) elapsed=$($r.elapsed_ms)ms")
        }
      } else {
        [Console]::Out.WriteLine(([pscustomobject]@{
          status = "ok"
          schema = "cucp.history/v1"
          records = @($records)
          count = $records.Count
        } | ConvertTo-Json -Depth 5))
      }
      return 0
    }
    "stats" {
      $stats = _History-Stats
      if ($Brief) {
        $strList = ($stats.strategies.Keys | Sort-Object | ForEach-Object {
          "$_=$($stats.strategies[$_])"
        }) -join ", "
        [Console]::Out.WriteLine("ok history stats total=$($stats.total) success=$($stats.success) rate=$($stats.success_rate)% strategies=[$strList]")
      } else {
        [Console]::Out.WriteLine(($stats | ConvertTo-Json -Depth 4))
      }
      return 0
    }
    "clear" {
      if (Test-Path -LiteralPath $Script:HistoryFile) {
        Remove-Item -LiteralPath $Script:HistoryFile -Force -ErrorAction SilentlyContinue
      }
      if ($Brief) { [Console]::Out.WriteLine("ok history cleared") }
      else { [Console]::Out.WriteLine('{"status":"ok","cleared":true}') }
      return 0
    }
    default {
      throw "macro history requires 'show' / 'stats' / 'clear' subcommand"
    }
  }
}

# ============================================================================
# macro smart-click ─ Cascade 전략 + ambiguity 거부 + 클릭 검증
# ============================================================================
# 사용자가 한 번만 호출해도 가장 안정적인 방법으로 클릭.
#
# Cascade 우선순위 (정확도 / 안전도 높은 순):
#   ┌─ Stage 0: CDP/DOM smart click         [--allow-cdp / --cdp-page-match / --cdp-port]
#   │    Chrome/Electron 원격 디버깅 포트가 열려 있으면 DOM text/aria/label 기반 click().
#   │    포트 탐지 지연을 피하려고 기본 자동 실행은 꺼져 있음.
#   ├─ Stage 1: UIA Pattern (uia-invoke)
#   │    InvokePattern.Invoke() 직접 호출. 마우스 안 움직임. BoundingRectangle만으로 동작.
#   │    가장 안전. 화면 가려져도 동작. UIA Name 매칭 score >= 60 만 허용.
#   ├─ Stage 2: UIA 좌표 클릭 (uia-click)        [--allow-mouse-fallback]
#   │    UIA 가 알려준 좌표로 SendInput 마우스 클릭.
#   ├─ Stage 3: icon-find synonym 매칭             [--allow-mouse-fallback]
#   │    tooltip / AutomationId / AccessKey 기반 시각 요소 매칭 (작은 toolbar 아이콘).
#   ├─ Stage 4: OCR+UIA fusion (ocr-uia-invoke)  [--allow-mouse-fallback default ON / --no-ocr]
#   │    OCR 좌표 위 UIA element 발견 시 한 프로세스 안에서 InvokePattern.Invoke().
#   │    UIA Name 비어있어도 AutomationId / ClassName 으로 invoke 가능 (v1.0.0).
#   │    Name 도 없으면 fallback_coord 좌표 클릭 (--allow-mouse-fallback 필요).
#   ├─ Stage 5: OCR text 좌표                     [--allow-mouse-fallback default ON]
#   │    UIA element 없는 순수 캔버스/이미지 표면. OCR 텍스트 cx/cy 좌표 클릭.
#   └─ Stage 6: vision-click-precise              [--allow-vision]
#        crop-and-refine 2단계 vision 매칭. 마지막 fallback. 비싸고 느림.
#
# 안전 정책:
#   - score < 60 (낮은 신뢰도) → partial(2) 거부, 후보 반환
#   - 두 후보 점수 차이 < 8 → ambiguous_target partial(2)
#   - --no-ocr 로 Stage 4/5 동시 비활성화 가능
#   - --verify-label <text> 로 클릭 후 라벨 등장 검증
#   - --verify-screen-changed 로 클릭 후 픽셀 변화 검증 (v0.9.0)
#   - --retry-on-no-change N 으로 변화 없을 시 cascade 재시도 (v1.0.0)
#
# History learning (v1.1.0):
#   - 같은 (label, match) 의 과거 5건 중 가장 자주 성공한 strategy 자동 추천
#   - cascade 의 앞 stages skip → 평균 응답 시간 단축
#   - 그 stage 가 실패하면 전체 cascade 자동 재시도 (안전망)
#   - --no-history 로 비활성화. macro history show / stats / clear 로 관리.
# ============================================================================

function Invoke-MacroSmartPlan {
  param([string[]]$Rest)
  $captures = New-Object System.Collections.ArrayList
  $arguments = @{rest=@($Rest); cache_seconds=[int]$CacheSeconds; brief=[bool]$Brief; elapsed_ms=0; captured_replies=@()}
  # Input parsing/semantic errors happen before any probe or stopwatch, as originally.
  $state = _Invoke-LegacyCompatibility -Operation 'smart-plan-advance' -Arguments $arguments
  if ($state.state -eq 'error') { throw [string]$state.error }

  $label = _Read-OptValue -Rest $Rest -Name '--label'
  $match = _Read-OptValue -Rest $Rest -Name '--match'
  if (-not $match) { $match = _Read-OptValue -Rest $Rest -Name '--window' }
  $role = _Read-OptValue -Rest $Rest -Name '--role'
  $typeText = _Read-OptValue -Rest $Rest -Name '--type-text'
  $typeMode = ($null -ne $typeText)
  $page = _Read-OptValue -Rest $Rest -Name '--cdp-page-match'
  $portRaw = _Read-OptValue -Rest $Rest -Name '--cdp-port'
  $port = [int]$portRaw
  if ($port -le 0) { $port = 9222 }
  $cdpEnabled = (-not (_Read-Switch -Rest $Rest -Name '--no-cdp')) -and ((_Read-Switch -Rest $Rest -Name '--allow-cdp') -or $page -or $portRaw)
  $ocrMatch = _Read-OptValue -Rest $Rest -Name '--ocr-match'
  if (-not $ocrMatch) { $ocrMatch = 'contains' }
  $ocrLanguage = _Read-OptValue -Rest $Rest -Name '--ocr-language'

  # A locally reconstructed closed schedule authorizes only the old read-only calls.
  # No descriptor argv is ever forwarded to a shell, scriptblock, or plan actuator.
  $expected = New-Object System.Collections.ArrayList
  [void]$expected.Add(@{kind='history';argv=@("$label","$match",'5')})
  if ($cdpEnabled) { [void]$expected.Add(@{kind='cdp_port';argv=@("$port",'120')}) }
  $uiaArgs=@('-Action','uia-find','-Label',$label)
  if ($match) { $uiaArgs+=@('-Match',$match) }
  if ($role) { $uiaArgs+=@('-Role',$role) }
  [void]$expected.Add(@{kind='native';argv=$uiaArgs})
  if ((_Read-Switch -Rest $Rest -Name '--include-ocr') -and -not $typeMode) {
    $ocrArgs=@('-Action','ocr-uia-fuse','-OcrText',$label,'-OcrMatch',$ocrMatch)
    if ($match) { $ocrArgs+=@('-Match',$match) }
    if ($ocrLanguage) { $ocrArgs+=@('-OcrLanguage',$ocrLanguage) }
    [void]$expected.Add(@{kind='native';argv=$ocrArgs})
  }
  function _SmartPlan-ValidateDescriptor {
    param($Actual,$Expected)
    if ($null -eq $Actual -or $Actual.kind -isnot [string] -or $Actual.argv -isnot [array]) { throw 'Invalid SmartPlan query descriptor.' }
    $names=@($Actual.PSObject.Properties.Name)
    if ($names.Count -ne 2 -or $names -notcontains 'kind' -or $names -notcontains 'argv') { throw 'Invalid SmartPlan query fields.' }
    if ($Actual.kind -cne $Expected.kind -or $Actual.argv.Count -ne $Expected.argv.Count) { throw 'SmartPlan query does not match original acquisition schedule.' }
    for ($j=0;$j -lt $Expected.argv.Count;$j++) {
      if ($Actual.argv[$j] -isnot [string] -or $Actual.argv[$j] -cne $Expected.argv[$j]) { throw 'SmartPlan query argv does not match original acquisition schedule.' }
    }
  }
  $sw=[Diagnostics.Stopwatch]::StartNew()
  for ($probe=0;$probe -le 5;$probe++) {
    if ($state.state -eq 'error') { throw [string]$state.error }
    if ($state.state -eq 'complete') {
      if ($probe -ne $expected.Count -or @($state.queries).Count -ne $probe) { throw 'SmartPlan completed before original acquisition schedule.' }
      for ($i=0;$i -lt $probe;$i++) { _SmartPlan-ValidateDescriptor $state.queries[$i] $expected[$i] }
      $sw.Stop();$elapsed=[int]$sw.Elapsed.TotalMilliseconds
      if ($null -eq $state.payload -or $state.payload.schema -cne 'cucp.smart-plan/v1' -or $state.payload.safe_to_act -isnot [bool] -or $state.payload.status -notin @('ok','partial') -or $state.exit -notin @(0,2) -or (($state.payload.status -eq 'ok') -ne $state.payload.safe_to_act) -or (($state.exit -eq 0) -ne $state.payload.safe_to_act)) { throw 'Invalid SmartPlan completion envelope.' }
      $state.payload.elapsed_ms=$elapsed
      if ($Brief -and -not (_Read-Switch -Rest $Rest -Name '--json-only')) {
        if ($state.brief -isnot [string]) { throw 'Missing SmartPlan brief output.' }
        [Console]::Out.WriteLine(($state.brief -replace 'elapsed_ms=\d+$',"elapsed_ms=$elapsed"))
      } else { [Console]::Out.WriteLine(($state.payload | ConvertTo-Json -Depth 12)) }
      return [int]$state.exit
    }
    if ($probe -ge 5 -or $probe -ge $expected.Count -or $state.state -cne 'query') { throw 'SmartPlan exceeded the original five-probe bound.' }
    if (@($state.queries).Count -ne ($probe+1)) { throw 'Invalid SmartPlan query trace length.' }
    for ($i=0;$i -le $probe;$i++) { _SmartPlan-ValidateDescriptor $state.queries[$i] $expected[$i] }
    _SmartPlan-ValidateDescriptor $state.query $expected[$probe]
    $descriptor=$expected[$probe]
    $capture=@{kind=$descriptor.kind;argv=@($descriptor.argv)}
    try {
      switch -CaseSensitive ($descriptor.kind) {
        'history' { $capture.result = _History-PickBestStrategy -Label $label -Match $match -LookbackN 5 }
        'cdp_port' {
          $capture.result = Test-CdpPortQuick -Port $port -TimeoutMs 120
          if ($capture.result) {
            $action=if ($typeMode) { 'cdp-smart-type-find' } else { 'cdp-smart-find' }
            $cdpArgs=@('-Action',$action,'-CdpText',$label,'-CdpPort',"$port")
            if ($page) { $cdpArgs+=@('-CdpPageMatch',$page) } elseif ($match) { $cdpArgs+=@('-CdpPageMatch',$match) }
            $expected.Insert($probe+1,@{kind='native';argv=$cdpArgs})
          }
        }
        'native' { $capture.result = Invoke-NativeHelper -ArgList $descriptor.argv }
        default { throw 'Unsupported SmartPlan query kind.' }
      }
    } catch {
      # Preserve swallowed history errors and propagated native/port failures via
      # the same replay error envelope. A failed query is never retried.
      [void]$capture.Remove('result');$capture.error=$_.Exception.Message
    }
    [void]$captures.Add($capture)
    $arguments.captured_replies=@($captures)
    $arguments.elapsed_ms=[int]$sw.Elapsed.TotalMilliseconds
    $state=_Invoke-LegacyCompatibility -Operation 'smart-plan-advance' -Arguments $arguments
  }
  throw 'SmartPlan did not finish within the original query bound.'
}

function _Parse-WorkflowStepTokens {
  param([string]$Step)
  $parseErrors = $null
  $tokens = [System.Management.Automation.PSParser]::Tokenize($Step, [ref]$parseErrors)
  if ($parseErrors -and $parseErrors.Count -gt 0) {
    return [pscustomobject]@{
      ok = $false
      error = "parse_error"
      detail = (($parseErrors | ForEach-Object { $_.Message }) -join "; ")
      tokens = @()
    }
  }
  $allowedTypes = @("Command","CommandArgument","String","Number")
  $items = New-Object System.Collections.ArrayList
  foreach ($t in @($tokens)) {
    $typeName = "$($t.Type)"
    if ($typeName -eq "NewLine" -or $typeName -eq "LineContinuation") { continue }
    if ($allowedTypes -notcontains $typeName) {
      return [pscustomobject]@{
        ok = $false
        error = "unsupported_token"
        detail = "unsupported token type '$typeName'"
        tokens = @()
      }
    }
    if ($null -ne $t.Content -and "$($t.Content)" -ne "") { [void]$items.Add("$($t.Content)") }
  }
  return [pscustomobject]@{
    ok = ($items.Count -gt 0)
    error = if ($items.Count -gt 0) { "" } else { "empty_step" }
    detail = ""
    tokens = @($items)
  }
}

function _Read-WorkflowStepSpecs {
  param([string[]]$Rest)
  $steps = New-Object System.Collections.ArrayList
  for ($i = 0; $i -lt $Rest.Count; $i++) {
    if ($Rest[$i] -ne "--step") { continue }
    $parts = New-Object System.Collections.ArrayList
    $j = $i + 1
    while ($j -lt $Rest.Count -and $Rest[$j] -ne "--step") {
      [void]$parts.Add($Rest[$j])
      $j++
    }
    if ($parts.Count -gt 0) {
      [void]$steps.Add((@($parts) -join " "))
    } else {
      [void]$steps.Add("")
    }
    $i = $j - 1
  }
  return @($steps)
}

function _Build-WorkflowPlan {
  param([string[]]$Rest)
  # Retain the exact legacy PSParser language; only policy/plan assembly is C#.
  $parsed = New-Object System.Collections.ArrayList
  foreach ($spec in @(_Read-WorkflowStepSpecs -Rest $Rest)) {
    [void]$parsed.Add((_Parse-WorkflowStepTokens -Step "$spec"))
  }
  $result = _Invoke-LegacyCompatibility -Operation 'workflow-plan-from-parsed' -Arguments @{rest=@($Rest); parsed_steps=@($parsed)}
  if ($result.schema -ne 'cucp.workflow-plan/v1' -or $result.status -notin @('ok','partial') -or $result.safe_to_run -isnot [bool] -or $result.requires_sensitive_confirmation -isnot [bool]) {
    throw 'Invalid workflow plan response; execution remains blocked.'
  }
  return $result
}

function Invoke-MacroWorkflowPlan {
  param([string[]]$Rest)
  $jsonOnly = _Read-Switch -Rest $Rest -Name "--json-only"
  $plan = _Build-WorkflowPlan -Rest $Rest
  if ($Brief -and -not $jsonOnly) {
    [Console]::Out.WriteLine("$($plan.status) workflow-plan steps=$($plan.step_count) live=$($plan.live_step_count) errors=$($plan.errors.Count)")
  } else {
    [Console]::Out.WriteLine(($plan | ConvertTo-Json -Depth 12))
  }
  if ($plan.status -eq "ok") { return 0 }
  return 2
}

function _Invoke-LegacyExecutionChild {
  param([string]$ScriptPath, $Effect, [bool]$LiveCeiling, [bool]$SensitiveCeiling,
        [switch]$SensitiveCeilingContractVerified)
  if (-not $SensitiveCeilingContractVerified) { throw 'Execution child sensitive-ceiling contract has not been qualified.' }
  $childTokens=$null;$childErrors=$null
  $childAst=[Management.Automation.Language.Parser]::ParseFile($ScriptPath,[ref]$childTokens,[ref]$childErrors)
  $childReader=@($childAst.FindAll({param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq '_Read-Switch'},$true))
  if ($childErrors.Count -gt 0 -or $childReader.Count -ne 1 -or -not $childReader[0].Extent.Text.Contains('cucp.execution-sensitive-ceiling/v1')) { throw 'Execution child does not support cucp.execution-sensitive-ceiling/v1.' }
  if ($Effect.kind -ne 'Child' -or $Effect.argv -isnot [array] -or
      @($Effect.argv | Where-Object { $_ -isnot [string] }).Count -gt 0 -or
      $Effect.live -isnot [bool] -or $Effect.quiet -isnot [bool] -or
      $Effect.brief -isnot [bool] -or $Effect.confirm_sensitive -isnot [bool]) { throw 'Invalid typed execution child descriptor.' }
  if ($Effect.live -and -not $LiveCeiling) { throw 'Execution descriptor exceeds live startup authority.' }
  if ($Effect.confirm_sensitive -and -not $SensitiveCeiling) { throw 'Execution descriptor exceeds sensitive startup authority.' }
  $bootstrap = @'
$ErrorActionPreference='Stop'
$ProgressPreference='SilentlyContinue'
$utf8=New-Object Text.UTF8Encoding($false,$true)
[Console]::OutputEncoding=$utf8
$reader=New-Object IO.StreamReader -ArgumentList @([Console]::OpenStandardInput(),$utf8,$true)
try {$text=$reader.ReadToEnd()} finally {$reader.Dispose()}
$r=$text | ConvertFrom-Json
$expected=@('schema','script_path','argv','live','quiet','brief','sensitive_ceiling')
if(@($r.PSObject.Properties).Count -ne $expected.Count -or @($r.PSObject.Properties | Where-Object {$_.Name -notin $expected}).Count -gt 0 -or
   $r.schema -ne 'cucp.execution-child/v1' -or $r.script_path -isnot [string] -or $r.argv -isnot [array] -or
   @($r.argv | Where-Object {$_ -isnot [string]}).Count -gt 0 -or $r.live -isnot [bool] -or
   $r.quiet -isnot [bool] -or $r.brief -isnot [bool] -or $r.sensitive_ceiling -isnot [bool]) {throw 'Invalid execution child request.'}
Set-Variable -Name CUCP_EXECUTION_SENSITIVE_CEILING -Scope Global -Option Constant -Value ([bool]$r.sensitive_ceiling)
$global:LASTEXITCODE=0
& ([string]$r.script_path) -AllowLiveControl:([bool]$r.live) -Quiet:([bool]$r.quiet) -Brief:([bool]$r.brief) -CucpArgs ([string[]]$r.argv)
exit [int]$LASTEXITCODE
'@
  $utf8=New-Object Text.UTF8Encoding($false,$true)
  $request=[ordered]@{schema='cucp.execution-child/v1';script_path=$ScriptPath;argv=@($Effect.argv);
    live=[bool]$Effect.live;quiet=[bool]$Effect.quiet;brief=[bool]$Effect.brief;sensitive_ceiling=($SensitiveCeiling -and [bool]$Effect.confirm_sensitive)}
  $bytes=$utf8.GetBytes((ConvertTo-Json -InputObject $request -Depth 8 -Compress))
  $psi=New-Object Diagnostics.ProcessStartInfo
  $psi.FileName=(Get-Command powershell.exe -CommandType Application -ErrorAction Stop).Source
  $psi.Arguments='-NoProfile -NonInteractive -ExecutionPolicy Bypass -InputFormat Text -OutputFormat Text -EncodedCommand '+[Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($bootstrap))
  $psi.UseShellExecute=$false;$psi.RedirectStandardInput=$true;$psi.RedirectStandardOutput=$true;$psi.RedirectStandardError=$true
  $psi.StandardOutputEncoding=$utf8;$psi.StandardErrorEncoding=$utf8
  $process=New-Object Diagnostics.Process;$process.StartInfo=$psi;$started=$false
  try {
    $started=$process.Start();$stdout=$process.StandardOutput.ReadToEndAsync();$stderr=$process.StandardError.ReadToEndAsync()
    $process.StandardInput.BaseStream.Write($bytes,0,$bytes.Length);$process.StandardInput.Close();$process.WaitForExit()
    $out=$stdout.GetAwaiter().GetResult();$err=$stderr.GetAwaiter().GetResult()
    if($Effect.name -ceq 'direct'){[Console]::Out.Write($out);if($err){[Console]::Error.Write($err)}}
    $raw=(($out+$err) -replace "`r`n","`n") -replace "`n$",''
    $json=$null;try {$json=$raw|ConvertFrom-Json -ErrorAction Stop} catch {}
    return [pscustomobject]@{exit=[int]$process.ExitCode;raw=$raw;json=$json}
  } finally {if($started){try {if(-not $process.HasExited){$process.Kill()}} catch {}};$process.Dispose()}
}

function _Execution-EncodeWire($Value) {
  if($null -eq $Value){return @{kind='scalar';value=$null}}
  if($Value -is [string] -or $Value -is [ValueType]){return @{kind='scalar';value=$Value}}
  if($Value -is [System.Collections.IDictionary]){return @{kind='object';properties=@(foreach($key in $Value.Keys){@{name=[string]$key;value=(_Execution-EncodeWire $Value[$key])}})}}
  if($Value -is [System.Collections.IEnumerable]){return @{kind='array';items=@(foreach($item in $Value){_Execution-EncodeWire $item})}}
  return @{kind='object';properties=@(foreach($p in $Value.PSObject.Properties){@{name=$p.Name;value=(_Execution-EncodeWire $p.Value)}})}
}

function _Execution-Require($Condition,[string]$Message) {
  if (-not $Condition) { throw (New-Object InvalidOperationException -ArgumentList $Message) }
}

function _Execution-Fields($Value,[string[]]$Names) {
  _Execution-Require ($null -ne $Value -and $Value -isnot [array] -and $Value -isnot [string] -and $Value -isnot [ValueType]) 'Expected an execution protocol object.'
  $properties=@($Value.PSObject.Properties)
  _Execution-Require ($properties.Count -eq $Names.Count -and @($properties | Where-Object {$_.Name -cnotin $Names}).Count -eq 0) 'Unexpected execution protocol fields.'
}

function _Execution-DecodeWire($Wire) {
  _Execution-Require ($null -ne $Wire -and $Wire.kind -is [string]) 'Missing execution wire tag.'
  switch -CaseSensitive ($Wire.kind) {
    'scalar' {
      _Execution-Fields $Wire @('kind','value')
      _Execution-Require ($null -eq $Wire.value -or $Wire.value -is [string] -or $Wire.value -is [ValueType]) 'Invalid scalar wire value.'
      return ,$Wire.value
    }
    'array' {
      _Execution-Fields $Wire @('kind','items');_Execution-Require ($Wire.items -is [array]) 'Wire array items must be an array.'
      $items=New-Object Collections.ArrayList
      foreach($item in $Wire.items){[void]$items.Add((_Execution-DecodeWire $item))}
      return ,([object[]]$items.ToArray())
    }
    'object' {
      _Execution-Fields $Wire @('kind','properties');_Execution-Require ($Wire.properties -is [array]) 'Wire object properties must be an array.'
      $object=[ordered]@{}
      foreach($property in $Wire.properties){
        _Execution-Fields $property @('name','value');_Execution-Require ($property.name -is [string] -and -not $object.Contains($property.name)) 'Invalid or duplicate wire property.'
        $object[$property.name]=_Execution-DecodeWire $property.value
      }
      return ,([pscustomobject]$object)
    }
    default {throw 'Unknown execution wire kind.'}
  }
}

function _Execution-WriteChunks($Writer,[long]$Id,[string]$Target,$Value) {
  $utf8=New-Object Text.UTF8Encoding($false,$true)
  $bytes=$utf8.GetBytes((ConvertTo-Json -InputObject $Value -Depth 100 -Compress))
  for($offset=0;$offset -lt $bytes.Length;$offset+=49152){
    $count=[Math]::Min(49152,$bytes.Length-$offset)
    $frame=[ordered]@{kind='part';id=$Id;data=[Convert]::ToBase64String($bytes,$offset,$count)}
    if($Target){$frame['target']=$Target}
    $Writer.WriteLine((ConvertTo-Json -InputObject $frame -Compress))
  }
  $end=[ordered]@{kind='end';id=$Id};if($Target){$end['target']=$Target}
  $Writer.WriteLine((ConvertTo-Json -InputObject $end -Compress));$Writer.Flush()
}

function _Execution-WriteDiagnostic($State,$Process,$Stderr,[string]$ErrorText) {
  # Qualification-only opt-in. Never modify the protocol or replace its error.
  try {
    if($env:CUCP_EXECUTION_DIAGNOSTICS -cne '1' -or $State.diagnostic_phase -ceq 'host-error'){return}
    $counter=Get-Variable -Name ExecutionDiagnosticCount -Scope Script -ErrorAction SilentlyContinue
    $count=if($null -eq $counter){0}else{[int]$counter.Value}
    if($count -ge 4){return};$script:ExecutionDiagnosticCount=$count+1
    $line=[string]$State.diagnostic_frame;$prefix=$line.Substring(0,[Math]::Min(256,$line.Length))
    $points=@(foreach($character in $line.Substring(0,[Math]::Min(16,$line.Length)).ToCharArray()){'U+{0:X4}' -f [int]$character})
    $exited=$null;$code=$null;$err=''
    if($null -ne $Process){$exited=$Process.HasExited;if($exited){$code=$Process.ExitCode}}
    if($null -ne $Stderr -and $Stderr.IsCompleted){$err=[string]$Stderr.GetAwaiter().GetResult()}
    $record=[ordered]@{phase=[string]$State.diagnostic_phase;expected_id=$State.diagnostic_expected_id;
      frame_characters=$line.Length;prefix_codepoints=$points;frame_prefix=$prefix;
      host_exited=$exited;host_exit=$code;stderr_prefix=$err.Substring(0,[Math]::Min(1024,$err.Length));
      error=$ErrorText.Substring(0,[Math]::Min(512,$ErrorText.Length))}
    [Console]::Error.WriteLine('[execution-protocol] '+(ConvertTo-Json -InputObject $record -Depth 5 -Compress))
  } catch {} # Diagnostic collection cannot mask the original failure.
}

function _Execution-ValidateEffect($Effect,$State) {
  _Execution-Fields $Effect @('kind','name','argv','data','live','quiet','brief','confirm_sensitive')
  _Execution-Require ($Effect.kind -is [string] -and $Effect.name -is [string] -and $Effect.argv -is [array] -and
    @($Effect.argv | Where-Object {$_ -isnot [string]}).Count -eq 0 -and $Effect.live -is [bool] -and
    $Effect.quiet -is [bool] -and $Effect.brief -is [bool] -and $Effect.confirm_sensitive -is [bool]) 'Malformed execution effect descriptor.'
  _Execution-Require (-not $Effect.live -or $State.live) 'Effect exceeds immutable live startup authority.'
  _Execution-Require (-not $Effect.confirm_sensitive -or $State.sensitive) 'Effect exceeds immutable sensitive startup authority.'
  $Effect.data=_Execution-DecodeWire $Effect.data
  if($State.family -ceq 'interaction'){_Interaction-ValidateEffect $Effect $State;return}
  if($State.family -ceq 'diagnostics'){_Diagnostic-ValidateEffect $Effect $State;return}
  $a=@($Effect.argv);$d=$Effect.data;$n=$Effect.name;$kind=$Effect.kind
  _Execution-Require ($kind -cin @('WorkflowPlan','Child','Native','LocalMacro','CdpPort','HistoryRead','HistoryAppend','TrajectoryAppend','Sleep','Clock','Timestamp','CachePath','FileExists','RemoveFile','SendEscape','Console')) 'Unknown execution effect.'
  if($kind -ne 'Child'){_Execution-Require (-not $Effect.quiet -and -not $Effect.brief) 'Non-child effect changed child options.'}
  if($kind -notin @('Child','SendEscape')){_Execution-Require (-not $Effect.confirm_sensitive) 'Unexpected sensitive effect option.'}
  if($kind -notin @('Child','Native','LocalMacro','SendEscape')){_Execution-Require (-not $Effect.live) 'Unexpected live effect option.'}
  switch -CaseSensitive ($kind) {
    'WorkflowPlan' {_Execution-Require ($n -eq '' -and $null -eq $d) 'Invalid workflow acquisition descriptor.'}
    'Child' {_Execution-Require ($n -cin @('','direct') -and $null -eq $d) 'Invalid child execution descriptor.'}
    'Native' {
      _Execution-Require ($n -eq '' -and $null -eq $d -and $a.Count -ge 2 -and ($a.Count%2) -eq 0 -and $a[0] -ceq '-Action') 'Invalid native execution descriptor.'
      $action=$a[1];$live=$action -cin @('uia-invoke','uia-click','click','ocr-uia-invoke','cdp-smart-click')
      _Execution-Require ($Effect.live -eq $live) 'Native action/live classification mismatch.'
      $fields=switch -CaseSensitive ($action) {
        'focused' {@()};'modal-detect' {@('-Match')}
        'uia-find' {@('-Label','-Match','-Role')};'uia-invoke' {@('-Label','-Match','-Role')};'uia-click' {@('-Label','-Match','-Role')}
        'cdp-smart-click' {@('-CdpText','-CdpPort','-CdpPageMatch')}
        'ocr-uia-invoke' {@('-OcrText','-OcrMatch','-OcrMaxCandidates','-Match','-OcrLanguage')}
        'ocr-find-text' {@('-OcrText','-OcrMatch','-OcrMaxCandidates','-Match','-OcrLanguage')}
        'click' {@('-X','-Y','-Button','-ClickRefine','-TargetMatch')}
        'screenshot' {@('-OutPath','-ScreenshotX','-ScreenshotY','-ScreenshotW','-ScreenshotH')}
        'screenshot-diff' {@('-DiffBefore','-DiffAfter','-DiffThreshold')}
        default {throw 'Native action is outside execution coordination.'}
      }
      $seen=@{}
      for($i=2;$i -lt $a.Count;$i+=2){_Execution-Require ($a[$i] -cin $fields -and -not $seen.ContainsKey($a[$i])) 'Invalid or duplicate native effect argument.';$seen[$a[$i]]=$a[$i+1]}
      if($action -eq 'screenshot'){_Execution-Require ($State.paths.ContainsKey($seen['-OutPath'])) 'Screenshot destination is not owned by this execution.'}
      if($action -eq 'screenshot-diff'){_Execution-Require ($State.paths.ContainsKey($seen['-DiffBefore']) -and $State.paths.ContainsKey($seen['-DiffAfter'])) 'Screenshot diff paths are not owned by this execution.'}
    }
    'LocalMacro' {_Execution-Require ($n -cin @('click-point','icon-find') -and $null -eq $d -and $Effect.live -eq ($n -eq 'click-point')) 'Invalid local execution macro.'}
    'CdpPort' {_Execution-Require ($n -eq '' -and $null -eq $d -and $a.Count -eq 2 -and $a[1] -ceq '120' -and $a[0] -match '^\d+$') 'Invalid CDP port query.'}
    'HistoryRead' {_Execution-Require ($n -eq '' -and $null -eq $d -and $a.Count -eq 3 -and $a[2] -ceq '5') 'Invalid history query.'}
    'HistoryAppend' {
      _Execution-Require ($n -eq '' -and $a.Count -eq 3) 'Invalid history append descriptor.'
      _Execution-Fields $d @('success','elapsed_ms');_Execution-Require ($d.success -is [bool] -and ($d.elapsed_ms -is [int] -or $d.elapsed_ms -is [long]) -and $d.elapsed_ms -ge [int]::MinValue -and $d.elapsed_ms -le [int]::MaxValue) 'Invalid history append payload.'
    }
    'TrajectoryAppend' {
      _Execution-Require ($n -cin @('workflow-run','task-run','form-run') -and $a.Count -eq 0) 'Invalid trajectory append kind.'
      if($n -eq 'task-run'){_Execution-Fields $d @('status','dry_run','workflow_exit','elapsed_ms')}
      else {_Execution-Fields $d @('status','executed_count','failed_count','total_steps','elapsed_ms')}
    }
    'Sleep' {_Execution-Require ($n -eq '' -and $a.Count -eq 0 -and ($d -is [int] -or $d -is [long]) -and $d -ge 0 -and $d -le [int]::MaxValue) 'Invalid execution sleep.'}
    'Clock' {_Execution-Require ($n -cin @('start','stop','elapsed') -and $a.Count -eq 0 -and $d -is [string] -and $d -cin @('total','step','attempt','run')) 'Invalid execution clock.'}
    'Timestamp' {_Execution-Require ($n -cin @('o','HHmmss-fff') -and $a.Count -eq 0 -and $null -eq $d) 'Invalid execution timestamp.'}
    'CachePath' {_Execution-Require ($n -cin @('smartclick-before','smartclick-after','smartclick-retry-before','smartclick-retry-after') -and $a.Count -eq 0 -and $d -is [string] -and $d -match '^\d{6}-\d{3}$') 'Invalid execution capture path.'}
    'FileExists' {_Execution-Require ($n -eq '' -and $a.Count -eq 0 -and $d -is [string] -and $State.paths.ContainsKey($d)) 'Execution file probe is outside owned captures.'}
    'RemoveFile' {_Execution-Require ($n -eq '' -and $a.Count -eq 0 -and $d -is [string] -and $State.paths.ContainsKey($d)) 'Execution cleanup is outside owned captures.'}
    'SendEscape' {_Execution-Require ($n -eq '' -and $a.Count -eq 0 -and $null -eq $d -and $Effect.live -and $Effect.confirm_sensitive) 'Escape input requires both explicit startup gates.'}
    'Console' {_Execution-Require ($n -eq '' -and $a.Count -eq 0 -and $d -is [string]) 'Invalid execution console output.'}
  }
}

function _Execution-SendEscape {
  Add-Type -AssemblyName System.Windows.Forms -ErrorAction Stop
  [System.Windows.Forms.SendKeys]::SendWait('{ESC}')
}

function _Execution-Dispatch($Effect,$State) {
  if($State.family -ceq 'interaction'){return ,(_Interaction-Dispatch $Effect $State)}
  if($State.family -ceq 'diagnostics'){return ,(_Diagnostic-Dispatch $Effect $State)}
  $a=[string[]]$Effect.argv;$d=$Effect.data;$n=$Effect.name
  switch -CaseSensitive ($Effect.kind) {
    'WorkflowPlan' {return ,(_Build-WorkflowPlan -Rest $a)}
    'Child' {return ,(_Invoke-LegacyExecutionChild -ScriptPath $State.script_path -Effect $Effect -LiveCeiling $State.live -SensitiveCeiling $State.sensitive -SensitiveCeilingContractVerified)}
    'Native' {return ,(Invoke-NativeHelper -ArgList $a)}
    'LocalMacro' {
      $previous=[Console]::Out;$writer=New-Object IO.StringWriter
      try {
        [Console]::SetOut($writer)
        if($n -eq 'click-point'){$exit=Invoke-MacroClickPoint -Rest $a}else{Invoke-MacroIconFind -Rest $a | Out-Null;$exit=0}
      } finally {[Console]::SetOut($previous)}
      $raw=$writer.ToString();$writer.Dispose();$json=$null
      try {$json=$raw|ConvertFrom-Json -ErrorAction Stop} catch {}
      return [pscustomobject]@{exit=[int]$exit;raw=$raw;json=$json}
    }
    'CdpPort' {return Test-CdpPortQuick -Port ([int]$a[0]) -TimeoutMs ([int]$a[1])}
    'HistoryRead' {return ,(_History-PickBestStrategy -Label $a[0] -Match $a[1] -LookbackN ([int]$a[2]))}
    'HistoryAppend' {_History-Append -Label $a[0] -Match $a[1] -Strategy $a[2] -Success ([bool]$d.success) -ElapsedMs ([int]$d.elapsed_ms);return}
    'TrajectoryAppend' {$payload=@{};foreach($p in $d.PSObject.Properties){$payload[$p.Name]=$p.Value};_Trajectory-Append -Kind $n -Payload $payload;return}
    'Sleep' {Start-Sleep -Milliseconds ([int]$d);return}
    'Clock' {
      if($n -eq 'start'){$State.clocks[$d]=[Diagnostics.Stopwatch]::StartNew();return 0}
      if(-not $State.clocks.ContainsKey($d)){throw 'Execution clock has not been started.'}
      if($n -eq 'stop'){$State.clocks[$d].Stop()}
      return [int]$State.clocks[$d].Elapsed.TotalMilliseconds
    }
    'Timestamp' {return (Get-Date).ToString($n)}
    'CachePath' {$path=Join-Path $State.cache_dir ($n+'-'+$d+'.png');$State.paths[$path]=$true;return $path}
    'FileExists' {return Test-Path -LiteralPath ([string]$d)}
    'RemoveFile' {Remove-Item -LiteralPath ([string]$d) -Force -ErrorAction SilentlyContinue;return}
    'SendEscape' {_Execution-SendEscape;return}
    'Console' {[Console]::Out.WriteLine([string]$d);return}
    default {throw 'Unknown execution effect.'}
  }
}

# This classification records possible owned-state changes; it grants no authority.
# The validated descriptor has already passed the family-specific ownership checks.
function _Execution-EffectMayChangeState($Effect) {
  if($Effect.live){return $true}
  if($Effect.kind -cin @('Child','HistoryAppend','TrajectoryAppend','RemoveFile','PointCacheWrite','AnchorAppend','Appshot','Vision','Notice','Cucp')){return $true}
  if($Effect.kind -ceq 'LocalMacro'){return $Effect.name -cne 'icon-find'}
  if($Effect.kind -ceq 'Native'){return $true} # Retained helper may write cache/log files for every action.
  if($Effect.kind -ceq 'Diagnostic'){
    if($Effect.name -cin @('AuditProbe','ClearAppshotCache','Appshot','Notice','HelperUp','AssertAuthorized','Cli','Native')){return $true}
    if($Effect.name -ceq 'Macro'){return ($Effect.data.name -cin @('health-quick','find-label')) -or
      ($Effect.data.name -ceq 'windows' -and $Effect.argv.Count -eq 1 -and $Effect.argv[0] -ceq '--rich')}
  }
  return $false
}

function _Invoke-LegacyExecutionEffectLoop {
  param([Diagnostics.Process]$HostProcess,[hashtable]$State)
  $utf8=New-Object Text.UTF8Encoding($false,$true);$sequence=0L
  while($true) {
    $buffer=New-Object IO.MemoryStream;$target=$null;$id=$null
    try {
      while($true) {
        $State.diagnostic_phase='read-frame';$State.diagnostic_expected_id=$sequence+1;$State.diagnostic_frame=$null
        $line=$HostProcess.StandardOutput.ReadLine();if($null -eq $line){if($State.state_effect_seen -or $State.live_effect_seen){throw 'mutation_may_have_occurred=true; automatic_retry=false; execution session disconnected.'};throw 'Execution session disconnected; automatic_retry=false.'}
        $State.diagnostic_frame=$line;$State.diagnostic_phase='parse-frame'
        $frame=$line|ConvertFrom-Json -ErrorAction Stop
        $State.diagnostic_phase='validate-frame'
        if($frame.kind -ceq 'part'){_Execution-Fields $frame @('kind','target','id','data')}
        elseif($frame.kind -ceq 'end'){_Execution-Fields $frame @('kind','target','id')}
        else {throw 'Unknown execution frame kind.'}
        _Execution-Require ($frame.target -cin @('effect','complete','error') -and ($frame.id -is [int] -or $frame.id -is [long]) -and $frame.id -eq ($sequence+1)) 'Invalid execution frame sequence.'
        if($null -eq $id){$id=[long]$frame.id;$target=[string]$frame.target}
        _Execution-Require ($frame.id -eq $id -and $frame.target -ceq $target) 'Execution frame target changed.'
        if($frame.kind -ceq 'end'){break}
        _Execution-Require ($frame.data -is [string]) 'Execution chunk data must be a base64 string.'
        $part=[Convert]::FromBase64String($frame.data);_Execution-Require ($part.Length -le 49152) 'Execution chunk exceeds 48 KiB.';$buffer.Write($part,0,$part.Length)
      }
      $State.diagnostic_phase='parse-message'
      $message=$utf8.GetString($buffer.ToArray())|ConvertFrom-Json -ErrorAction Stop
    } finally {$buffer.Dispose()}
    $sequence=$id
    if($target -ceq 'error'){
      $State.diagnostic_phase='host-error'
      _Execution-Fields $message @('message','mutation_may_have_occurred','automatic_retry')
      _Execution-Require ($message.message -is [string] -and $message.mutation_may_have_occurred -is [bool] -and $message.automatic_retry -is [bool] -and -not $message.automatic_retry) 'Invalid execution error envelope.'
      if($message.mutation_may_have_occurred){throw ('mutation_may_have_occurred=true; automatic_retry=false; '+$message.message)}
      throw $message.message
    }
    if($target -ceq 'complete') {
      $State.diagnostic_phase='validate-completion'
      _Execution-Fields $message @('payload','exit','json_depth','brief','emit_json')
      # PS5 parses JSON integers as Int32; PS7 uses Int64. Accept both parser
      # representations while preserving the exact integer/range contract.
      _Execution-Require (($message.exit -is [int] -or $message.exit -is [long]) -and
        $message.exit -ge [int]::MinValue -and $message.exit -le [int]::MaxValue -and
        ($State.family -ceq 'interaction' -or ($message.exit -ge 0 -and $message.exit -le 3)) -and
        ($message.json_depth -is [int] -or $message.json_depth -is [long]) -and
        $message.json_depth -ge 0 -and $message.json_depth -le 100 -and $message.emit_json -is [bool] -and ($null -eq $message.brief -or $message.brief -is [string])) 'Invalid execution completion envelope.'
      $payload=_Execution-DecodeWire $message.payload
      if($State.family -ceq 'diagnostics'){$payload=_Diagnostic-PreparePayload $payload $State}
      if($message.emit_json){[Console]::Out.WriteLine((ConvertTo-Json -InputObject $payload -Depth ([int]$message.json_depth)))}
      elseif($null -ne $message.brief){[Console]::Out.WriteLine([string]$message.brief)}
      return [int]$message.exit
    }
    # Protocol/authority failures must terminate, never become fallback replies.
    $State.diagnostic_phase='validate-effect'
    _Execution-ValidateEffect $message $State
    $State.diagnostic_phase='dispatch-effect'
    if($message.live){$State.live_effect_seen=$true}
    $currentMayChangeState=[bool](_Execution-EffectMayChangeState $message)
    if($currentMayChangeState){$State.state_effect_seen=$true}
    try {$value=_Execution-Dispatch $message $State;$reply=@{state='ok';value=(_Execution-EncodeWire $value)}}
    catch {$reply=@{state='error';message=$_.Exception.Message;mutation_may_have_occurred=[bool]($currentMayChangeState -or $State.live_effect_seen)}}
    _Execution-WriteChunks -Writer $State.writer -Id $id -Target '' -Value $reply
  }
}

function _Invoke-LegacyExecutionFamily {
  param([ValidateSet('workflow-run','task-run','form-run','smart-click','watch','recovery-plan','recovery-run')][string]$Operation,[string[]]$Rest,[string]$ScriptPath)
  # Capture immutable invocation context before any plan/acquisition effect.
  $liveCeiling=[bool]$AllowLiveControl
  $sensitiveCeiling=[bool](_Read-StandaloneConfirmation -Rest $Rest)
  $inherited=Get-Variable -Name CUCP_EXECUTION_SENSITIVE_CEILING -Scope Global -ErrorAction SilentlyContinue
  if($null -ne $inherited -and ($inherited.Value -isnot [bool] -or -not $inherited.Value -or
      -not ($inherited.Options -band [Management.Automation.ScopedItemOptions]::Constant))){$sensitiveCeiling=$false}
  $startup=[ordered]@{schema='cucp.execution-start/v1';operation=$Operation;rest=@($Rest);brief=[bool]$Brief;
    cache_seconds=[int]$CacheSeconds;vision_available=[bool]$Script:CliPath;culture=[Globalization.CultureInfo]::CurrentCulture.Name}
  $restCopy=@($Rest);if($null -ne $restCopy){$restCopy=$restCopy.Clone()}
  $state=@{family='execution';operation=$Operation;rest=$restCopy;state_effect_seen=$false;live=$liveCeiling;sensitive=$sensitiveCeiling;script_path=$ScriptPath;cache_dir=$Script:CacheDir;paths=@{};clocks=@{};writer=$null;live_effect_seen=$false}
  return _Invoke-LegacyExecutionHost -EntryPoint 'legacy-execution-session' -Startup $startup -State $state
}

function _Invoke-LegacyExecutionHost {
  param([ValidateSet('legacy-execution-session','legacy-interaction-session','legacy-diagnostic-session')][string]$EntryPoint,
    $Startup,[hashtable]$State)
  _Execution-Require ($State.live -is [bool] -and $State.sensitive -is [bool]) 'Host authority ceilings must be booleans.'
  $expectedFamily=switch($EntryPoint){'legacy-execution-session'{'execution'};'legacy-interaction-session'{'interaction'};'legacy-diagnostic-session'{'diagnostics'}}
  _Execution-Require ($State.family -ceq $expectedFamily -and $State.operation -ceq $Startup.operation) 'Host family or operation context mismatch.'
  $State.state_effect_seen=$false;$State.live_effect_seen=$false
  $native=$env:CUCP_NATIVE_HOST
  if(-not $native){$native=Join-Path $PSScriptRoot '..\pcucp-next\bin\native\PcuCp.NativeHost.exe'}
  $native=[IO.Path]::GetFullPath($native)
  if(-not (Test-Path -LiteralPath $native -PathType Leaf)){throw 'Matching execution runtime missing. Publish the native runtime or set CUCP_NATIVE_HOST to its executable/DLL.'}
  $psi=New-Object Diagnostics.ProcessStartInfo
  switch ([IO.Path]::GetExtension($native).ToLowerInvariant()) {
    '.dll' {
      if($native.Contains('"') -or $native.Contains("`r") -or $native.Contains("`n")){throw 'Invalid execution runtime DLL path.'}
      $psi.FileName=(Get-Command dotnet.exe -CommandType Application -TotalCount 1 -ErrorAction Stop).Source
      $psi.Arguments='"'+$native+'" '+$EntryPoint
    }
    '.exe' {$psi.FileName=$native;$psi.Arguments=$EntryPoint}
    default {throw 'Execution runtime must be an executable or DLL, never a shell script.'}
  }
  if($State.live){$psi.Arguments+=' --allow-live-control'}
  if($State.sensitive){$psi.Arguments+=' --confirm-sensitive'}
  $utf8=New-Object Text.UTF8Encoding($false,$true)
  $psi.UseShellExecute=$false;$psi.CreateNoWindow=$true
  $psi.RedirectStandardInput=$true;$psi.RedirectStandardOutput=$true;$psi.RedirectStandardError=$true
  $psi.StandardOutputEncoding=$utf8;$psi.StandardErrorEncoding=$utf8
  $process=New-Object Diagnostics.Process;$process.StartInfo=$psi;$started=$false;$writer=$null;$stderr=$null
  try {
    $started=$process.Start();if(-not $started){throw 'Execution runtime did not start.'}
    $stderr=$process.StandardError.ReadToEndAsync()
    # Own no-BOM writer; .NET Framework's default redirected writer is not used.
    $writer=New-Object IO.StreamWriter -ArgumentList @($process.StandardInput.BaseStream,$utf8,4096,$true)
    $state.writer=$writer
    _Execution-WriteChunks -Writer $writer -Id 0 -Target '' -Value $startup
    $exit=_Invoke-LegacyExecutionEffectLoop -HostProcess $process -State $state
    $writer.Flush();$writer.Dispose();$writer=$null;$process.StandardInput.Close()
    if(-not $process.WaitForExit(10000)){throw 'Execution runtime did not exit after its final report; no action was retried.'}
    $err=$stderr.GetAwaiter().GetResult()
    if($process.ExitCode -ne $exit){throw ('Execution runtime exit did not match its final report. '+$err)}
    if($State.family -ceq 'interaction'){foreach($item in $State.pipeline_output){Write-Output -InputObject $item}}
    return [int]$exit
  } catch {
    _Execution-WriteDiagnostic -State $state -Process $process -Stderr $stderr -ErrorText $_.Exception.Message
    if(($state.state_effect_seen -or $state.live_effect_seen) -and $_.Exception.Message -notlike 'mutation_may_have_occurred=true;*'){
      throw ('mutation_may_have_occurred=true; automatic_retry=false; '+$_.Exception.Message)
    }
    throw
  } finally {
    if($null -ne $writer){try {$writer.Dispose()}catch {}}
    if($started){try {if(-not $process.HasExited){$process.Kill();[void]$process.WaitForExit(5000)}}catch {}}
    $process.Dispose()
  }
}

function Invoke-MacroWorkflowRun {param([string[]]$Rest) return _Invoke-LegacyExecutionFamily -Operation 'workflow-run' -Rest $Rest -ScriptPath $PSCommandPath}







function _AppStrategy-NormalizeRoute {
  param([string]$Strategy)
  $s = "$Strategy"
  if (-not $s) { return "" }
  $s = ($s -replace '\+.*$', '').ToLowerInvariant()
  switch -Regex ($s) {
    '^cdp' { return "cdp_dom" }
    '^uia_set_value$' { return "uia_value_or_pattern" }
    '^uia_pattern$' { return "uia_pattern" }
    '^uia_precision_point$' { return "precision_point" }
    '^uia_coord$' { return "uia_click" }
    '^fusion_uia_invoke$' { return "fusion_uia_invoke" }
    '^fusion_coord$' { return "ocr" }
    '^ocr_text$' { return "ocr" }
    '^vision_precise$' { return "vision_precise" }
    default { return $s }
  }
}



function _AppStrategy-Read {
  if (-not $Script:AppStrategyFile -or -not (Test-Path -LiteralPath $Script:AppStrategyFile)) { return @() }
  $records = New-Object System.Collections.ArrayList
  foreach ($line in @(Get-Content -LiteralPath $Script:AppStrategyFile -Encoding UTF8 -ErrorAction SilentlyContinue)) {
    if ([string]::IsNullOrWhiteSpace($line)) { continue }
    try {
      $obj = $line | ConvertFrom-Json -ErrorAction Stop
      if ($obj) { [void]$records.Add($obj) }
    } catch { }
  }
  return @($records)
}

function _AppStrategy-LastGood {
  param([string]$AppKey)
  if (-not $AppKey) { return $null }
  $records = @(_AppStrategy-Read | Where-Object {
    "$($_.app_key)" -eq $AppKey -and $_.success -eq $true -and $_.strategy
  })
  if ($records.Count -eq 0) { return $null }
  return @($records | Sort-Object ts -Descending | Select-Object -First 1)[0]
}

function _AppStrategy-Append {
  param(
    [string]$AppKey,
    [string]$AppType,
    [string]$Strategy,
    [string]$Confidence,
    [int]$Score,
    [string]$Process,
    [string]$Class,
    [string]$Title
  )
  if (-not $Script:AppStrategyFile -or -not $AppKey -or -not $Strategy) { return $null }
  try {
    $dir = Split-Path -Parent $Script:AppStrategyFile
    if ($dir -and -not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
    $record = [pscustomobject]@{
      ts = (Get-Date).ToString("o")
      app_key = $AppKey
      app_type = $AppType
      strategy = $Strategy
      normalized_strategy = (_AppStrategy-NormalizeRoute -Strategy $Strategy)
      confidence = $Confidence
      score = [int]$Score
      success = $true
      process = $Process
      class = $Class
      title = $Title
    }
    $line = $record | ConvertTo-Json -Compress -Depth 6
    Add-Content -LiteralPath $Script:AppStrategyFile -Value $line -Encoding UTF8 -ErrorAction SilentlyContinue
    if (Test-Path -LiteralPath $Script:AppStrategyFile) {
      $all = @(Get-Content -LiteralPath $Script:AppStrategyFile -Encoding UTF8 -ErrorAction SilentlyContinue)
      if ($all.Count -gt 400) {
        $tail = @($all | Select-Object -Last 400)
        [System.IO.File]::WriteAllLines($Script:AppStrategyFile, $tail, (New-Object System.Text.UTF8Encoding($true)))
      }
    }
    return $record
  } catch {
    return [pscustomobject]@{ error = "$($_.Exception.Message)" }
  }
}

function Invoke-MacroAppProfile {
  param([string[]]$Rest)
  $historyFile=$Script:AppStrategyFile
  $recordRequested=(_Read-Switch -Rest $Rest -Name '--record-strategy') -or (_Read-Switch -Rest $Rest -Name '--remember-strategy')
  $historyEnabled=-not (_Read-Switch -Rest $Rest -Name '--no-strategy-history')
  $jsonOnly=_Read-Switch -Rest $Rest -Name '--json-only'
  $captures=New-Object Collections.ArrayList
  $arguments=@{rest=@($Rest);brief=[bool]$Brief;culture=[Globalization.CultureInfo]::CurrentCulture.Name;history_file=$historyFile;elapsed_ms=0;cdp_elapsed_ms=0;uia_elapsed_ms=0;captured_replies=@()}
  $recordAttempted=$false;$evaluations=0;$facadeCalls=0;$recordCompletion=$null
  $sw=[Diagnostics.Stopwatch]::StartNew()
  for ($probe=0;$probe -le 7;$probe++) {
    if ($null -ne $recordCompletion) { $state=$recordCompletion }
    else {
      if ($facadeCalls -ge 7) { throw 'App-profile exceeded its facade call budget.' }
      $facadeCalls++
      $arguments.captured_replies=@($captures)
      $state=_Invoke-LegacyCompatibility -Operation 'app-profile-advance' -Arguments $arguments
      if ($state.facade -cne 'cucp.app-profile-controller/v1' -or $state.kernel_evaluations -notin @(1,2)) { throw 'Missing app-profile controller validation.' }
      $evaluations += [int]$state.kernel_evaluations
      if ($evaluations -gt 8) { throw 'App-profile exceeded its pure evaluation budget.' }
    }
    if ($state.state -ceq 'error') { throw [string]$state.error }
    if (-not [object]::Equals($Script:AppStrategyFile,$historyFile)) { throw 'App-profile history destination changed during acquisition.' }
    if ($state.state -ceq 'complete') {
      if ($state.queries -isnot [array] -or $state.queries.Count -ne $captures.Count) { throw 'Invalid app-profile completion trace.' }
      $sw.Stop();$elapsed=[int]$sw.Elapsed.TotalMilliseconds
      $state.payload.elapsed_ms=$elapsed
      if ($Brief -and -not $jsonOnly) { [Console]::Out.WriteLine(($state.brief -replace 'elapsed_ms=\d+$',"elapsed_ms=$elapsed")) }
      else { [Console]::Out.WriteLine(($state.payload | ConvertTo-Json -Depth ([int]$state.json_depth))) }
      return [int]$state.exit
    }
    $query=$state.query
    if ($probe -ge 7 -or $state.state -cne 'query' -or $state.queries -isnot [array] -or $state.queries.Count -ne ($captures.Count+1) -or $query.argv -isnot [array]) { throw 'Invalid app-profile acquisition state.' }
    $authorization=$state.record_authorization
    if ($query.kind -ceq 'record') {
      # Independent side-effect gate: user flags, fixed destination, controller
      # preflight, score threshold, matching argv, and no previous append attempt.
      $score=$authorization.strategy_score
      $expectedConfidence=if ($score.total_score -ge 75) {'high'} else {'medium'}
      if (-not $recordRequested -or -not $historyEnabled -or $recordAttempted -or
          $state.kernel_evaluations -ne 2 -or
          $authorization.schema -cne 'cucp.app-profile-record-authorization/v1' -or
          $state.record_completion.state -cne 'complete' -or
          $state.record_completion.payload.schema -cne 'cucp.app-profile/v1' -or
          $state.record_completion.queries.Count -ne ($captures.Count+1) -or
          -not [object]::Equals($authorization.history_file,$historyFile) -or
          ($score.total_score -isnot [int] -and $score.total_score -isnot [long]) -or $score.total_score -lt 50 -or $score.total_score -gt 100 -or
          $score.confidence -cne $expectedConfidence -or $query.argv.Count -ne 8 -or
          -not [string]::Equals((ConvertTo-Json -InputObject @($authorization.query.argv) -Compress),
            (ConvertTo-Json -InputObject @($query.argv) -Compress),[StringComparison]::Ordinal)) {
        throw 'App-profile record lacks a valid explicit authorization.'
      }
      $ready=$state.record_completion
    } elseif ($null -ne $authorization -or $null -ne $state.record_completion -or $state.kernel_evaluations -ne 1) { throw 'Unexpected app-profile record authorization.' }
    if ($query.kind -ceq 'history' -and -not $historyEnabled) { throw 'App-profile history is disabled.' }
    $capture=@{kind=$query.kind;argv=@($query.argv)}
    try {
      switch -CaseSensitive ($query.kind) {
        'windows' {
          if ($query.argv.Count -eq 0) { $capture.result=@(_Enumerate-Win32Windows) }
          else { $capture.result=@(_Enumerate-Win32Windows -Match $query.argv[1]) }
        }
        'cdp_port' {
          $cdpWatch=[Diagnostics.Stopwatch]::StartNew()
          # The original consumes this reply only as an if-condition.
          $capture.result=[bool](Test-CdpPortQuick -Port ([int]$query.argv[0]) -TimeoutMs 120)
          if (-not $capture.result) { $cdpWatch.Stop() }
        }
        'native' { $capture.result=Invoke-NativeHelper -ArgList @('-Action','cdp-detect','-CdpPort',$query.argv[3]);$cdpWatch.Stop() }
        'uia' {
          $uiaWatch=[Diagnostics.Stopwatch]::StartNew()
          $capture.result=@(_Get-UIAffordances -FocusedWindow $query.argv[1] -MaxElements ([int]$query.argv[3]) -MinSize 6 -Hwnd ([int64]$query.argv[7]))
          $uiaWatch.Stop();$arguments.uia_elapsed_ms=[int]$uiaWatch.Elapsed.TotalMilliseconds
        }
        'history' {
          $capture.result=_AppStrategy-LastGood -AppKey $query.argv[0]
          # Remove only runtime Array wrapper metadata before JSON transport.
          # Literal objects with value/Count properties remain ordinary objects.
          if ($capture.result -is [array]) { $capture.result=$capture.result.Clone() }
        }
        'record' {
          $recordAttempted=$true
          $capture.result=_AppStrategy-Append -AppKey $query.argv[0] -AppType $query.argv[1] -Strategy $query.argv[2] -Confidence $query.argv[3] -Score ([int]$query.argv[4]) -Process $query.argv[5] -Class $query.argv[6] -Title $query.argv[7]
          # Preserve the original raw value and PowerShell truth rule. The target,
          # score and all other output were validated before the single write.
          $ready.payload.strategy_persistence.record=$capture.result
          $ready.payload.strategy_persistence.recorded=[bool]($capture.result -and -not $capture.result.error)
          $recordCompletion=$ready
        }
        default { throw 'Unsupported app-profile acquisition kind.' }
      }
    } catch {
      if ($query.kind -ceq 'record') { throw }
      [void]$capture.Remove('result');$capture.error=$_.Exception.Message
    }
    if ($cdpWatch -and -not $cdpWatch.IsRunning) { $arguments.cdp_elapsed_ms=[int]$cdpWatch.Elapsed.TotalMilliseconds }
    [void]$captures.Add($capture)
  }
  throw 'App-profile did not finish within its acquisition bound.'
}

function _Invoke-LegacyReadOnlyQuery {
  param([string[]]$ChildArgs)
  if ($ChildArgs.Count -lt 4 -or $ChildArgs[0] -ne '-Quiet' -or $ChildArgs[1] -ne 'macro' -or
      $ChildArgs[2] -notin @('task-plan','form-plan','smart-plan') -or $ChildArgs[-1] -ne '--json-only') {
    throw 'Invalid readonly planning query descriptor.'
  }
  # Fixed code receives data on stdin and binds the named array in-process.
  # Native powershell -File reparses control-like values as script switches.
  $bootstrap = @'
$ErrorActionPreference='Stop'
$ProgressPreference='SilentlyContinue'
$utf8=New-Object Text.UTF8Encoding($false,$true)
[Console]::OutputEncoding=$utf8
$reader=New-Object IO.StreamReader -ArgumentList @([Console]::OpenStandardInput(),$utf8,$true)
try { $wire=$reader.ReadToEnd() } finally { $reader.Dispose() }
if ($wire.Length -gt 0 -and $wire[0] -eq [char]0xfeff) { $wire=$wire.Substring(1) }
$request=$wire | ConvertFrom-Json
if ($request.schema -ne 'cucp.readonly-plan-query/v1' -or $request.script_path -isnot [string] -or @($request.argv).Count -lt 2 -or $request.argv[0] -ne 'macro' -or $request.argv[1] -notin @('task-plan','form-plan','smart-plan') -or $request.argv[-1] -ne '--json-only' -or @($request.argv | Where-Object { $_ -isnot [string] }).Count -gt 0) { throw 'Invalid readonly planning query.' }
$global:LASTEXITCODE=0
& ([string]$request.script_path) -Quiet -CucpArgs ([string[]]$request.argv)
exit [int]$LASTEXITCODE
'@
  $utf8 = New-Object Text.UTF8Encoding($false,$true)
  $wire = @{schema='cucp.readonly-plan-query/v1';script_path=$PSCommandPath;argv=@($ChildArgs | Select-Object -Skip 1)} | ConvertTo-Json -Depth 6 -Compress
  $bytes = $utf8.GetBytes($wire)
  if ($bytes.Length -gt 1048576) { throw 'Readonly planning query exceeds 1 MiB.' }
  $psi = New-Object Diagnostics.ProcessStartInfo
  $psi.FileName = (Get-Command powershell.exe -CommandType Application -ErrorAction Stop).Source
  $psi.Arguments = '-NoProfile -NonInteractive -ExecutionPolicy Bypass -InputFormat Text -OutputFormat Text -EncodedCommand ' + [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($bootstrap))
  $psi.UseShellExecute = $false
  $psi.RedirectStandardInput = $true; $psi.RedirectStandardOutput = $true; $psi.RedirectStandardError = $true
  $psi.StandardOutputEncoding = $utf8; $psi.StandardErrorEncoding = $utf8
  $process = New-Object Diagnostics.Process
  $process.StartInfo = $psi
  $started = $false
  try {
    $started = $process.Start()
    $stdout = $process.StandardOutput.ReadToEndAsync(); $stderr = $process.StandardError.ReadToEndAsync()
    $process.StandardInput.BaseStream.Write($bytes,0,$bytes.Length)
    $process.StandardInput.Close()
    $process.WaitForExit()
    $out = $stdout.GetAwaiter().GetResult(); $err = $stderr.GetAwaiter().GetResult()
    if ($out.Length -gt 16777216 -or $err.Length -gt 1048576) { throw 'Readonly planning response exceeds its budget.' }
    $raw = (($out + $err) -replace "`r`n", "`n") -replace "`n$", ''
    $obj = $null
    try { $obj = $raw | ConvertFrom-Json -ErrorAction Stop } catch { }
    return [pscustomobject]@{exit=[int]$process.ExitCode;raw=$raw;json=$obj}
  } finally {
    if ($started) { try { if (-not $process.HasExited) { $process.Kill() } } catch { } }
    $process.Dispose()
  }
}

function Invoke-MacroTaskPreset {
  param([string[]]$Rest)
  $jsonOnly = _Read-Switch -Rest $Rest -Name "--json-only"
  $preset = _Invoke-LegacyCompatibility -Operation 'task-preset-prepare' -Arguments @{rest=@($Rest)} -PreserveInvalidArguments
  if ($preset.schema -ne 'cucp.task-preset-preparation/v1' -or $preset.mode -notin @('task','workflow') -or @($preset.queries).Count -ne 1) {
    throw 'Invalid task preset preparation response; no planning query was executed.'
  }
  $query = @($preset.queries)[0]
  function _PresetInvokeJson {
    param([string[]]$ChildArgs)
    return (_Invoke-LegacyReadOnlyQuery -ChildArgs $ChildArgs)
  }

  $elapsed = 0
  if ($preset.mode -eq 'task') {
    $childArgs = @($query.argv)
    if ($query.kind -ne 'task_plan' -or $null -ne $query.rest -or $childArgs.Count -lt 4 -or
        $childArgs[0] -ne '-Quiet' -or $childArgs[1] -ne 'macro' -or $childArgs[2] -ne 'task-plan' -or
        $childArgs[-1] -ne '--json-only' -or @($childArgs | Where-Object { $_ -isnot [string] }).Count -gt 0) {
      throw 'Invalid task preset child query; only the task-plan query is allowed.'
    }
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    $planResult = _PresetInvokeJson -ChildArgs $childArgs
    $sw.Stop()
    $elapsed = [int]$sw.Elapsed.TotalMilliseconds
    $captured = @{exit=[int]$planResult.exit; raw=$planResult.raw; json=$planResult.json}
  } else {
    if ($query.kind -ne 'workflow_plan' -or $null -ne $query.argv -or @($query.rest).Count -eq 0 -or
        @($query.rest | Where-Object { $_ -isnot [string] }).Count -gt 0) {
      throw 'Invalid task preset workflow query.'
    }
    $captured = @{workflow_plan=(_Build-WorkflowPlan -Rest @($query.rest))}
  }
  $payload = _Invoke-LegacyCompatibility -Operation 'task-preset-complete' -Arguments @{rest=@($Rest); captured_query_result=$captured; elapsed_ms=$elapsed} -PreserveInvalidArguments
  if ($payload.schema -ne 'cucp.task-preset/v1' -or $payload.status -notin @('ok','partial') -or $payload.kind -ne $preset.kind) {
    throw 'Invalid task preset completion response.'
  }
  if ($Brief -and -not $jsonOnly) {
    if ($preset.mode -eq 'workflow') {
      [Console]::Out.WriteLine("$($payload.status) task-preset kind=$($payload.kind) mode=workflow steps=$(@($preset.workflow_steps).Count)")
    } else {
      [Console]::Out.WriteLine("$($payload.status) task-preset kind=$($payload.kind) task_plan_exit=$($payload.task_plan_exit) elapsed_ms=$($payload.elapsed_ms)")
    }
  } else {
    [Console]::Out.WriteLine(($payload | ConvertTo-Json -Depth 18))
  }
  if ($payload.status -eq 'ok') { return 0 }
  return 2
}

function Invoke-MacroTaskPlan {
  param([string[]]$Rest)
  $jsonOnly = _Read-Switch -Rest $Rest -Name '--json-only'
  $prepared = _Invoke-LegacyCompatibility -Operation 'task-plan-prepare' -Arguments @{rest=@($Rest)} -PreserveInvalidArguments
  if ($prepared.schema -ne 'cucp.task-plan-preparation/v1' -or $prepared.queries -isnot [System.Array]) { throw 'Invalid task planning preparation response.' }
  function _InvokeTaskChildJson {
    param([string[]]$ChildArgs)
    return (_Invoke-LegacyReadOnlyQuery -ChildArgs $ChildArgs)
  }
  $sw = [Diagnostics.Stopwatch]::StartNew()
  $captured = New-Object Collections.ArrayList
  foreach ($query in $prepared.queries) {
    if ($query.kind -isnot [string] -or $query.argv -isnot [System.Array] -or @($query.argv | Where-Object { $_ -isnot [string] }).Count -gt 0) { throw 'Invalid planning query field types.' }
    $argv = @($query.argv)
    $macro = if ($query.kind -eq 'form_plan') { 'form-plan' } elseif ($query.kind -eq 'smart_plan') { 'smart-plan' } else { $null }
    if (-not $macro -or $argv.Count -lt 6 -or $argv[0] -ne '-Quiet' -or $argv[1] -ne 'macro' -or $argv[2] -ne $macro -or $argv[-1] -ne '--json-only') { throw 'Invalid task planning query descriptor.' }
    $reply = _InvokeTaskChildJson -ChildArgs $argv
    [void]$captured.Add(@{kind=$query.kind;argv=$argv;exit=[int]$reply.exit;raw=[string]$reply.raw;json=$reply.json})
  }
  $assembly = _Invoke-LegacyCompatibility -Operation 'task-plan-assemble' -Arguments @{rest=@($Rest);captured_query_results=@($captured)} -PreserveInvalidArguments
  if ($assembly.schema -ne 'cucp.task-plan-assembly/v1' -or $assembly.workflow_required -isnot [bool] -or $assembly.workflow_rest -isnot [System.Array] -or @($assembly.workflow_rest | Where-Object { $_ -isnot [string] }).Count -gt 0) { throw 'Invalid task workflow assembly response.' }
  $workflowPlan = $null
  if ($assembly.workflow_required) { $workflowPlan = _Build-WorkflowPlan -Rest @($assembly.workflow_rest) }
  $sw.Stop()
  $payload = _Invoke-LegacyCompatibility -Operation 'task-plan-complete' -Arguments @{rest=@($Rest);captured_query_results=@($captured);captured_workflow_plan=$workflowPlan;elapsed_ms=[int]$sw.Elapsed.TotalMilliseconds} -PreserveInvalidArguments
  if ($payload.schema -ne 'cucp.task-plan/v1' -or $payload.safe_to_run -isnot [bool] -or $payload.status -notin @('ok','partial') -or (($payload.status -eq 'ok') -ne $payload.safe_to_run)) { throw 'Invalid task planning completion response.' }
  if ($Brief -and -not $jsonOnly) {
    [Console]::Out.WriteLine("$($payload.status) task-plan steps=$($payload.step_count) live=$($payload.live_step_count) errors=$(@($payload.errors).Count) elapsed_ms=$($payload.elapsed_ms)")
  } else { [Console]::Out.WriteLine(($payload | ConvertTo-Json -Depth 18)) }
  if ($payload.safe_to_run) { return 0 }
  return 2
}

function Invoke-MacroTaskRun {param([string[]]$Rest) return _Invoke-LegacyExecutionFamily -Operation 'task-run' -Rest $Rest -ScriptPath $PSCommandPath}

function Invoke-MacroFormPlan {
  param([string[]]$Rest)
  $jsonOnly = _Read-Switch -Rest $Rest -Name '--json-only'
  $prepared = _Invoke-LegacyCompatibility -Operation 'form-plan-prepare' -Arguments @{rest=@($Rest)} -PreserveInvalidArguments
  if ($prepared.schema -ne 'cucp.form-plan-preparation/v1' -or $prepared.queries -isnot [System.Array]) { throw 'Invalid form planning preparation response.' }
  function _InvokeChildSmartPlanJson {
    param([string[]]$PlanArgs)
    return (_Invoke-LegacyReadOnlyQuery -ChildArgs (@('-Quiet','macro','smart-plan') + $PlanArgs + @('--json-only')))
  }
  $sw = [Diagnostics.Stopwatch]::StartNew()
  $captured = New-Object Collections.ArrayList
  foreach ($query in $prepared.queries) {
    if ($query.kind -isnot [string] -or $query.argv -isnot [System.Array] -or @($query.argv | Where-Object { $_ -isnot [string] }).Count -gt 0) { throw 'Invalid planning query field types.' }
    $argv = @($query.argv)
    if ($query.kind -ne 'smart_plan' -or $argv.Count -lt 6 -or $argv[0] -ne '-Quiet' -or $argv[1] -ne 'macro' -or $argv[2] -ne 'smart-plan' -or $argv[-1] -ne '--json-only') { throw 'Invalid form planning query descriptor.' }
    $reply = _InvokeChildSmartPlanJson -PlanArgs @($argv[3..($argv.Count - 2)])
    [void]$captured.Add(@{kind=$query.kind;argv=$argv;exit=[int]$reply.exit;raw=[string]$reply.raw;json=$reply.json})
  }
  $sw.Stop()
  $payload = _Invoke-LegacyCompatibility -Operation 'form-plan-complete' -Arguments @{rest=@($Rest);captured_query_results=@($captured);elapsed_ms=[int]$sw.Elapsed.TotalMilliseconds} -PreserveInvalidArguments
  if ($payload.schema -ne 'cucp.form-plan/v1' -or $payload.safe_to_act -isnot [bool] -or $payload.status -notin @('ok','partial') -or (($payload.status -eq 'ok') -ne $payload.safe_to_act)) { throw 'Invalid form planning completion response.' }
  if ($Brief -and -not $jsonOnly) {
    if ($payload.safe_to_act) { [Console]::Out.WriteLine("ok form-plan steps=$($payload.step_count) safe=$($payload.safe_step_count) match='$($payload.match)' elapsed_ms=$($payload.elapsed_ms)") }
    else { [Console]::Out.WriteLine("partial form-plan steps=$($payload.step_count) safe=$($payload.safe_step_count) errors=$(@($payload.errors).Count) match='$($payload.match)' elapsed_ms=$($payload.elapsed_ms)") }
  } else { [Console]::Out.WriteLine(($payload | ConvertTo-Json -Depth 16)) }
  if ($payload.safe_to_act) { return 0 }
  return 2
}

function Invoke-MacroFormRun {param([string[]]$Rest) return _Invoke-LegacyExecutionFamily -Operation 'form-run' -Rest $Rest -ScriptPath $PSCommandPath}

function Invoke-MacroSmartClick {param([string[]]$Rest) return _Invoke-LegacyExecutionFamily -Operation 'smart-click' -Rest $Rest -ScriptPath $PSCommandPath}

# ============================================================================
# macro watch ─ 연속 관찰 모드 (continuous observation)
# ============================================================================
# 매 액션 후 자동으로 UIA refresh + foreground 변화 감지.
# 자율 작업 시 화면이 바뀐 줄 모르고 캐시된 좌표로 재시도하는 문제 방지.
#
# 사용 예:
#   macro watch --interval-ms 500 --max-cycles 20 --until-label "Saved"
#
# 매 cycle마다 brief 한 줄 emit:
#   cycle=N foreground='...' delta=changed/same affordance_count=M
# ============================================================================

function Invoke-MacroWatch {param([string[]]$Rest) return _Invoke-LegacyExecutionFamily -Operation 'watch' -Rest $Rest -ScriptPath $PSCommandPath}

# ============================================================================
# OCR 매크로 (Windows.Media.Ocr) — 브라우저 캔버스/이미지 표면 커버
# ============================================================================
# UIA로 안 잡히는 표면(브라우저 canvas, Electron 커스텀 그리기, PDF 이미지,
# 게임 UI 일부)을 OCR로 텍스트+좌표 추출해서 클릭/검색합니다.
#
# 주의: OCR은 BoundingRectangle 정확도가 폰트 크기/대비/회전/언어팩에 의존합니다.
#       UIA가 가능하면 항상 UIA Pattern (uia-invoke / smart-click) 우선 사용.
# ============================================================================

# macro ocr-screen [--region x,y,w,h] [--language ko]
# 화면 영역 캡처 + OCR. read-only.
function Invoke-MacroOcrScreen {
  param([string[]]$Rest)
  $region = _Read-OptValue -Rest $Rest -Name "--region"
  $lang = _Read-OptValue -Rest $Rest -Name "--language"
  $args = @("-Action","ocr-screen")
  if ($region) {
    # "x,y,w,h" 형식
    $parts = $region -split ','
    if ($parts.Count -eq 4) {
      $args += @("-ScreenshotX",$parts[0].Trim(),"-ScreenshotY",$parts[1].Trim(),
                 "-ScreenshotW",$parts[2].Trim(),"-ScreenshotH",$parts[3].Trim())
    }
  }
  if ($lang) { $args += @("-OcrLanguage", $lang) }
  $r = Invoke-NativeHelper -ArgList $args
  if ($Brief) {
    if ($r.Json -and $r.Json.status -eq "ok") {
      [Console]::Out.WriteLine("ok ocr-screen lines=$($r.Json.line_count) words=$($r.Json.word_count) language=$($r.Json.engine_language) elapsed_ms=$($r.ElapsedMs)")
    } else {
      [Console]::Out.WriteLine("err ocr-screen reason=$($r.Json.reason) exit=$($r.ExitCode)")
    }
  } else {
    if ($r.Raw) { [Console]::Out.Write($r.Raw) }
  }
  return $r.ExitCode
}

# macro ocr-image --path <png> [--language ko]
# 임의 PNG 파일 OCR. read-only. 좌표는 이미지 픽셀 기준.
function Invoke-MacroOcrImage {
  param([string[]]$Rest)
  $path = _Read-OptValue -Rest $Rest -Name "--path"
  $lang = _Read-OptValue -Rest $Rest -Name "--language"
  if (-not $path) { throw "macro ocr-image requires --path <png>" }
  $args = @("-Action","ocr-image","-OcrPath",$path)
  if ($lang) { $args += @("-OcrLanguage", $lang) }
  $r = Invoke-NativeHelper -ArgList $args
  if ($Brief) {
    if ($r.Json -and $r.Json.status -eq "ok") {
      [Console]::Out.WriteLine("ok ocr-image path='$path' lines=$($r.Json.line_count) words=$($r.Json.word_count) language=$($r.Json.engine_language) elapsed_ms=$($r.ElapsedMs)")
    } else {
      [Console]::Out.WriteLine("err ocr-image path='$path' reason=$($r.Json.reason) exit=$($r.ExitCode)")
    }
  } else {
    if ($r.Raw) { [Console]::Out.Write($r.Raw) }
  }
  return $r.ExitCode
}

# macro ocr-find-text --text <s> [--match contains|exact|prefix|fuzzy] [--region x,y,w,h]
#                     [--path <png>] [--target-match <window>] [--language ko] [--max-candidates N]
# 화면(또는 이미지)에서 텍스트 위치 찾기. read-only.
# 출력: top 후보의 (cx,cy) 클릭 좌표 + score
function Invoke-MacroOcrFindText {
  param([string[]]$Rest)
  $text = _Read-OptValue -Rest $Rest -Name "--text"
  $match = _Read-OptValue -Rest $Rest -Name "--match"
  $region = _Read-OptValue -Rest $Rest -Name "--region"
  $path = _Read-OptValue -Rest $Rest -Name "--path"
  $targetMatch = _Read-OptValue -Rest $Rest -Name "--target-match"
  $lang = _Read-OptValue -Rest $Rest -Name "--language"
  $maxN = [int](_Read-OptValue -Rest $Rest -Name "--max-candidates")
  if (-not $text) { throw "macro ocr-find-text requires --text" }
  if (-not $match) { $match = "contains" }
  $args = @("-Action","ocr-find-text","-OcrText",$text,"-OcrMatch",$match)
  if ($maxN -gt 0) { $args += @("-OcrMaxCandidates","$maxN") }
  if ($lang) { $args += @("-OcrLanguage", $lang) }
  if ($path) { $args += @("-OcrPath", $path) }
  elseif ($targetMatch) { $args += @("-Match", $targetMatch) }
  if ($region) {
    $parts = $region -split ','
    if ($parts.Count -eq 4) {
      $args += @("-ScreenshotX",$parts[0].Trim(),"-ScreenshotY",$parts[1].Trim(),
                 "-ScreenshotW",$parts[2].Trim(),"-ScreenshotH",$parts[3].Trim())
    }
  }
  $r = Invoke-NativeHelper -ArgList $args
  if ($Brief) {
    if ($r.Json -and $r.Json.status -eq "ok") {
      $top = $r.Json.top
      [Console]::Out.WriteLine("ok ocr-find-text '$text' match='$match' top='$($top.text)' score=$($top.score) cx=$($top.cx) cy=$($top.cy) candidates=$($r.Json.candidate_count) elapsed_ms=$($r.ElapsedMs)")
    } else {
      [Console]::Out.WriteLine("partial ocr-find-text '$text' reason=$($r.Json.reason) exit=$($r.ExitCode)")
    }
  } else {
    if ($r.Raw) { [Console]::Out.Write($r.Raw) }
  }
  return $r.ExitCode
}

# macro ocr-click --text <s> [--match contains|exact|prefix|fuzzy] [--region x,y,w,h]
#                 [--button left|right|double] [--language ko] [--min-score 70] [--target-match <window>]
# OCR로 텍스트 좌표 찾고 click. -AllowLiveControl 필수 (라이브 actuation).
# 안전 정책:
#   - min-score 미달 → partial(2) 거부
#   - top 후보 없음 → partial(2) 거부
function Invoke-MacroOcrClick {param([string[]]$Rest) return _Invoke-LegacyInteractionFamily -Operation 'ocr-click' -Rest $Rest -ScriptPath $PSCommandPath}

# ============================================================================
# v0.9.0 — OCR+UIA fusion + screenshot diff verify
# ============================================================================
# 핵심 통찰:
#   1. OCR 이 보지만 UIA 가 비어있는 element (Electron 일부) → fuse 로 InvokePattern 호출 가능
#   2. 좌표 클릭은 "정말 통했는지" 모름 → 클릭 전후 스크린샷 diff 로 검증
# 두 매크로는 read-only 이지만 click-and-verify-screen 은 actuation 매크로.
# ============================================================================

# macro ocr-uia-fuse --text <s> [--match contains|exact|prefix|fuzzy] [--match-window <s>]
#                    [--region x,y,w,h] [--language ko]
# OCR 1순위 좌표 위에 UIA element 가 있으면 invoke 패턴 가능 여부 보고 (read-only).
function Invoke-MacroOcrUiaFuse {
  param([string[]]$Rest)
  $text = _Read-OptValue -Rest $Rest -Name "--text"
  $match = _Read-OptValue -Rest $Rest -Name "--match"
  $matchWindow = _Read-OptValue -Rest $Rest -Name "--match-window"
  $region = _Read-OptValue -Rest $Rest -Name "--region"
  $lang = _Read-OptValue -Rest $Rest -Name "--language"
  if (-not $text) { throw "macro ocr-uia-fuse requires --text" }
  if (-not $match) { $match = "contains" }
  $argList = @("-Action","ocr-uia-fuse","-OcrText",$text,"-OcrMatch",$match)
  if ($matchWindow) { $argList += @("-Match", $matchWindow) }
  if ($lang) { $argList += @("-OcrLanguage", $lang) }
  if ($region) {
    $parts = $region -split ','
    if ($parts.Count -eq 4) {
      $argList += @("-ScreenshotX",$parts[0].Trim(),"-ScreenshotY",$parts[1].Trim(),
                    "-ScreenshotW",$parts[2].Trim(),"-ScreenshotH",$parts[3].Trim())
    }
  }
  $r = Invoke-NativeHelper -ArgList $argList
  $exitCode = [int]$r.ExitCode
  if ($Brief) {
    if ($r.Json -and $r.Json.status -eq "ok") {
      $rec = $r.Json.recommendation
      $canI = $r.Json.can_invoke
      $pat = "n/a"
      if ($r.Json.invoke_pattern) { $pat = $r.Json.invoke_pattern }
      $top = $r.Json.ocr_top
      [Console]::Out.WriteLine("ok ocr-uia-fuse '$text' top='$($top.text)' score=$($top.score) can_invoke=$canI pattern=$pat recommend=$rec elapsed_ms=$($r.ElapsedMs)")
    } else {
      [Console]::Out.WriteLine("partial ocr-uia-fuse '$text' reason=$($r.Json.reason) recommend=$($r.Json.recommendation)")
    }
  } else {
    if ($r.Raw) { [Console]::Out.Write($r.Raw) }
  }
  return $exitCode
}

# macro ocr-uia-invoke --text <s> [--match contains|exact|prefix|fuzzy] [--match-window <s>]
#                      [--language ko]
# OCR 좌표 위 UIA element 를 한 프로세스 안에서 직접 InvokePattern.Invoke().
# 마우스 안 움직임. UIA Name 비어있어도 AutomationId / ClassName 으로 invoke.
# -AllowLiveControl 필수 (실제 actuation).
function Invoke-MacroOcrUiaInvoke {
  param([string[]]$Rest)
  if (-not $AllowLiveControl) { throw "macro ocr-uia-invoke requires -AllowLiveControl" }
  $text = _Read-OptValue -Rest $Rest -Name "--text"
  $match = _Read-OptValue -Rest $Rest -Name "--match"
  $matchWindow = _Read-OptValue -Rest $Rest -Name "--match-window"
  $lang = _Read-OptValue -Rest $Rest -Name "--language"
  if (-not $text) { throw "macro ocr-uia-invoke requires --text" }
  if (-not $match) { $match = "contains" }
  $argList = @("-Action","ocr-uia-invoke","-OcrText",$text,"-OcrMatch",$match)
  if ($matchWindow) { $argList += @("-Match", $matchWindow) }
  if ($lang) { $argList += @("-OcrLanguage", $lang) }
  $r = Invoke-NativeHelper -ArgList $argList
  $exitCode = [int]$r.ExitCode
  _Trajectory-Append -Kind "click" -Payload @{
    source = "ocr_uia_invoke"
    text = $text
    method = "$($r.Json.method)"
    uia_name = "$($r.Json.uia_name)"
    uia_automation_id = "$($r.Json.uia_automation_id)"
    exit = $exitCode
  }
  if ($Brief) {
    if ($r.Json -and $r.Json.status -eq "ok") {
      $idLabel = "n/a"
      if ($r.Json.uia_name) { $idLabel = "name='$($r.Json.uia_name)'" }
      elseif ($r.Json.uia_automation_id) { $idLabel = "id='$($r.Json.uia_automation_id)'" }
      elseif ($r.Json.uia_class_name) { $idLabel = "class='$($r.Json.uia_class_name)'" }
      [Console]::Out.WriteLine("ok ocr-uia-invoke '$text' method=$($r.Json.method) $idLabel score=$($r.Json.ocr_score) mouse_moved=False elapsed_ms=$($r.ElapsedMs)")
    } else {
      [Console]::Out.WriteLine("partial ocr-uia-invoke '$text' reason=$($r.Json.reason) exit=$exitCode")
    }
  } else {
    if ($r.Raw) { [Console]::Out.Write($r.Raw) }
  }
  return $exitCode
}

# macro screenshot-diff --before <png> --after <png> [--threshold N]
#                       [--region x,y,w,h] [--ignore-region "x,y,w,h;x2,y2,w2,h2"]
# 두 PNG 의 픽셀 변화 비율 측정. read-only.
# v1.0.0: --ignore-region 으로 동영상/애니메이션 영역 마스킹 (false positive 방지)
function Invoke-MacroScreenshotDiff {
  param([string[]]$Rest)
  $before = _Read-OptValue -Rest $Rest -Name "--before"
  $after  = _Read-OptValue -Rest $Rest -Name "--after"
  $thr    = [int](_Read-OptValue -Rest $Rest -Name "--threshold")
  $region = _Read-OptValue -Rest $Rest -Name "--region"
  $ignore = _Read-OptValue -Rest $Rest -Name "--ignore-region"
  if (-not $before -or -not $after) { throw "macro screenshot-diff requires --before and --after" }
  $argList = @("-Action","screenshot-diff","-DiffBefore",$before,"-DiffAfter",$after)
  if ($thr -gt 0) { $argList += @("-DiffThreshold","$thr") }
  if ($ignore) { $argList += @("-DiffIgnoreRegions", $ignore) }
  if ($region) {
    $parts = $region -split ','
    if ($parts.Count -eq 4) {
      $argList += @("-ScreenshotX",$parts[0].Trim(),"-ScreenshotY",$parts[1].Trim(),
                    "-ScreenshotW",$parts[2].Trim(),"-ScreenshotH",$parts[3].Trim())
    }
  }
  $r = Invoke-NativeHelper -ArgList $argList
  $exitCode = [int]$r.ExitCode
  if ($Brief) {
    if ($r.Json -and $r.Json.status -eq "ok") {
      $ignoredHint = ""
      if ($r.Json.ignored_pixels -gt 0) { $ignoredHint = " ignored=$($r.Json.ignored_pixels)" }
      [Console]::Out.WriteLine("ok screenshot-diff changed=$($r.Json.changed) ratio=$($r.Json.changed_ratio) pixels=$($r.Json.changed_pixels)/$($r.Json.effective_pixels)$ignoredHint elapsed_ms=$($r.ElapsedMs)")
    } else {
      [Console]::Out.WriteLine("err screenshot-diff reason=$($r.Json.reason) exit=$exitCode")
    }
  } else {
    if ($r.Raw) { [Console]::Out.Write($r.Raw) }
  }
  return $exitCode
}

# macro click-and-verify-screen --x <n> --y <n> [--button left|right|double]
#                               [--region x,y,w,h] [--threshold N] [--wait-ms N]
# 화면 캡처 → 클릭 → 대기 → 다시 캡처 → diff 로 변화 확인.
# 변화 없으면 partial(2) 반환 → 클릭이 안 통했다는 확실한 증거.
# -AllowLiveControl 필수.
function Invoke-MacroClickAndVerifyScreen {
  param([string[]]$Rest)
  if (-not $AllowLiveControl) { throw "macro click-and-verify-screen requires -AllowLiveControl" }
  $x = [int](_Read-OptValue -Rest $Rest -Name "--x")
  $y = [int](_Read-OptValue -Rest $Rest -Name "--y")
  $btn = _Read-OptValue -Rest $Rest -Name "--button"
  if (-not $btn) { $btn = "left" }
  $thr = [int](_Read-OptValue -Rest $Rest -Name "--threshold")
  $waitMs = [int](_Read-OptValue -Rest $Rest -Name "--wait-ms")
  $region = _Read-OptValue -Rest $Rest -Name "--region"
  if ($x -le 0 -or $y -le 0) { throw "macro click-and-verify-screen requires --x and --y" }
  if ($waitMs -le 0) { $waitMs = 500 }
  if ($thr -le 0) { $thr = 16 }

  # diff 영역 — 명시 없으면 클릭 좌표 주변 200x200 사각형 (작은 변화도 잡기 좋게)
  $rx = $x - 100; $ry = $y - 100; $rw = 200; $rh = 200
  if ($region) {
    $parts = $region -split ','
    if ($parts.Count -eq 4) {
      $rx = [int]$parts[0].Trim(); $ry = [int]$parts[1].Trim()
      $rw = [int]$parts[2].Trim(); $rh = [int]$parts[3].Trim()
    }
  }
  if ($rx -lt 0) { $rx = 0 }
  if ($ry -lt 0) { $ry = 0 }

  $tag = (Get-Date).ToString("HHmmss-fff")
  $beforePng = Join-Path $Script:CacheDir ("verify-before-$tag.png")
  $afterPng  = Join-Path $Script:CacheDir ("verify-after-$tag.png")

  # 1) before 캡처
  $rB = Invoke-NativeHelper -ArgList @("-Action","screenshot","-OutPath",$beforePng,
       "-ScreenshotX","$rx","-ScreenshotY","$ry","-ScreenshotW","$rw","-ScreenshotH","$rh")
  if (-not ($rB.Json -and $rB.Json.status -eq "ok")) {
    Remove-Item -LiteralPath $beforePng -Force -ErrorAction SilentlyContinue
    if ($Brief) { [Console]::Out.WriteLine("err click-and-verify-screen capture_before_failed") }
    return 1
  }

  # 2) 클릭
  $rC = Invoke-NativeHelper -ArgList @("-Action","click","-X","$x","-Y","$y","-Button",$btn)
  _Trajectory-Append -Kind "click" -Payload @{
    source = "click_and_verify_screen"; x = $x; y = $y; button = $btn; exit = $rC.ExitCode
  }

  # 3) 대기
  Start-Sleep -Milliseconds $waitMs

  # 4) after 캡처 (절대 좌표 동일 영역)
  $rA = Invoke-NativeHelper -ArgList @("-Action","screenshot","-OutPath",$afterPng,
       "-ScreenshotX","$rx","-ScreenshotY","$ry","-ScreenshotW","$rw","-ScreenshotH","$rh")
  if (-not ($rA.Json -and $rA.Json.status -eq "ok")) {
    Remove-Item -LiteralPath $beforePng,$afterPng -Force -ErrorAction SilentlyContinue
    if ($Brief) { [Console]::Out.WriteLine("err click-and-verify-screen capture_after_failed") }
    return 1
  }

  # 5) diff
  $rD = Invoke-NativeHelper -ArgList @("-Action","screenshot-diff",
       "-DiffBefore",$beforePng,"-DiffAfter",$afterPng,"-DiffThreshold","$thr")
  Remove-Item -LiteralPath $beforePng,$afterPng -Force -ErrorAction SilentlyContinue

  if (-not ($rD.Json -and $rD.Json.status -eq "ok")) {
    if ($Brief) { [Console]::Out.WriteLine("err click-and-verify-screen diff_failed") }
    return 1
  }
  $changed = [bool]$rD.Json.changed
  $ratio = $rD.Json.changed_ratio

  if ($Brief) {
    if ($changed) {
      [Console]::Out.WriteLine("ok click-and-verify-screen @($x,$y) changed=True ratio=$ratio elapsed_ms=$($rD.ElapsedMs)")
    } else {
      [Console]::Out.WriteLine("partial click-and-verify-screen @($x,$y) changed=False ratio=$ratio click_likely_missed")
    }
  } else {
    [Console]::Out.WriteLine(([pscustomobject]@{
      schema = "cucp.click-verify/v1"
      status = if ($changed) { "ok" } else { "partial" }
      x = $x; y = $y; button = $btn
      changed = $changed
      changed_ratio = $ratio
      changed_pixels = $rD.Json.changed_pixels
      total_pixels = $rD.Json.total_pixels
      threshold = $thr
      wait_ms = $waitMs
      diff_region = [ordered]@{ x=$rx; y=$ry; width=$rw; height=$rh }
    } | ConvertTo-Json -Depth 4))
  }
  if (-not $changed) { return 2 }
  return 0
}

# ============================================================================
# Auto-do: self-correcting click loop (라벨 → 위치 변경 시 vision 재시도)
# ============================================================================

function Invoke-MacroAutoDo {
  param([string[]]$Rest)
  $label = _Read-OptValue -Rest $Rest -Name "--label"
  $describe = _Read-OptValue -Rest $Rest -Name "--describe"
  $window = _Read-OptValue -Rest $Rest -Name "--window"
  $maxAttempts = [int](_Read-OptValue -Rest $Rest -Name "--max-attempts")
  $verifyLabel = _Read-OptValue -Rest $Rest -Name "--verify-label"
  $verifyTimeout = [int](_Read-OptValue -Rest $Rest -Name "--verify-timeout-ms")
  if (-not $label -and -not $describe) { throw "macro auto-do requires --label or --describe" }
  if (-not $AllowLiveControl) { throw "macro auto-do requires -AllowLiveControl" }
  if ($maxAttempts -le 0) { $maxAttempts = 3 }
  if ($verifyTimeout -le 0) { $verifyTimeout = 5000 }

  $strategies = @()
  if ($label) { $strategies += "label" }
  if ($label) { $strategies += "vision_label" }  # vision with label as description
  if ($describe) { $strategies += "vision_describe" }
  if (-not $describe -and $label) {
    # auto-build a vision-friendly description
    $describe = "the $label button or element"
    $strategies += "vision_describe"
  }

  $attempt = 0
  $success = $false
  $usedStrategy = ""
  foreach ($strategy in $strategies) {
    if ($success) { break }
    $attempt++
    if ($attempt -gt $maxAttempts) { break }

    Write-Notice -Level "INFO" -Message "auto-do 시도 ${attempt}/$maxAttempts (전략=$strategy)"
    $exitCode = 1

    if ($strategy -eq "label") {
      $args = @("macro", "click-label", "--label", $label, "--no-vision")
      if ($window) { $args += @("--window", $window) }
      $r = Invoke-Cucp -ArgList $args
      $exitCode = $r.ExitCode
    } elseif ($strategy -eq "vision_label") {
      # click-label with vision fallback enabled
      $args = @("macro", "click-label", "--label", $label)
      if ($window) { $args += @("--window", $window) }
      $r = Invoke-Cucp -ArgList $args
      $exitCode = $r.ExitCode
    } elseif ($strategy -eq "vision_describe") {
      $args = @("macro", "vision-click", "--describe", $describe)
      if ($window) { $args += @("--window", $window) }
      $r = Invoke-Cucp -ArgList $args
      $exitCode = $r.ExitCode
    }

    if ($exitCode -eq 0) {
      # Optional verify-label
      if ($verifyLabel) {
        $vargs = @("macro", "wait-label", "--label", $verifyLabel, "--timeout-ms", "$verifyTimeout")
        if ($window) { $vargs += @("--window", $window) }
        $vr = Invoke-Cucp -ArgList $vargs
        if ($vr.ExitCode -eq 0) { $success = $true; $usedStrategy = $strategy }
      } else {
        $success = $true; $usedStrategy = $strategy
      }
    }
  }

  _Trajectory-Append -Kind "auto_do" -Payload @{
    label = $label
    describe = $describe
    window = $window
    attempts = $attempt
    success = $success
    used_strategy = $usedStrategy
  }

  if ($Brief) {
    if ($success) { [Console]::Out.WriteLine("ok auto-do '$label' attempts=$attempt strategy=$usedStrategy") }
    else { [Console]::Out.WriteLine("err auto-do '$label' attempts=$attempt all-strategies-failed") }
  }
  if ($success) { return 0 } else { return 2 }
}

# ============================================================================
# Standardized exit code reference (printed in help, used in trajectory):
#   0   ok
#   1   generic failure / wrapper-side error
#   2   partial / verification failed (e.g. evidence partial, verify-label miss)
#   3   live-control blocked (no -AllowLiveControl)
#   4   coordinate without --after observation
#   124 timeout (Process killed by InvokeTimeoutMs)
# ============================================================================

# ============================================================================
# Trajectory store (working memory) -- persistent NDJSON of recent observations
# and actions. Lets the model recall the last N steps without re-observing.
# ============================================================================

$Script:TrajectoryFile = Join-Path $Script:AuditDir "trajectory.ndjson"
$Script:TrajectoryMax = 200

# v1.1.0: smart-click history learning
# 같은 (label, match) 의 과거 시도 결과를 기억해서 다음 호출 시 가장 자주 성공한
# strategy 부터 시도. cascade 의 앞 단계를 skip 해서 평균 응답 시간 단축.
# 안전: history 가 없거나 corrupt 면 무시 (기존 cascade 그대로). --no-history 로 비활성화.
$Script:HistoryFile = Join-Path $Script:AuditDir "smart-click-history.ndjson"
$Script:HistoryMax = 1000  # rotate 한도 — 1000 라인 넘으면 최신 800개만 유지
$Script:AnchorHistoryFile = Join-Path $Script:AuditDir "coord-anchor-history.ndjson"
$Script:AnchorHistoryMax = 500
$Script:AppStrategyFile = Join-Path $Script:AuditDir "app-strategy-history.ndjson"

function _Trajectory-Append {
  param([string]$Kind, [hashtable]$Payload)
  try {
    $entry = @{
      ts = (Get-Date).ToString("o")
      kind = $Kind
    }
    foreach ($k in $Payload.Keys) { $entry[$k] = $Payload[$k] }
    $line = ($entry | ConvertTo-Json -Compress -Depth 6)
    Add-Content -LiteralPath $Script:TrajectoryFile -Value $line -Encoding UTF8 -ErrorAction SilentlyContinue
    # Trim to TrajectoryMax lines
    if (Test-Path -LiteralPath $Script:TrajectoryFile) {
      $info = Get-Item -LiteralPath $Script:TrajectoryFile
      if ($info.Length -gt 1MB) {
        $all = Get-Content -LiteralPath $Script:TrajectoryFile -Encoding UTF8
        if ($all.Count -gt $Script:TrajectoryMax) {
          $tail = $all[($all.Count - $Script:TrajectoryMax)..($all.Count - 1)]
          [System.IO.File]::WriteAllLines($Script:TrajectoryFile, $tail, (New-Object System.Text.UTF8Encoding($true)))
        }
      }
    }
  } catch { }
}

function _Trajectory-Read {
  param([int]$Last = 20)
  if (-not (Test-Path -LiteralPath $Script:TrajectoryFile)) { return @() }
  $all = Get-Content -LiteralPath $Script:TrajectoryFile -Encoding UTF8 -ErrorAction SilentlyContinue
  if (-not $all) { return @() }
  $start = [Math]::Max(0, $all.Count - $Last)
  $tail = $all[$start..($all.Count - 1)]
  $parsed = @()
  foreach ($l in $tail) {
    try { $parsed += ($l | ConvertFrom-Json -ErrorAction Stop) } catch { }
  }
  return $parsed
}

function _Trajectory-Clear {
  if (Test-Path -LiteralPath $Script:TrajectoryFile) {
    Remove-Item -LiteralPath $Script:TrajectoryFile -Force -ErrorAction SilentlyContinue
  }
}

# ============================================================================
# v1.1.0 — smart-click history learning
# ============================================================================
# 모든 smart-click 시도를 NDJSON 으로 기록하고, 같은 (label, match) 의 최근 N 회
# 결과를 통계로 만들어 다음 호출에 "어느 stage 부터 시도해야 빨리 성공할까" 가이드.
#
# Append 레코드 형식:
#   {"ts":"2026-05-25T...","label":"Save","match":"Notepad","strategy":"uia_pattern",
#    "success":true,"elapsed_ms":1024}
#
# 통계 로직 (_History-PickBestStrategy):
#   - 같은 (label, match) 매칭 최근 5건 조회
#   - success=true 인 것들의 strategy 중 가장 자주 등장한 것 반환
#   - 동률 시 더 최근 것 우선
#   - 5건 모두 fail 이면 $null 반환 (기존 cascade 처음부터)
# ============================================================================

# 한 번의 smart-click 결과 append. 1MB / HistoryMax 라인 넘으면 자동 rotate.
function _History-Append {
  param(
    [string]$Label,
    [string]$Match,
    [string]$Strategy,
    [bool]$Success,
    [int]$ElapsedMs
  )
  try {
    $entry = [ordered]@{
      ts = (Get-Date).ToString("o")
      label = $Label
      match = $Match
      strategy = $Strategy
      success = $Success
      elapsed_ms = $ElapsedMs
    }
    $line = ($entry | ConvertTo-Json -Compress -Depth 4)
    Add-Content -LiteralPath $Script:HistoryFile -Value $line -Encoding UTF8 -ErrorAction SilentlyContinue

    # rotate: 1MB 또는 HistoryMax 초과 시 최신 (HistoryMax * 0.8) 만 유지
    if (Test-Path -LiteralPath $Script:HistoryFile) {
      $info = Get-Item -LiteralPath $Script:HistoryFile
      if ($info.Length -gt 1MB) {
        $all = Get-Content -LiteralPath $Script:HistoryFile -Encoding UTF8
        if ($all.Count -gt $Script:HistoryMax) {
          $keep = [int]($Script:HistoryMax * 0.8)
          $tail = $all[($all.Count - $keep)..($all.Count - 1)]
          [System.IO.File]::WriteAllLines($Script:HistoryFile, $tail, (New-Object System.Text.UTF8Encoding($true)))
        }
      }
    }
  } catch { }
}

# 같은 (label, match) 의 최근 N 회 시도를 읽어 후보 strategy 반환.
# 반환값:
#   - $null  → history 없음 / 모두 실패 / 학습 비활성
#   - string → 추천 strategy 이름 (예: "uia_pattern", "fusion_uia_invoke")
function _History-PickBestStrategy {
  param(
    [string]$Label,
    [string]$Match,
    [int]$LookbackN = 5
  )
  if (-not (Test-Path -LiteralPath $Script:HistoryFile)) { return $null }
  $all = @(Get-Content -LiteralPath $Script:HistoryFile -Encoding UTF8 -ErrorAction SilentlyContinue)
  if (-not $all -or $all.Count -eq 0) { return $null }

  # 같은 (label, match) 의 최근 LookbackN 건 — 뒤에서부터 매칭
  $candidates = New-Object System.Collections.ArrayList
  for ($i = $all.Count - 1; $i -ge 0 -and $candidates.Count -lt $LookbackN; $i--) {
    try {
      $rec = $all[$i] | ConvertFrom-Json -ErrorAction Stop
      if ("$($rec.label)" -eq $Label -and "$($rec.match)" -eq "$Match") {
        [void]$candidates.Add($rec)
      }
    } catch { continue }
  }
  if ($candidates.Count -eq 0) { return $null }

  # 성공한 strategy 들만 카운트, 가장 자주 등장한 것 반환
  $strategyCount = @{}
  foreach ($r in $candidates) {
    if ($r.success -eq $true -and $r.strategy) {
      $key = "$($r.strategy)"
      if (-not $strategyCount.ContainsKey($key)) { $strategyCount[$key] = 0 }
      $strategyCount[$key]++
    }
  }
  if ($strategyCount.Count -eq 0) { return $null }

  # 가장 많이 등장한 strategy. 동률 시 가장 최근 strategy 우선.
  $maxCount = ($strategyCount.Values | Measure-Object -Maximum).Maximum
  $topStrategies = @($strategyCount.Keys | Where-Object { $strategyCount[$_] -eq $maxCount })
  if ($topStrategies.Count -eq 1) { return $topStrategies[0] }
  # 동률 — candidates 는 최신부터이므로 처음 만나는 strategy 가 더 최근
  foreach ($r in $candidates) {
    if ($r.success -eq $true -and $topStrategies -contains "$($r.strategy)") {
      return "$($r.strategy)"
    }
  }
  return $topStrategies[0]
}

# history 전체 통계 (macro session info / metrics 에서 호출 가능)
function _History-Stats {
  if (-not (Test-Path -LiteralPath $Script:HistoryFile)) {
    return [pscustomobject]@{ total = 0; success = 0; success_rate = 0.0; strategies = @{} }
  }
  $all = @(Get-Content -LiteralPath $Script:HistoryFile -Encoding UTF8 -ErrorAction SilentlyContinue)
  if (-not $all) {
    return [pscustomobject]@{ total = 0; success = 0; success_rate = 0.0; strategies = @{} }
  }
  $total = 0; $success = 0
  $byStrategy = @{}
  foreach ($l in $all) {
    try {
      $r = $l | ConvertFrom-Json -ErrorAction Stop
      $total++
      if ($r.success -eq $true) {
        $success++
        $key = "$($r.strategy)"
        if (-not $byStrategy.ContainsKey($key)) { $byStrategy[$key] = 0 }
        $byStrategy[$key]++
      }
    } catch { continue }
  }
  $rate = 0.0
  if ($total -gt 0) { $rate = [Math]::Round(($success / $total) * 100, 1) }
  return [pscustomobject]@{
    total = $total
    success = $success
    success_rate = $rate
    strategies = $byStrategy
  }
}

# ============================================================================
# Helper auto-start -- ensures the Windows-MCP HTTP helper is running before
# operations that require it. Idempotent (returns early if already up).
# ============================================================================

function _Helper-IsUp {
  $r = Invoke-Cucp -ArgList @("tools") -CaptureJson
  return ($r.ExitCode -eq 0 -and $r.Json.status -eq "ok")
}

function _Helper-Ensure {
  param([int]$WaitMs = 8000)
  if (_Helper-IsUp) { return $true }
  Write-Notice -Level "INFO" -Message "helper 미가동 - 자동 기동 시도"
  $r = Invoke-Cucp -ArgList @("start") -CaptureJson
  if ($r.ExitCode -ne 0) {
    Write-Notice -Level "ERROR" -Message "helper 자동 기동 실패 (exit=$($r.ExitCode))"
    return $false
  }
  $deadline = (Get-Date).AddMilliseconds($WaitMs)
  while ((Get-Date) -lt $deadline) {
    if (_Helper-IsUp) {
      Write-Notice -Level "OK" -Message "helper 가동 확인"
      return $true
    }
    Start-Sleep -Milliseconds 500
  }
  Write-Notice -Level "ERROR" -Message "helper 기동했지만 응답 없음 (timeout=${WaitMs}ms)"
  return $false
}

function Invoke-MacroSession {
  param([string[]]$Rest)
  $action = if ($Rest.Count -ge 1) { $Rest[0] } else { "" }
  switch ($action) {
    "clear-cache" {
      Get-ChildItem -LiteralPath $Script:CacheDir -Filter "appshot-*.json" -ErrorAction SilentlyContinue |
        Remove-Item -Force -ErrorAction SilentlyContinue
      Get-ChildItem -LiteralPath $Script:CacheDir -Filter "point-plan-*.json" -ErrorAction SilentlyContinue |
        Remove-Item -Force -ErrorAction SilentlyContinue
      Write-Notice -Level "OK" -Message "관찰/포인트 캐시를 비웠습니다."
      return 0
    }
    "info" {
      $cacheCount = (Get-ChildItem -LiteralPath $Script:CacheDir -Filter "appshot-*.json" -ErrorAction SilentlyContinue).Count
      $pointPlanCacheCount = (Get-ChildItem -LiteralPath $Script:CacheDir -Filter "point-plan-*.json" -ErrorAction SilentlyContinue).Count
      $logSize = if (Test-Path $Script:WrapperLog) { (Get-Item $Script:WrapperLog).Length } else { 0 }
      $hsStatus = $null
      try { $hsStatus = Get-HelperServerStatus } catch { $hsStatus = $null }
      $info = [pscustomobject]@{
        cache_dir = $Script:CacheDir
        audit_dir = $Script:AuditDir
        cache_files = $cacheCount
        point_plan_cache_files = $pointPlanCacheCount
        log_path = $Script:WrapperLog
        log_size_bytes = $logSize
        cli_path = $Script:CliPath
        cache_seconds = $CacheSeconds
        helper_server = $hsStatus
      }
      [Console]::Out.WriteLine(($info | ConvertTo-Json -Depth 6))
      return 0
    }
    "start-helper" {
      # v1.6.0: helper persistent server spawn (idempotent)
      $idleStr = _Read-OptValue -Rest $Rest -Name "--idle-timeout-ms"
      $idleMs = 60000
      if ($idleStr) { try { $idleMs = [int]$idleStr } catch { $idleMs = 60000 } }
      $r = Start-HelperServer -IdleTimeoutMs $idleMs
      if ($Brief) {
        if ($r.status -eq "ok") {
          $reused = if ($r.reused) { "reused" } else { "spawned" }
          [Console]::Out.WriteLine("ok session start-helper $reused pid=$($r.pid) pipe=$($r.pipe_name)")
        } else {
          [Console]::Out.WriteLine("error session start-helper reason=$($r.reason)")
        }
      } else {
        $payload = [ordered]@{ schema = "cucp.helper-server-start/v1" }
        foreach ($p in $r.PSObject.Properties) { $payload[$p.Name] = $p.Value }
        [Console]::Out.WriteLine(($payload | ConvertTo-Json -Depth 6))
      }
      if ($r.status -eq "ok") { return 0 } else { return 1 }
    }
    "stop-helper" {
      $force = _Read-Switch -Rest $Rest -Name "--force"
      $r = Stop-HelperServer -Force:$force
      if ($Brief) {
        [Console]::Out.WriteLine("$($r.status) session stop-helper stopped_pid=$($r.stopped_pid) forced=$($r.forced)")
      } else {
        $payload = [ordered]@{ schema = "cucp.helper-server-stop/v1" }
        foreach ($p in $r.PSObject.Properties) { $payload[$p.Name] = $p.Value }
        [Console]::Out.WriteLine(($payload | ConvertTo-Json -Depth 6))
      }
      if ($r.status -eq "ok") { return 0 } else { return 1 }
    }
    "helper-status" {
      $r = Get-HelperServerStatus
      if ($Brief) {
        if ($r.alive) {
          [Console]::Out.WriteLine("ok session helper-status alive pid=$($r.pid) uptime_s=$($r.uptime_s) requests=$($r.request_count)")
        } else {
          [Console]::Out.WriteLine("ok session helper-status not_running")
        }
      } else {
        [Console]::Out.WriteLine(($r | ConvertTo-Json -Depth 6))
      }
      return 0
    }
    "install-autostart" {
      if (-not $AllowLiveControl) { throw "session install-autostart requires -AllowLiveControl" }
      # v2.2.0: Windows 로그인 시 helper-server 자동 기동 shim 설치 (cold first-call 제거)
      $idleStr = _Read-OptValue -Rest $Rest -Name "--idle-timeout-ms"
      $idleMs = 28800000  # 기본 8시간
      if ($idleStr) { try { $idleMs = [int]$idleStr } catch { $idleMs = 28800000 } }
      $r = Install-HelperAutostart -IdleTimeoutMs $idleMs
      $payload = [ordered]@{ schema = "cucp.helper-autostart/v1" }
      foreach ($p in $r.PSObject.Properties) { $payload[$p.Name] = $p.Value }
      _Emit-Envelope -Envelope ([pscustomobject]$payload) -BriefLine "$($r.status) session install-autostart shim=$($r.shim_path)" -Depth 6
      if ($r.status -eq "ok") { return 0 } else { return 1 }
    }
    "uninstall-autostart" {
      if (-not $AllowLiveControl) { throw "session uninstall-autostart requires -AllowLiveControl" }
      $r = Uninstall-HelperAutostart
      $payload = [ordered]@{ schema = "cucp.helper-autostart/v1" }
      foreach ($p in $r.PSObject.Properties) { $payload[$p.Name] = $p.Value }
      _Emit-Envelope -Envelope ([pscustomobject]$payload) -BriefLine "$($r.status) session uninstall-autostart removed=$($r.removed)" -Depth 6
      if ($r.status -eq "ok") { return 0 } else { return 1 }
    }
    "autostart-status" {
      $r = Get-HelperAutostartStatus
      $payload = [ordered]@{ schema = "cucp.helper-autostart/v1" }
      foreach ($p in $r.PSObject.Properties) { $payload[$p.Name] = $p.Value }
      _Emit-Envelope -Envelope ([pscustomobject]$payload) -BriefLine "ok session autostart-status installed=$($r.installed)" -Depth 6
      return 0
    }
    default {
      Write-Notice -Level "ERROR" -Message "session 하위 명령: clear-cache, info, start-helper, stop-helper, helper-status, install-autostart, uninstall-autostart, autostart-status"
      return 1
    }
  }
}

# ============================================================================
# Dispatch
# ============================================================================

if (-not $CucpArgs -or $CucpArgs.Count -eq 0) {
  Write-WrapperLog -Message "INVOKE help (no args)"
  & node $Script:CliPath --help
  Write-Host ""
  Write-Host "[CUCP wrapper extras]" -ForegroundColor Cyan
  Write-Host "  macro find-label         --label <text> [--window <title>] [--match <text>] [--role <role>]"
  Write-Host "  macro list-affordances   [--window <title>] [--match <text>] [--limit <n>]"
  Write-Host "  macro click-label        --label <text> [--window <title>] [--role <role>] [--offset-x <n>] [--offset-y <n>]"
  Write-Host "  macro double-click-label ... (same options)"
  Write-Host "  macro right-click-label  ... (same options)"
  Write-Host "  macro click-id           --id <affordance_id> [--window <title>]"
  Write-Host "  macro fill-label         --label <text> --text <value> [--window <title>] [--clear] [--enter]"
  Write-Host "  macro focus-window       --name <window-or-process>"
  Write-Host "  macro wait-window        --title <text> [--timeout-ms <n>] [--interval-ms <n>]"
  Write-Host "  macro wait-label         --label <text> [--window <title>] [--timeout-ms <n>] [--interval-ms <n>]"
  Write-Host "  macro shortcut           --keys <combo>"
  Write-Host "  macro goal               --objective <text> [--max-steps <n>] [--max-phase-ms <n>] [--provider heuristic|codex]"
  Write-Host "                           [--verify-label <text>] [--verify-window <title>] [--verify-timeout-ms <n>] [--dry-run]"
  Write-Host "  macro session            clear-cache | info | start-helper | stop-helper | helper-status | install-autostart | uninstall-autostart | autostart-status"
  Write-Host "  macro self-test          [--deep] [--strict]"
  Write-Host "  macro trajectory         show [--last <n>] | tail | clear"
  Write-Host "  macro ensure-helper      [--wait-ms <n>]"
  Write-Host "  macro vision-find        --describe <text> [--screenshot <path>] [--model <name>] [--timeout-ms <n>]"
  Write-Host "  macro vision-click       --describe <text> [--window <title>] [--verify-label <text>] [--verify-timeout-ms <n>] [--model <name>]"
  Write-Host "  macro metrics            (operational counters + click/cache rates)"
  Write-Host "  macro perf               [--iters <n>] [--json-only] [--quick] [--include-live-ish]   (timing min/avg/max ms)"
  Write-Host "  macro health-detail      [--json-only]   (per-component health: node/cli/helper/uia/codex/audit)"
  Write-Host "  macro health-quick       [--json-only]   (lightweight: node/cli/audit/win32 + temp pressure + recent timeouts)"
  Write-Host "  macro safety-classify    --text <text> | --step <macro command> [--macro <name>]   (read-only sensitive action classifier)"
  Write-Host "  macro windows            [--match <s>] [--rich] [--include-hidden]   (Win32 enum, deterministic fallback)"
  Write-Host "  macro coord-profile      [--x <n> --y <n>] [--target-match <s>]   (read-only DPI/monitor/window coordinate profile)"
  Write-Host "  macro coord-map          --from screen|window|normalized --x <n> --y <n> [--target-match <s>]   (read-only screen/window coordinate transform)"
  Write-Host "  macro coord-anchor       --x <n> --y <n> [--target-match <s>] [--record-history]   (read-only layout-relative coordinate anchor)"
  Write-Host "  macro hit-test           --x <n> --y <n> [--target-match <s>] [--click-inset <n>] [--fast]   (read-only point analysis)"
  Write-Host "  macro hit-test-batch     --point <x,y>... | --points <x,y;x,y> [--target-match <s>]   (read-only fast point batch)"
  Write-Host "  macro hit-scan           --x <n> --y <n> [--radius <n>] [--step <n>] [--target-match <s>]   (read-only micro point scan)"
  Write-Host "  macro point-plan         --x <n> --y <n> [--radius <n>] [--step <n>] [--target-match <s>]   (read-only precision click plan)"
  Write-Host "  macro target-validate    --x <n> --y <n> [--target-match <s>] [--min-confidence medium]   (read-only pre-click target validation)"
  Write-Host "  macro cdp-detect         [--port <n>]   (Chrome/Electron DevTools Protocol probe)"
  Write-Host "  macro cdp-eval           --expr <js> | --expr-b64 <base64> [--page-match <s>] [--port <n>]"
  Write-Host "  macro cdp-smart-find     --text <label> [--page-match <s>] [--port <n>]   (read-only DOM label resolver)"
  Write-Host "  macro cdp-smart-type-find --label <field> [--page-match <s>] [--port <n>]   (read-only DOM input resolver)"
  Write-Host "  macro cdp-smart-click    --text <label> [--page-match <s>] [--port <n>]   (live: DOM label click)"
  Write-Host "  macro cdp-smart-type     --label <field> --text <value> [--press-enter] [--page-match <s>] [--port <n>]"
  Write-Host "  macro workflow-plan      --step <macro command>...   (read-only macro sequence planner)"
  Write-Host "  macro workflow-run       --step <macro command>... [--dry-run] [--settle-ms <n>] [--observe-after-step|--verify-after-step] [--verify-label-after-step <text>] [--retry-failed-step <n>] [--confirm-sensitive]   (live: gated macro sequence runner)"
  Write-Host "  macro smart-plan         --label <text> [--type-text <value>] [--match <s>] [--allow-cdp] [--include-ocr] [--precision-points]   (read-only route planner)"
  Write-Host "  macro smart-click        --label <text> [--match <s>] [--allow-mouse-fallback] [--precision-points] [--allow-cdp] [--allow-vision]   (live: cascade click)"
  Write-Host "  macro app-profile        [--match <s>] [--label <text>...] [--auto-probe|--probe-cdp|--probe-uia]   (read-only app automation profile)"
  Write-Host "  macro task-preset        --kind document|mail|form-submit|file-upload|file-download|settings   (read-only task/workflow template)"
  Write-Host "  macro task-plan          [--app <name>] [--type-text <text>] [--shortcut <keys>] [--field <label=value>...] [--send-label <text>]   (read-only app/form workflow planner)"
  Write-Host "  macro task-run           [--dry-run] [--app <name>] [--type-text <text>] [--shortcut <keys>] [--field <label=value>...] [--confirm-sensitive]   (live: gated task-plan executor)"
  Write-Host "  macro form-plan          --field <label=value>... [--send-label <text>] [--allow-cdp]   (read-only multi-step planner)"
  Write-Host "  macro form-run           --field <label=value>... [--send-label <text>] [--allow-cdp] [--dry-run] [--confirm-sensitive]   (live: executes safe form-plan)"
  Write-Host "  macro focus-verify       --name <substring> [--timeout-ms <n>]   (live: focus + Win32 verify)"
  Write-Host "  macro log-tail           [--lines <n>] [--max-bytes <n>] [--path <file>] [--errors-only]   (bounded read + redact)"
  Write-Host "  macro diagnose-lag       [--sample-ms <n>] [--json-only]   (Codex/Electron app/Chrome process snapshot + warnings)"
  Write-Host "  macro cleanup            --dry-run | --execute   [--older-than-minutes <n>] [--keep-latest <n>] [--max-files <n>] [--max-mb <n>]"
  Write-Host "  macro icon-find          --label <text> [--window <s>] [--max-size <px>] [--near-x <n>] [--near-y <n>]   (small toolbar icon resolver)"
  Write-Host "  macro icon-click         --label <text> [--window <s>] [--max-size <px>] [--near-x <n>] [--near-y <n>]   (live: refuses ambiguous)"
  Write-Host "  macro vision-click-precise --describe <text> [--window <s>] [--crop-size <px>] [--verify-label <text>]   (2-stage crop+refine)"
  Write-Host "  macro app-launch         --name <app> [--args <s>] [--wait-title <text>] [--wait-timeout-ms <n>]"
  Write-Host "  macro app-close          --name <app> | --pid <n> [--force]"
  Write-Host "  macro with-app           --name <app> [--wait-title <text>] [--hold-ms <n>] [--close-after] [--force]"
  Write-Host "  macro click-and-verify   --label <text> [--window <title>] [--verify-label <text>] [--wait-change-ms <n>]"
  Write-Host "  macro auto-do            --label <text> | --describe <text> [--window <title>] [--max-attempts <n>] [--verify-label <text>]"
  Write-Host ""
  Write-Host "  Wrapper flags: -AllowLiveControl, -Brief, -Quiet, -CacheSeconds <n>, -InvokeTimeoutMs <n>"
  exit 0
}

# ============================================================================
# v1.4.0 — 6 missing items implementation + 보안 보완
# ============================================================================
# 9개 매크로:
#   1. cdp-deep-find        DOM bridge v2 traversal report (read-only)
#   2. ime-paste            한국어 IME-safe clipboard paste (live)
#   3. safe-type-ime        focus + ime-paste + verify (live)
#   4. modal-detect         모달/대화상자 감지 (read-only)
#   5. recovery-plan        실패 후 재관찰 + retry 추천 (read-only)
#   6. recovery-run         recovery-plan 실행 (live, sensitive gate)
#   7. precision-validate   coordinate precision 측정 (read-only)
#   8. benchmark            read-only 측정 + SLO 검증 (read-only)
#   9. release-notes        CHANGELOG -> release note + secret redact (read-only)
# ============================================================================

# 매크로 envelope schema 상수 ─ 일관된 cucp.<name>/v1 형식 유지
$Script:CucpV14Schema = @{
  CdpDeepFind       = "cucp.cdp-deep-find/v1"
  ImePaste          = "cucp.ime-paste/v1"
  SafeTypeIme       = "cucp.safe-type-ime/v1"
  ModalDetect       = "cucp.modal-detect/v1"
  RecoveryPlan      = "cucp.recovery-plan/v1"
  RecoveryRun       = "cucp.recovery-run/v1"
  PrecisionValidate = "cucp.precision-validate/v1"
  Benchmark         = "cucp.benchmark/v1"
  ReleaseNotes      = "cucp.release-notes/v1"
}

# ----------------------------------------------------------------------------
# 보안 보완: secret/PII redaction helper (release-notes 출력에 사용)
# 패턴: GitHub PAT (ghp_/gho_/ghs_/...), OpenAI sk-, AWS AKIA, Bearer/JWT, PEM
# ----------------------------------------------------------------------------


# ----------------------------------------------------------------------------
# 1. cdp-deep-find ─ Shadow DOM/iframe 깊이 보고 (read-only)
# 입력: --text <label> [--page-match <s>] [--port <n>]
# 출력: cucp.cdp-deep-find/v1
# 동기: smart-find/type 가 deepCollect 로 traversal 하지만 그 메타정보가
#       외부에 안 보임. 디버깅/벤치마크용으로 노출.
# ----------------------------------------------------------------------------


# ----------------------------------------------------------------------------
# 2. ime-paste ─ 한국어 IME-safe clipboard paste (live)
# 입력: --text <s> [--press-enter] [--target-match <s>] [--target-hwnd <n>]
# 출력: cucp.ime-paste/v1
# 보안: clipboard 백업/복구, hit-test 가드, 마우스 안 움직임
# ----------------------------------------------------------------------------
function Invoke-MacroImePaste {
  param([string[]]$Rest)
  if (-not $AllowLiveControl) { throw "macro ime-paste requires -AllowLiveControl" }
  $text = _Read-OptValue -Rest $Rest -Name "--text"
  if (-not $text) { throw "macro ime-paste requires --text" }
  $tm = _Read-OptValue -Rest $Rest -Name "--target-match"
  $thStr = _Read-OptValue -Rest $Rest -Name "--target-hwnd"
  $th = 0
  if ($thStr) { try { $th = [int]$thStr } catch { $th = 0 } }
  $pressEnter = _Read-Switch -Rest $Rest -Name "--press-enter"
  $argList = @("-Action","ime-paste","-Text",$text)
  if ($pressEnter) { $argList += "-PressEnter" }
  if ($tm) { $argList += @("-TargetMatch", $tm) }
  if ($th -gt 0) { $argList += @("-TargetHwnd", "$th") }
  $r = Invoke-NativeHelper -ArgList $argList
  $out = [ordered]@{ schema = $Script:CucpV14Schema.ImePaste }
  if ($r.Json) {
    foreach ($prop in $r.Json.PSObject.Properties) { $out[$prop.Name] = $prop.Value }
  } else {
    $out["status"] = "error"
    $out["reason"] = "helper_failed"
  }
  if ($Brief) {
    if ($r.Json -and $r.Json.status -eq "ok") {
      [Console]::Out.WriteLine("ok ime-paste len=$($r.Json.text_len) restored=$($r.Json.restored_clipboard)")
    } elseif ($r.Json -and $r.Json.status -eq "blocked") {
      [Console]::Out.WriteLine("blocked ime-paste reason=$($r.Json.reason)")
    } else {
      $reason = "helper_failed"
      if ($r.Json -and $r.Json.reason) { $reason = $r.Json.reason }
      [Console]::Out.WriteLine("partial ime-paste reason=$reason")
    }
  } else {
    [Console]::Out.WriteLine(($out | ConvertTo-Json -Depth 10))
  }
  if ($r.Json) {
    switch ($r.Json.status) {
      "ok"      { return 0 }
      "blocked" { return 3 }
      default   { return 2 }
    }
  }
  return 1
}

# ----------------------------------------------------------------------------
# 3. safe-type-ime ─ focus + ime-paste + 선택적 verify (live)
# 입력: --text <s> [--target-match <s>] [--target-hwnd <n>] [--press-enter]
#       [--verify-title <s>]
# 출력: cucp.safe-type-ime/v1
# 동기: safe-type 의 race condition 을 clipboard route 로 회피
# ----------------------------------------------------------------------------
function Invoke-MacroSafeTypeIme {
  param([string[]]$Rest)
  if (-not $AllowLiveControl) { throw "macro safe-type-ime requires -AllowLiveControl" }
  $text = _Read-OptValue -Rest $Rest -Name "--text"
  if (-not $text) { throw "macro safe-type-ime requires --text" }
  $tm = _Read-OptValue -Rest $Rest -Name "--target-match"
  $thStr = _Read-OptValue -Rest $Rest -Name "--target-hwnd"
  $th = 0
  if ($thStr) { try { $th = [int]$thStr } catch { $th = 0 } }
  $pressEnter  = _Read-Switch -Rest $Rest -Name "--press-enter"
  $verifyTitle = _Read-OptValue -Rest $Rest -Name "--verify-title"
  # Step A: focus (--target-match 있을 때만)
  $focusEvidence = $null
  if ($tm) {
    try {
      $fa = @("-Action","focus","-Match",$tm)
      $fr = Invoke-NativeHelper -ArgList $fa
      if ($fr.Json) { $focusEvidence = $fr.Json }
    } catch { $focusEvidence = $null }
  }
  Start-Sleep -Milliseconds 80
  # Step B: ime-paste (native helper 직접 호출)
  $pa = @("-Action","ime-paste","-Text",$text)
  if ($pressEnter) { $pa += "-PressEnter" }
  if ($tm) { $pa += @("-TargetMatch", $tm) }
  if ($th -gt 0) { $pa += @("-TargetHwnd", "$th") }
  $pr = Invoke-NativeHelper -ArgList $pa
  # Step C: 선택적 verify (window title 부분 일치)
  $verifyEvidence = $null
  if ($verifyTitle -and $pr.Json -and $pr.Json.status -eq "ok") {
    Start-Sleep -Milliseconds 120
    try {
      $wr = Invoke-NativeHelper -ArgList @("-Action","windows")
      $hit = $false
      if ($wr.Json -and $wr.Json.windows) {
        foreach ($w in $wr.Json.windows) {
          if ($w.title -and ($w.title -match [regex]::Escape($verifyTitle))) {
            $hit = $true; break
          }
        }
      }
      $verifyEvidence = [ordered]@{ verify_title=$verifyTitle; matched=$hit }
    } catch {
      $verifyEvidence = [ordered]@{ verify_title=$verifyTitle; matched=$false; error=$_.Exception.Message }
    }
  }
  # paste 단계 status 로 최종 status 결정
  $finalStatus = "ok"
  if (-not $pr.Json) { $finalStatus = "error" }
  elseif ($pr.Json.status -eq "blocked") { $finalStatus = "blocked" }
  elseif ($pr.Json.status -ne "ok")      { $finalStatus = "partial" }
  $out = [ordered]@{
    schema = $Script:CucpV14Schema.SafeTypeIme
    status = $finalStatus
    text_len = [int]$text.Length
    pressed_enter = [bool]$pressEnter
    focus  = $focusEvidence
    paste  = if ($pr.Json) { $pr.Json } else { $null }
    verify = $verifyEvidence
  }
  if ($Brief) {
    $vm = "n/a"
    if ($verifyEvidence) { $vm = "$($verifyEvidence.matched)" }
    [Console]::Out.WriteLine("$finalStatus safe-type-ime len=$($text.Length) verify_matched=$vm")
  } else {
    [Console]::Out.WriteLine(($out | ConvertTo-Json -Depth 10))
  }
  switch ($finalStatus) {
    "ok"      { return 0 }
    "blocked" { return 3 }
    "partial" { return 2 }
    default   { return 1 }
  }
}

# ----------------------------------------------------------------------------
# 4. modal-detect ─ 모달/대화상자 감지 (read-only)
# 입력: [--match <s>] [--target-hwnd <n>]
# 출력: cucp.modal-detect/v1 (native helper output + schema)
# ----------------------------------------------------------------------------
function Invoke-MacroModalDetect {
  param([string[]]$Rest)
  $tm = _Read-OptValue -Rest $Rest -Name "--match"
  $thStr = _Read-OptValue -Rest $Rest -Name "--target-hwnd"
  $th = 0
  if ($thStr) { try { $th = [int]$thStr } catch { $th = 0 } }
  $argList = @("-Action","modal-detect")
  if ($tm) { $argList += @("-Match", $tm) }
  if ($th -gt 0) { $argList += @("-TargetHwnd", "$th") }
  $r = Invoke-NativeHelper -ArgList $argList
  $out = [ordered]@{ schema = $Script:CucpV14Schema.ModalDetect }
  if ($r.Json) {
    foreach ($prop in $r.Json.PSObject.Properties) { $out[$prop.Name] = $prop.Value }
  } else {
    $out["status"] = "error"
    $out["reason"] = "helper_failed"
  }
  if ($Brief) {
    $cc = 0; $rec = "observe"
    if ($r.Json -and $r.Json.candidate_count)    { $cc  = [int]$r.Json.candidate_count }
    if ($r.Json -and $r.Json.recommended_action) { $rec = "$($r.Json.recommended_action)" }
    [Console]::Out.WriteLine("ok modal-detect candidates=$cc recommended=$rec")
  } else {
    [Console]::Out.WriteLine(($out | ConvertTo-Json -Depth 10))
  }
  return 0
}

# ----------------------------------------------------------------------------
# 5. recovery-plan ─ 실패 후 재관찰 + retry 추천 (read-only)
# 입력: [--match <s>] [--failed-step <s>] [--failed-reason <s>]
# 출력: cucp.recovery-plan/v1 { modal, foreground, recovery_candidates[], next_action }
# ----------------------------------------------------------------------------
function Invoke-MacroRecoveryPlan {param([string[]]$Rest) return _Invoke-LegacyExecutionFamily -Operation 'recovery-plan' -Rest $Rest -ScriptPath $PSCommandPath}

# ----------------------------------------------------------------------------
# 6. recovery-run ─ recovery-plan 실행 (live, sensitive gate)
# 입력: [--match <s>] [--failed-step <s>] [--dry-run] [--confirm-sensitive]
# 출력: cucp.recovery-run/v1
# 보안: live action 은 -AllowLiveControl + --confirm-sensitive 둘 다 필수
# ----------------------------------------------------------------------------
function Invoke-MacroRecoveryRun {param([string[]]$Rest) return _Invoke-LegacyExecutionFamily -Operation 'recovery-run' -Rest $Rest -ScriptPath $PSCommandPath}

# ----------------------------------------------------------------------------
# 7. precision-validate ─ coordinate precision 측정 (read-only)
# 입력: --x <n> --y <n> [--target-match <s>] [--samples <n>]
# 출력: cucp.precision-validate/v1 { drift_max, drift_avg, stable, recommendation }
# ----------------------------------------------------------------------------
function Invoke-MacroPrecisionValidate {param([string[]]$Rest) return _Invoke-LegacyInteractionFamily -Operation 'precision-validate' -Rest $Rest -ScriptPath $PSCommandPath}

# ----------------------------------------------------------------------------
# 8. benchmark ─ read-only 측정 + SLO 검증 (read-only, 라이브 클래스룸 안 씀)
# 입력: [--iters <n>]   기본 3, 최대 10
# 출력: cucp.benchmark/v1 { results[], slo_pass_rate_pct, recommendation }
# 보안: 텍스트/PII 미포함, 길이/타이밍만 측정
# ----------------------------------------------------------------------------
function Invoke-MacroBenchmark {
  param([string[]]$Rest)
  $itersStr = _Read-OptValue -Rest $Rest -Name "--iters"
  $baselinePath = _Read-OptValue -Rest $Rest -Name "--baseline"
  $iters = 3
  if ($itersStr) { try { $iters = [int]$itersStr } catch { $iters = 3 } }
  if ($iters -lt 1)  { $iters = 1 }
  if ($iters -gt 10) { $iters = 10 }
  # 측정 대상 (모두 read-only native helper actions, helper 외 의존성 없음)
  $targets = @(
    @{ name="windows";      args=@("-Action","windows");      slo_ms=600 },
    @{ name="health";       args=@("-Action","health");       slo_ms=400 },
    @{ name="focused";      args=@("-Action","focused");      slo_ms=500 },
    @{ name="modal-detect"; args=@("-Action","modal-detect"); slo_ms=800 }
  )
  $results = New-Object System.Collections.ArrayList
  foreach ($t in $targets) {
    $samples = New-Object System.Collections.ArrayList
    for ($i = 0; $i -lt $iters; $i++) {
      $sw = [System.Diagnostics.Stopwatch]::StartNew()
      $okFlag = $false
      $errMsg = $null
      try {
        $r = Invoke-NativeHelper -ArgList $t.args
        $sw.Stop()
        if ($r.ExitCode -eq 0 -and $r.Json) {
          if ($r.Json.status) {
            if ($r.Json.status -eq "ok") { $okFlag = $true }
          } else {
            $okFlag = $true
          }
        }
      } catch {
        $sw.Stop()
        $errMsg = $_.Exception.Message
      }
      $entry = [ordered]@{ iter=$i+1; ms=[int]$sw.ElapsedMilliseconds; ok=$okFlag }
      if ($errMsg) { $entry["error"] = $errMsg }
      [void]$samples.Add($entry)
    }
    $okMs = @($samples | Where-Object { $_.ok } | ForEach-Object { $_.ms })
    $p50 = $null; $p95 = $null; $avg = $null
    if ($okMs.Count -gt 0) {
      $sorted = @($okMs | Sort-Object)
      $i50 = [int]([Math]::Ceiling($sorted.Count * 0.5)) - 1
      $i95 = [int]([Math]::Ceiling($sorted.Count * 0.95)) - 1
      if ($i50 -lt 0) { $i50 = 0 }
      if ($i95 -lt 0) { $i95 = 0 }
      $p50 = $sorted[$i50]
      $p95 = $sorted[$i95]
      $avg = [int](($okMs | Measure-Object -Average).Average)
    }
    # A passing timing percentile cannot conceal failures or an empty sample.
    $sloOk = ($okMs.Count -eq $iters -and $okMs.Count -gt 0 -and $p95 -le $t.slo_ms)
    [void]$results.Add([ordered]@{
      name=$t.name; iters=$iters; ok_count=$okMs.Count; failure_count=($iters - $okMs.Count);
      p50_ms=$p50; p95_ms=$p95; avg_ms=$avg;
      slo_ms=$t.slo_ms; slo_ok=$sloOk;
      samples=@($samples)
    })
  }
  $totalSlos = (@($results | Where-Object { $_.slo_ok })).Count
  $passRate = 0.0
  if ($targets.Count -gt 0) {
    $passRate = [Math]::Round(([double]$totalSlos / [double]$targets.Count) * 100.0, 1)
  }
  $rec = "investigate_helper_health"
  if ($passRate -ge 90.0)      { $rec = "all_within_slo" }
  elseif ($passRate -ge 60.0)  { $rec = "review_slow_targets" }
  # v1.5.0: --baseline 비교 모드 (read-only, regression detection)
  $baselineCompare = $null
  if ($baselinePath -and (Test-Path -LiteralPath $baselinePath)) {
    try {
      $baseRaw = @(Get-Content -LiteralPath $baselinePath -Raw)
      $base = $baseRaw -join "" | ConvertFrom-Json
      $cmpRows = New-Object System.Collections.ArrayList
      $regressed = 0
      $improved  = 0
      foreach ($cur in $results) {
        $b = $base.results | Where-Object { $_.name -eq $cur.name } | Select-Object -First 1
        if (-not $b -or $null -eq $cur.p50_ms -or $null -eq $b.p50_ms) { continue }
        $deltaP50 = $cur.p50_ms - [int]$b.p50_ms
        $deltaP95 = $cur.p95_ms - [int]$b.p95_ms
        $pctP50 = 0
        if ([int]$b.p50_ms -gt 0) { $pctP50 = [Math]::Round((([double]$deltaP50) / [double]$b.p50_ms) * 100.0, 1) }
        $verdict = "neutral"
        if ($deltaP50 -le -10) { $verdict = "improved"; $improved++ }
        elseif ($deltaP50 -ge 30) { $verdict = "regressed"; $regressed++ }
        [void]$cmpRows.Add([ordered]@{
          name = $cur.name
          baseline_p50_ms = [int]$b.p50_ms
          current_p50_ms  = $cur.p50_ms
          delta_ms = $deltaP50
          delta_pct = $pctP50
          verdict = $verdict
        })
      }
      $baselineCompare = [ordered]@{
        baseline_path = $baselinePath
        compared_targets = $cmpRows.Count
        improved_count = $improved
        regressed_count = $regressed
        rows = @($cmpRows)
      }
    } catch {
      $baselineCompare = [ordered]@{
        baseline_path = $baselinePath
        error = "baseline_load_failed"
        detail = $_.Exception.Message
      }
    }
  }
  $out = [ordered]@{
    schema = $Script:CucpV14Schema.Benchmark
    status = "ok"
    iters  = $iters
    target_count = $targets.Count
    results      = @($results)
    slo_pass_count    = $totalSlos
    slo_pass_rate_pct = $passRate
    recommendation    = $rec
    baseline_compare  = $baselineCompare
  }
  if ($Brief) {
    if ($baselineCompare -and -not $baselineCompare.error) {
      [Console]::Out.WriteLine("ok benchmark targets=$($targets.Count) iters=$iters slo_pass=$totalSlos/$($targets.Count) ($passRate%) improved=$($baselineCompare.improved_count) regressed=$($baselineCompare.regressed_count)")
    } else {
      [Console]::Out.WriteLine("ok benchmark targets=$($targets.Count) iters=$iters slo_pass=$totalSlos/$($targets.Count) ($passRate%)")
    }
  } else {
    [Console]::Out.WriteLine(($out | ConvertTo-Json -Depth 10))
  }
  return 0
}

# ----------------------------------------------------------------------------
# 9. release-notes ─ CHANGELOG -> release notes (read-only, secret redact)
# 입력: [--version <x.y.z>] [--since <x.y.z>]   기본: 최신 1개
# 출력: cucp.release-notes/v1 { notes[], migration_notes, external_agent_usage }
# 보안: secret 패턴 자동 redact (PAT, sk-, AKIA, Bearer, JWT, PEM)
# ----------------------------------------------------------------------------
function Invoke-MacroReleaseNotes {param([string[]]$Rest) return _Invoke-LegacyDiagnosticFamily -Operation 'release-notes' -Rest $Rest}

# ============================================================================
# v1.7.0 — daemon batch + mouse-verify (single-shot 누적 가속 + 정확도 측정)
# ============================================================================

# ----------------------------------------------------------------------------
# macro cdp-prosemirror-insert --selector <css> --text <s>
#   [--page-match <s>] [--port <n>]
# ----------------------------------------------------------------------------
# v1.3.0 부터 부채인 ProseMirror live 입력 해결. CDP `Input.insertText` 사용.
# ProseMirror / TipTap 같은 React state-managed editor 가 execCommand 거부 시
# 이 매크로 사용. live actuation 이라 -AllowLiveControl 필수.
# ----------------------------------------------------------------------------


# ----------------------------------------------------------------------------
# macro daemon batch <commands.json>
# ----------------------------------------------------------------------------
# 한 wrapper invocation 안에서 여러 매크로를 순차 실행. PowerShell startup +
# CLI cache + helper-server 라이프사이클 비용을 1회로 묶음. AI agent 가 여러
# 매크로를 한 번에 실행할 때 유용.
#
# commands.json 형식:
#   { "commands": [
#       { "macro": "windows", "args": [] },
#       { "macro": "find-label", "args": ["--label", "Save"] },
#       { "macro": "session", "args": ["info"] }
#   ]}
#
# 출력: { schema, total_count, success_count, failed_count, results: [...] }
# ----------------------------------------------------------------------------
function Invoke-MacroDaemon {
  param([string[]]$Rest)
  $action = if ($Rest.Count -ge 1) { $Rest[0] } else { "" }
  switch ($action) {
    "batch" {
      $cmdFile = _Read-OptValue -Rest $Rest -Name "--file"
      $autoStart = _Read-Switch -Rest $Rest -Name "--auto-start-helper"
      if (-not $cmdFile) { throw "macro daemon batch requires --file <commands.json>" }
      if (-not (Test-Path -LiteralPath $cmdFile)) { throw "commands.json not found: $cmdFile" }
      $cmdJson = $null
      try {
        $cmdJson = Get-Content -LiteralPath $cmdFile -Raw -Encoding UTF8 | ConvertFrom-Json
      } catch { throw "invalid commands.json: $($_.Exception.Message)" }
      if (-not $cmdJson.commands) { throw "commands.json must have 'commands' array" }
      $commands = @($cmdJson.commands)
      # 자동으로 helper-server 띄우기 (옵션)
      $serverWasUp = $false
      if ($autoStart) {
        $hs = Get-HelperServerStatus
        if ($hs.alive) { $serverWasUp = $true }
        else { try { Start-HelperServer -IdleTimeoutMs 60000 | Out-Null } catch { } }
      }
      $results = New-Object System.Collections.ArrayList
      $successCount = 0
      $failedCount = 0
      $batchSw = [System.Diagnostics.Stopwatch]::StartNew()
      foreach ($c in $commands) {
        $macroName = "$($c.macro)"
        $macroArgs = @()
        if ($c.args) { $macroArgs = @($c.args | ForEach-Object { "$_" }) }
        $itemSw = [System.Diagnostics.Stopwatch]::StartNew()
        $itemRes = [ordered]@{
          macro = $macroName
          args = @($macroArgs)
          exit_code = 0
          elapsed_ms = 0
        }
        try {
          # macro 키워드 + args 묶어서 dispatch 재호출
          $argList = @("macro", $macroName) + $macroArgs
          $code = Invoke-Macro -ArgList $argList
          if ($null -eq $code) { $code = 0 }
          if ($code -is [array]) { $code = $code[-1] }
          if ($code -isnot [int]) { try { $code = [int]$code } catch { $code = 0 } }
          $itemRes["exit_code"] = $code
          if ($code -eq 0) { $successCount++ } else { $failedCount++ }
        } catch {
          $itemRes["exit_code"] = 1
          $itemRes["error"] = $_.Exception.Message
          $failedCount++
        }
        $itemSw.Stop()
        $itemRes["elapsed_ms"] = [int]$itemSw.Elapsed.TotalMilliseconds
        [void]$results.Add($itemRes)
      }
      $batchSw.Stop()
      # 자동 시작했고 원래 down 이었으면 정리
      if ($autoStart -and -not $serverWasUp) {
        try { Stop-HelperServer | Out-Null } catch { }
      }
      $out = [ordered]@{
        schema = "cucp.daemon-batch/v1"
        status = "ok"
        total_count = $commands.Count
        success_count = $successCount
        failed_count = $failedCount
        elapsed_ms = [int]$batchSw.Elapsed.TotalMilliseconds
        avg_ms_per_command = if ($commands.Count -gt 0) { [int]($batchSw.Elapsed.TotalMilliseconds / $commands.Count) } else { 0 }
        helper_server_used = (Get-HelperServerStatus).alive
        results = @($results)
      }
      if ($Brief) {
        [Console]::Out.WriteLine("ok daemon batch total=$($out.total_count) success=$($out.success_count) failed=$($out.failed_count) elapsed_ms=$($out.elapsed_ms) avg=$($out.avg_ms_per_command)ms")
      } else {
        [Console]::Out.WriteLine(($out | ConvertTo-Json -Depth 10))
      }
      return 0
    }
    "serve" {
      return Invoke-MacroDaemonServe -Rest $Rest
    }
    default {
      Write-Notice -Level "ERROR" -Message "daemon 하위 명령: batch --file <commands.json> [--auto-start-helper] | serve [--max-commands N] [--idle-timeout-ms N]"
      return 1
    }
  }
}

# ----------------------------------------------------------------------------
# macro daemon serve  (v2.3.0 — single-shot 가속 정공법)
# ----------------------------------------------------------------------------
# 문제: single-shot 호출(매번 새 PowerShell)이 ~2초. 그 2초의 대부분은 helper
#       child spawn 이 아니라 "PowerShell 실행 + wrapper 14,800줄 파싱 + .NET/UIA
#       assembly 로드" 다. helper-server 가 떠 있어도 이 비용은 안 줄어든다
#       (실측 확인). 따라서 진짜 해법은 wrapper 자체를 한 번만 로드한 상주
#       프로세스가 명령을 실시간으로 받아 처리하는 것.
#
# 동작: stdin 에서 JSON-line 한 줄 = 명령 하나. stdout 으로 JSON-line 한 줄 = 응답.
#       wrapper 는 이미 메모리에 로드돼 있으므로 2번째 명령부터는 파싱/로드 비용 0.
#       각 명령은 Invoke-Macro 를 그대로 재호출 → 모든 안전 게이트 동일 적용.
#
# 안전 설계:
#   - live 허용은 daemon 시작 시 -AllowLiveControl 로 고정된다 (PowerShell param
#     스위치라 런타임 토글 불가). read-only daemon 과 live daemon 을 명시 분리 →
#     "실수로 띄운 daemon 이 조작까지 한다" 를 구조적으로 차단.
#   - 각 매크로의 stdout 직접 출력([Console]::Out.WriteLine)을 StringWriter 로
#     가로채 캡처한 뒤 원래 stdout 으로 복원. 응답 JSON 의 stdout 필드에 담는다.
#   - --max-commands / --idle-timeout-ms 로 무한 상주 방지 (자원 누수 차단).
#
# 프로토콜:
#   요청: {"id":1,"macro":"windows","args":["--json-only"]}
#         {"action":"ping"}  /  {"action":"shutdown"}
#   응답: {"id":1,"exit_code":0,"stdout":"...","elapsed_ms":42}
#         {"action":"ping","ok":true,"live":false,"served":3}
# ----------------------------------------------------------------------------
function Invoke-MacroDaemonServe {
  param([string[]]$Rest)
  $maxCommands = [int](_Read-OptValue -Rest $Rest -Name "--max-commands")
  if ($maxCommands -le 0) { $maxCommands = 1000 }
  $idleTimeoutMs = [int](_Read-OptValue -Rest $Rest -Name "--idle-timeout-ms")
  if ($idleTimeoutMs -le 0) { $idleTimeoutMs = 1800000 }  # 정보용 (기본 30분)

  $stdin = [Console]::In
  $served = 0

  # ready 신호 (호출자가 daemon 기동 완료를 알 수 있게). live 모드 여부 노출.
  $ready = [ordered]@{
    schema = "cucp.daemon-serve/v1"
    status = "ready"
    live = [bool]$AllowLiveControl
    pid = $PID
    max_commands = $maxCommands
    protocol = "sentinel"
  }
  [Console]::Out.WriteLine(($ready | ConvertTo-Json -Compress -Depth 5))
  [Console]::Out.Flush()

  while ($served -lt $maxCommands) {
    # blocking ReadLine. 호출자가 shutdown 을 보내거나 stdin 을 닫으면(EOF) 종료.
    $line = $stdin.ReadLine()
    if ($null -eq $line) { break }                    # stdin EOF
    $line = $line.Trim()
    if ($line -eq "") { continue }

    $req = $null
    try { $req = $line | ConvertFrom-Json -ErrorAction Stop } catch {
      [Console]::Out.WriteLine((@{ schema="cucp.daemon-serve/v1"; status="error"; reason="bad_json" } | ConvertTo-Json -Compress))
      [Console]::Out.Flush(); continue
    }

    # 제어 명령 (action) 우선 처리
    if ($req.action) {
      if ("$($req.action)" -eq "shutdown") {
        [Console]::Out.WriteLine((@{ schema="cucp.daemon-serve/v1"; status="shutdown"; served=$served } | ConvertTo-Json -Compress))
        [Console]::Out.Flush(); break
      }
      if ("$($req.action)" -eq "ping") {
        [Console]::Out.WriteLine((@{ schema="cucp.daemon-serve/v1"; action="ping"; ok=$true; live=[bool]$AllowLiveControl; served=$served } | ConvertTo-Json -Compress))
        [Console]::Out.Flush(); continue
      }
    }

    $macroName = "$($req.macro)"
    $reqId = "$($req.id)"
    if (-not $macroName) {
      [Console]::Out.WriteLine((@{ schema="cucp.daemon-serve/v1"; id=$req.id; status="error"; reason="no_macro" } | ConvertTo-Json -Compress))
      [Console]::Out.Flush(); continue
    }
    $macroArgs = @()
    if ($req.args) { $macroArgs = @($req.args | ForEach-Object { "$_" }) }

    # ----- sentinel 프로토콜 -----
    # SetOut 캡처는 child-spawn 매크로(native helper)와 PowerShell 5.x 에서 충돌해
    # 데드락/race 를 일으킨다(실측). 그래서 매크로의 stdout 을 가로채지 않고, 응답을
    # BEGIN/END sentinel 로 감싸 raw stdout 에 그대로 흘려보낸다. 클라이언트는 두
    # sentinel 사이를 매크로 출력으로, END 줄에서 exit/elapsed 를 파싱한다.
    #   <<<CUCP-RESP id=ID>>>
    #   ...매크로 stdout (여러 줄 가능)...
    #   <<<CUCP-END id=ID exit=CODE ms=ELAPSED>>>
    $exitCode = 0
    $cmdSw = [System.Diagnostics.Stopwatch]::StartNew()
    [Console]::Out.WriteLine("<<<CUCP-RESP id=$reqId>>>")
    [Console]::Out.Flush()
    try {
      $argList = @("macro", $macroName) + $macroArgs
      $code = Invoke-Macro -ArgList $argList     # 매크로가 직접 [Console]::Out 으로 출력
      if ($null -eq $code) { $code = 0 }
      if ($code -is [array]) { $code = $code[-1] }
      if ($code -isnot [int]) { try { $code = [int]$code } catch { $code = 0 } }
      $exitCode = $code
    } catch {
      $exitCode = 1
      [Console]::Out.WriteLine((@{ schema="cucp.daemon-serve/v1"; error="$($_.Exception.Message)" } | ConvertTo-Json -Compress))
    }
    $cmdSw.Stop()
    [Console]::Out.Flush()
    [Console]::Out.WriteLine("<<<CUCP-END id=$reqId exit=$exitCode ms=$([int]$cmdSw.Elapsed.TotalMilliseconds)>>>")
    [Console]::Out.Flush()
    $served++
  }
  return 0
}

# ----------------------------------------------------------------------------
# macro mouse-verify --x <n> --y <n> [--target-match <s>] [--samples N]
# ----------------------------------------------------------------------------
# 좌표 클릭의 정확도 cassette. -AllowLiveControl 필수. 실제 click 후 도착 좌표
# (post_click.actual_x/y) 와 요청 좌표 비교 → drift 측정.
# 정확도 = drift_max ≤ 3px AND target window 일치율 100%.
# 본체에서 1환경 검증 후 cassette 보존 (Notepad / Electron app / Chrome).
# ----------------------------------------------------------------------------
function Invoke-MacroMouseVerify {
  param([string[]]$Rest)
  if (-not $AllowLiveControl) { throw "macro mouse-verify requires -AllowLiveControl" }
  $xStr = _Read-OptValue -Rest $Rest -Name "--x"
  $yStr = _Read-OptValue -Rest $Rest -Name "--y"
  if (-not $xStr -or -not $yStr) { throw "macro mouse-verify requires --x and --y" }
  $tm = _Read-OptValue -Rest $Rest -Name "--target-match"
  $samplesStr = _Read-OptValue -Rest $Rest -Name "--samples"
  $samples = 3
  if ($samplesStr) { try { $samples = [int]$samplesStr } catch { $samples = 3 } }
  if ($samples -lt 1) { $samples = 1 }
  if ($samples -gt 10) { $samples = 10 }
  $x = [int]$xStr
  $y = [int]$yStr
  $records = New-Object System.Collections.ArrayList
  for ($i = 0; $i -lt $samples; $i++) {
    $argList = @("-Action","click","-X","$x","-Y","$y","-Button","left")
    if ($tm) { $argList += @("-TargetMatch", $tm) }
    $r = Invoke-NativeHelper -ArgList $argList
    $rec = [ordered]@{
      iter = $i + 1
      exit_code = [int]$r.ExitCode
      route = if ($r.Route) { "$($r.Route)" } else { "child" }
    }
    if ($r.Json) {
      if ($r.Json.post_click) {
        $rec["actual_x"] = [int]$r.Json.post_click.actual_x
        $rec["actual_y"] = [int]$r.Json.post_click.actual_y
        $rec["drift_px"] = [int]$r.Json.post_click.drift_px
        $rec["accurate"] = [bool]$r.Json.post_click.accurate
      }
      if ($r.Json.status) { $rec["status"] = "$($r.Json.status)" }
      if ($r.Json.reason) { $rec["reason"] = "$($r.Json.reason)" }
    }
    [void]$records.Add($rec)
    Start-Sleep -Milliseconds 200  # OS event settling
  }
  # 통계
  $drifts = @($records | Where-Object { $_.drift_px -ne $null } | ForEach-Object { [int]$_.drift_px })
  $accurateCount = @($records | Where-Object { $_.accurate -eq $true }).Count
  $blockedCount = @($records | Where-Object { $_.exit_code -eq 3 }).Count
  $okCount = @($records | Where-Object { $_.exit_code -eq 0 }).Count
  $driftMax = if ($drifts.Count -gt 0) { [int]($drifts | Measure-Object -Maximum).Maximum } else { 0 }
  $driftAvg = if ($drifts.Count -gt 0) { [int]($drifts | Measure-Object -Average).Average } else { 0 }
  $passed = ($accurateCount -eq $samples -and $blockedCount -eq 0)
  $out = [ordered]@{
    schema = "cucp.mouse-verify/v1"
    status = if ($passed) { "ok" } else { "partial" }
    requested = [ordered]@{ x = $x; y = $y; target_match = $tm; samples = $samples }
    samples_count = $records.Count
    ok_count = $okCount
    blocked_count = $blockedCount
    accurate_count = $accurateCount
    drift_max_px = $driftMax
    drift_avg_px = $driftAvg
    passed = $passed
    cassette = @($records)
    recommendation = if ($passed) { "safe_to_click" } elseif ($driftMax -le 5) { "use_with_micro_refine" } else { "use_uia_pattern_or_relabel" }
  }
  if ($Brief) {
    [Console]::Out.WriteLine("$($out.status) mouse-verify samples=$samples drift_max=${driftMax}px accurate=$accurateCount/$samples passed=$passed")
  } else {
    [Console]::Out.WriteLine(($out | ConvertTo-Json -Depth 10))
  }
  if ($passed) { return 0 } else { return 2 }
}

# v1.8.0 — `cucp version` (top-level) 을 wrapper 통합 surface 로 가로챔.
# cli backend 로 위임하기 전에 wrapper 의 Get-CucpVersionReport 가 skill+cli+helper-server
# 셋을 묶은 envelope 을 직접 emit. cli backend 의 v1.0.0 자체 버전은 그 안에 포함됨.
if ($CucpArgs.Count -ge 1 -and $CucpArgs[0] -eq "version") {
  $rest = if ($CucpArgs.Count -gt 1) { $CucpArgs[1..($CucpArgs.Count-1)] } else { @() }
  try {
    $code = Invoke-MacroVersion -Rest $rest
    if ($null -eq $code) { $code = 0 }
    if ($code -is [array]) { $code = ($code | Where-Object { $_ -is [int] } | Select-Object -Last 1) }
    if ($code -isnot [int]) { try { $code = [int]$code } catch { $code = 0 } }
    exit $code
  } catch {
    Write-Notice -Level "ERROR" -Message "$($_.Exception.Message)"
    exit 1
  }
}

# Macro path
if ($CucpArgs[0] -eq "macro") {
  try {
    $code = Invoke-Macro -ArgList $CucpArgs
    if ($null -eq $code) { $code = 0 }
    # v0.9.0 fix: PowerShell 함수가 multiple output 흘려서 $code 가 array 가 될 수 있음.
    # 마지막 element (실제 return 값) 만 사용. int 가 아니면 0.
    if ($code -is [array]) {
      $last = $code[-1]
      if ($last -is [int]) { $code = $last } else { $code = 0 }
    }
    if ($code -isnot [int]) {
      try { $code = [int]$code } catch { $code = 0 }
    }
    exit $code
  } catch {
    $msg = "$($_.Exception.Message)"
    Write-Notice -Level "ERROR" -Message $msg
    # Standardized blocked exit codes (match SKILL.md table):
    #   3 = safety gate blocked (live-control, missing --after, requires
    #       -AllowLiveControl, label not found via fusion+vision, etc.)
    if ($msg -match 'AllowLiveControl|Live (desktop )?control|Live click|requires -AllowLiveControl|Coordinate-based act|requires --after|Label not found|affordance_id not found') {
      exit 3
    }
    exit 1
  }
}

# Direct CLI passthrough with safety gates.
# We forward to the CUCP CLI through Invoke-Cucp so the JSON envelope's
# `status: "error"` propagates into a non-zero exit code. This catches
# plan readiness/preflight/validate failures that the upstream CLI would
# otherwise report only via stdout.
try {
  Assert-Authorized -ArgList $CucpArgs
} catch {
  Write-Notice -Level "ERROR" -Message "$($_.Exception.Message)"
  exit 3
}

# JSON-bearing subcommands that should map status->exit. For everything else,
# fall through to a streaming invocation so heavy commands (benchmarks, l5,
# scenario) keep their original behavior.
$_jsonSurfacedFirstWords = @(
  "plan", "scenario", "tools", "version", "health", "release",
  "observe", "act", "app", "desktop", "l5", "replay"
)
$_useJsonCapture = $false
if ($CucpArgs.Count -ge 1) {
  if ($_jsonSurfacedFirstWords -contains $CucpArgs[0]) {
    $_useJsonCapture = $true
  }
}

if ($_useJsonCapture) {
  $r = Invoke-Cucp -ArgList $CucpArgs -CaptureJson
  if ($r.Raw) { [Console]::Out.Write($r.Raw) }
  if ($r.Err) { [Console]::Error.Write($r.Err) }
  $exitCode = $r.ExitCode
  # Promote envelope status=error to a non-zero exit so plan readiness etc.
  # fail loudly even when the CLI itself returned 0.
  if ($exitCode -eq 0 -and $r.Json -and $r.Json.status -eq "error") {
    $exitCode = 1
  }
  # Timeout path: raw stdout is empty; emit our envelope so callers always
  # have machine-readable evidence (command_id/elapsed_ms/recommended_action).
  if ($exitCode -eq 124 -and (-not $r.Raw) -and $r.Json) {
    [Console]::Out.WriteLine(($r.Json | ConvertTo-Json -Depth 4))
  }
} else {
  & node $Script:CliPath @CucpArgs
  $exitCode = $LASTEXITCODE
}

if ($exitCode -ne 0) {
  if ($exitCode -eq 124) {
    Write-Notice -Level "ERROR" -Message "CUCP CLI 타임아웃 (exit=124). InvokeTimeoutMs를 늘리거나 'cucp macro ensure-helper'를 실행해보세요."
  } else {
    Write-Notice -Level "ERROR" -Message "CUCP CLI 비정상 종료 (exit=$exitCode). 감사 로그: $Script:WrapperLog"
  }
} else {
  if (-not $Brief) { Write-Notice -Level "OK" -Message "완료 (exit=0)" }
}

exit $exitCode

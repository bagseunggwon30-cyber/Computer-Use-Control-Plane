# ============================================================================
# CUCP Native Desktop Helper (no Windows MCP / no Codex helper dependency)
# ============================================================================
# 이 helper는 외부 windows-mcp 또는 ~/.codex/bin/codex-win.ps1 helper에 의존하지
# 않고, Win32 API + UIAutomationClient + System.Drawing + Windows.Media.Ocr
# 만으로 다음을 제공합니다:
#
#   [관찰 / 탐색]
#   - window enum + foreground 추출 (EnumWindows + GetWindowText)
#   - UIA tree + label 매칭 (BoundingRectangle, Pattern 지원 여부)
#   - OCR (Windows.Media.Ocr): 화면/이미지 텍스트 + 좌표
#   - OCR+UIA fusion: OCR 좌표 위에 UIA element 가 있는지 + invoke 가능 여부
#
#   [actuation / 조작]
#   - mouse click (SendInput / mouse_event)
#   - keyboard text/shortcut (SendInput unicode + virtual-key)
#   - UIA Pattern 직접 호출 (InvokePattern.Invoke / TogglePattern.Toggle / SetValue)
#     → 마우스 안 움직임. BoundingRectangle 만으로 동작.
#   - OCR+UIA invoke: OCR 좌표 위 element 를 한 프로세스 안에서 직접 invoke
#     → UIA Name 비어있어도 AutomationId/ClassName 로 invoke
#
#   [출력]
#   - screenshot capture (Graphics.CopyFromScreen → PNG)
#   - screenshot diff (LockBits + Marshal.Copy 픽셀 비교, ignore-region 지원)
#
# ----------------------------------------------------------------------------
# 사용 방식:
#   powershell -NoProfile -ExecutionPolicy Bypass -File cucp-native-helper.ps1 \
#              -Action <action> [<옵션>] [-OutPath <file>]
#
# 모든 출력은 단일 JSON envelope (action / status / elapsed_ms 포함):
#   { status: "ok"|"error"|"partial", action, elapsed_ms, ... }
#
# Exit codes (CUCP 표준 — wrapper / Pester 도 같은 매핑 사용):
#   0   = ok
#   1   = generic failure / missing required argument
#   2   = partial (no_match, low_confidence, no_invoke_pattern 등 회복 가능)
#   3   = safety blocked (좌표 범위 초과 등 — 현재는 wrapper 가 주로 사용)
#   124 = timeout (wrapper 가 child kill 후 매핑)
#
# ----------------------------------------------------------------------------
# 함정 / 디자인 결정 (수정 시 주의):
#   - PowerShell 5.x 의 inline-if (`$x = if (cond) {...} else {...}`) 는 statement
#     context 에서 깨질 수 있음. 변수 미리 할당 패턴 사용.
#   - $args 는 PowerShell 자동 변수 — 함수 매개변수 이름으로 쓰면 충돌. $argList 로.
#   - JSON envelope 출력은 [Console]::Out.WriteLine 사용 (Write-Output 은 PowerShell
#     output stream 으로 가서 함수 return 값과 섞임 → JSON 깨짐).
#   - .ps1 파일은 한글 주석 보존을 위해 UTF-8 with BOM 으로 저장. 공백 라인 단위로
#     주석 끝 / 코드 시작 분리 (한 줄에 주석 + 코드 섞으면 PS5 가 코드를 주석으로 흡수).
#   - 모든 actuation action 은 wrapper 측에서 -AllowLiveControl 게이트 통과해야 함.
#     이 helper 자체는 게이트 안 잡음 (wrapper 책임).
# ============================================================================

  [CmdletBinding(PositionalBinding = $false)]
param(
  # 수행할 동작 — windows / focused / focus / screenshot / click / type /
  # shortcut / uia-tree / uia-find / uia-click / uia-invoke / uia-set-value /
  # uia-toggle / ocr-screen / ocr-image / ocr-find-text / ocr-uia-fuse /
  # ocr-uia-invoke / screenshot-diff / hit-test / hit-scan / cdp-detect / cdp-eval /
  # cdp-type / cdp-click / cdp-smart-click / cdp-smart-type / cdp-smart-find / cdp-smart-type-find / health
  # v1.4.0: ime-paste (한국어 IME 우회 클립보드 paste), modal-detect (UI recovery),
  #         cdp-deep-find (Shadow DOM/iframe 깊이 보고)
  [Parameter(Mandatory = $true)]
  [ValidateSet(
    "windows", "focused", "focus", "screenshot",
    "click", "type", "shortcut",
    "uia-tree", "uia-find", "uia-click",
    "uia-invoke", "uia-set-value", "uia-toggle",
    "ocr-screen", "ocr-image", "ocr-find-text",
    "ocr-uia-fuse", "ocr-uia-invoke", "screenshot-diff",
    "hit-test", "hit-scan",
    "cdp-detect", "cdp-eval", "cdp-type", "cdp-click",
    "cdp-smart-click", "cdp-smart-type", "cdp-smart-find", "cdp-smart-type-find",
    "cdp-deep-find",
    "cdp-prosemirror-insert",
    "ime-paste", "modal-detect",
    "health"
  )]
  [string]$Action,

  # window 검색용 (case-insensitive 부분 매칭, title 또는 process name)
  [string]$Match,

  # 좌표 기반 click/type 용
  [int]$X,
  [int]$Y,
  [ValidateSet("left", "right", "middle", "double")]
  [string]$Button = "left",

  # type 용 텍스트 (유니코드 그대로)
  [string]$Text,
  [switch]$ClearFirst,
  [switch]$PressEnter,

  # uia-set-value 전용 — UIA ValuePattern.SetValue 로 들어갈 값
  [string]$Value,

  # shortcut 용 (예: "ctrl+s", "alt+f4", "win+d")
  [string]$Keys,

  # screenshot 출력 경로
  [string]$OutPath,

  # screenshot 영역 (전체 가상 데스크톱이 기본)
  [int]$ScreenshotX = -1,
  [int]$ScreenshotY = -1,
  [int]$ScreenshotW = -1,
  [int]$ScreenshotH = -1,

  # UIA 검색 옵션
  [string]$Label,
  [string]$Role,
  [int]$MaxElements = 400,
  [int]$MinSize = 6,

  # 포커스 대상
  [string]$WindowTitle,
  [int]$WindowHwnd,

  # v1.2.0: hit-test 가드 — click/type/shortcut 직전 좌표가 의도한 윈도우 안인지 검증
  # - TargetHwnd: 정확한 hwnd 일치 검사
  # - TargetMatch: title 부분 매칭 (case-insensitive). hwnd 와 OR 관계.
  # 둘 다 비어있으면 가드 없음 (기존 동작). 하나라도 있으면 click/type 시 hit-test 후
  # 매칭 안 되면 exit 3 (safety blocked) + 기록.
  [int]$TargetHwnd,
  [string]$TargetMatch,
  [ValidateSet("none", "uia-safe")]
  [string]$ClickRefine = "none",
  [int]$ClickInset = 3,
  [int]$ScanRadius = 0,
  [int]$ScanStep = 6,
  [switch]$SkipUia,

  # v1.3.0: CDP 옵션
  # - CdpPort: Electron debug port (기본 9222)
  # - CdpPageMatch: /json/list 의 title 또는 url 부분 매칭 (Electron 앱은 보통 여러 페이지)
  # - CdpSelector: cdp-type / cdp-click 의 DOM 셀렉터 (예: "textarea", "button.send")
  # - CdpText: cdp-smart-click / cdp-smart-type / cdp-smart-find / cdp-smart-type-find 의 visible text/aria/placeholder label
  # - CdpExpr: cdp-eval 의 JavaScript expression
  # - CdpExprB64: cdp-eval 의 JavaScript expression (base64 인코딩, 긴 expression 또는
  #   특수문자 (`;` `:` `&`) 가 PowerShell argument parsing 에서 깨질 때 사용)
  [int]$CdpPort = 9222,
  # Explicit typed startup ceiling; never accepted from tool argument strings.
  [hashtable]$CdpStartup,
  [string]$CdpPageMatch,
  [string]$CdpSelector,
  [string]$CdpText,
  [string]$CdpExpr,
  [string]$CdpExprB64,

  # OCR 옵션
  # - OcrLanguage: "ko" / "en-US" — 비어있으면 사용자 언어 자동 선택 (TryCreateFromUserProfileLanguages)
  # - OcrPath: ocr-image 입력 PNG 경로
  # - OcrText: ocr-find-text 검색어 (case-insensitive 부분 일치 / score 매칭)
  # - OcrMatch: ocr-find-text 매칭 모드 (exact / contains / prefix / fuzzy). 기본 contains
  # - OcrMaxCandidates: ocr-find-text 결과 후보 최대 개수
  [string]$OcrLanguage,
  [string]$OcrPath,
  [string]$OcrText,
  [ValidateSet("exact", "contains", "prefix", "fuzzy")]
  [string]$OcrMatch = "contains",
  [int]$OcrMaxCandidates = 8,

  # screenshot-diff 옵션
  # - DiffBefore / DiffAfter: 비교 대상 PNG 경로
  # - DiffThreshold: per-pixel RGB 절대 차이가 N 이상이면 변화로 간주 (기본 16)
  # - DiffRegion: 비교 영역. 비어있으면 두 PNG 의 크기가 같다고 가정하고 전체 비교
  # - DiffIgnoreRegions: "x1,y1,w1,h1;x2,y2,w2,h2" 형식. 이 영역 안 픽셀은 비교에서 제외
  #   (동영상/애니메이션 영역 마스킹용 — v1.0.0)
  [string]$DiffBefore,
  [string]$DiffAfter,
  [int]$DiffThreshold = 16,
  [string]$DiffIgnoreRegions,

  # 일반 옵션
  [switch]$JsonOnly,
  [switch]$Quiet
)

$ErrorActionPreference = "Stop"
$Script:_HasCoordinates = $PSBoundParameters.ContainsKey("X") -and $PSBoundParameters.ContainsKey("Y")
try {
  [System.Console]::OutputEncoding = [System.Text.Encoding]::UTF8
  $OutputEncoding = [System.Text.Encoding]::UTF8
} catch { }

# ============================================================================
# Win32 P/Invoke surface (한 번만 컴파일)
# ============================================================================
# CUCP가 직접 호출하는 Win32 API들. 외부 라이브러리 없이 user32.dll 만 사용.
# - EnumWindows / GetWindowText / GetForegroundWindow / GetWindowRect: 윈도우 열거
# - SendInput / mouse_event / keybd_event: 입력 이벤트 주입
# - SetForegroundWindow / ShowWindow: 포커스 제어
# - GetCursorPos / SetCursorPos: 커서 위치 조회/설정
# ============================================================================
$Script:_Win32Loaded = $false
$Script:LegacyCdpSourceRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
. (Join-Path $PSScriptRoot 'cucp-legacy-cdp-adapter.ps1')

function _Ensure-Win32Native {
  if ($Script:_Win32Loaded) { return $true }
  try {
    $interopPath = $env:CUCP_LEGACY_INTEROP_DLL
    if (-not $interopPath) { $interopPath = Join-Path $PSScriptRoot '..\pcucp-next\bin\legacy\PcuCp.LegacyInterop.dll' }
    $existing = 'CucpNative' -as [type]
    if ($existing -and $existing.Assembly.GetName().Name -ne 'PcuCp.LegacyInterop') {
      throw 'A different legacy interop type is already loaded. Restart this PowerShell process with the matching runtime.'
    }
    if (-not $existing) {
      if (-not (Test-Path -LiteralPath $interopPath -PathType Leaf)) { throw 'Legacy interop DLL missing. Run python pcucp-next/packaging/publish_legacy_interop.py or set CUCP_LEGACY_INTEROP_DLL.' }
      Add-Type -LiteralPath $interopPath -ErrorAction Stop
    }
    try { [void][CucpNative]::SetProcessDPIAware() } catch { }
    $Script:_Win32Loaded = $true
    return $true
  } catch {
    Write-Error ("native helper P/Invoke load failed: " + $_.Exception.Message)
    return $false
  }
}

# ============================================================================
# UIAutomationClient assembly (UIA tree access)
# ============================================================================
$Script:_UIALoaded = $false
function _Ensure-UIA {
  if ($Script:_UIALoaded) { return $true }
  try {
    Add-Type -AssemblyName UIAutomationClient -ErrorAction Stop
    Add-Type -AssemblyName UIAutomationTypes -ErrorAction Stop
    Add-Type -AssemblyName WindowsBase -ErrorAction Stop
    $Script:_UIALoaded = $true
    return $true
  } catch {
    return $false
  }
}

# ============================================================================
# Windows.Media.Ocr (UWP Runtime API) — 외부 의존 0
# ============================================================================
# Windows 10/11 기본 내장 OCR 엔진. 별도 설치 불필요.
# 사용자 언어 설정에 따라 한국어/영어/일본어/중국어 등 25+ 언어 지원.
# 브라우저 캔버스 / 이미지 안 텍스트 / Electron 커스텀 그리기 표면처럼
# UIA로 안 잡히는 표면을 OCR text+BoundingRect 로 좌표 결정 가능.
# ============================================================================
$Script:_OCRLoaded = $false
$Script:_OCREngine = $null
$Script:_OCRError = $null

function _Require-LegacyImages {
  if ('PcuCp.LegacyImages.FileOcr' -as [type]) { return }
  $dll = $env:CUCP_LEGACY_IMAGES_DLL
  if (-not $dll) { $dll = Join-Path $PSScriptRoot '..\pcucp-next\bin\legacy\PcuCp.LegacyImages.dll' }
  if (-not (Test-Path -LiteralPath $dll -PathType Leaf)) { throw 'Legacy images DLL missing. Run python pcucp-next/packaging/publish_legacy_images.py or set CUCP_LEGACY_IMAGES_DLL.' }
  Add-Type -LiteralPath $dll -ErrorAction Stop
}

function _Ensure-OCR {
  if ($Script:_OCRLoaded) { return ($null -ne $Script:_OCREngine) }
  $Script:_OCRLoaded = $true
  try {
    _Require-LegacyImages
    $session = New-Object PcuCp.LegacyImages.FileOcrSession
    $available = $session.Ensure($OcrLanguage)
    $Script:_OCREngine = $session.Engine
    $Script:_OCRError = $session.Error
    return $available
  } catch {
    $Script:_OCRError = $_.Exception.Message
    return $false
  }
}

# IAsyncOperation<T> -> .Result wait helper. PS 5.x에서 await 흉내.
function _Wait-AsyncOp {
  param($AsyncOp, [Type]$ResultType)
  _Require-LegacyImages
  $result = [PcuCp.LegacyImages.FileOcr]::TryWaitAsyncOperation($AsyncOp, $ResultType)
  if ($null -ne $result.Error) { throw $result.Error }
  return $result.Value
}

# PNG 파일 -> SoftwareBitmap (OcrEngine.RecognizeAsync 입력 형식)
function _Load-SoftwareBitmapFromFile {
  param([string]$Path)
  _Require-LegacyImages
  $result = [PcuCp.LegacyImages.FileOcr]::TryLoadSoftwareBitmapFromFile($Path)
  if ($null -ne $result.Error) { throw $result.Error }
  return $result.Value
}

# OcrResult를 결정론적 JSON-friendly 구조로 변환 (offset_x/offset_y 적용 가능)
function _Convert-OcrResult {
  param($OcrResult, [int]$OffsetX = 0, [int]$OffsetY = 0)
  _Require-LegacyImages
  return [PcuCp.LegacyImages.FileOcr]::ConvertResult($OcrResult, $OffsetX, $OffsetY)
}

# ocr-find-text matching score. 0..100.
# exact/prefix/contains stay deterministic; fuzzy is opt-in to avoid unsafe clicks.
function _Capture-ScreenRegionToTempPng {
  param(
    [int]$RegionX,
    [int]$RegionY,
    [int]$RegionW,
    [int]$RegionH,
    [string]$Prefix = "cucp-cap"
  )
  Add-Type -AssemblyName System.Drawing -ErrorAction Stop
  $vx = [CucpNative]::GetSystemMetrics([CucpNative]::SM_XVIRTUALSCREEN)
  $vy = [CucpNative]::GetSystemMetrics([CucpNative]::SM_YVIRTUALSCREEN)
  $vw = [CucpNative]::GetSystemMetrics([CucpNative]::SM_CXVIRTUALSCREEN)
  $vh = [CucpNative]::GetSystemMetrics([CucpNative]::SM_CYVIRTUALSCREEN)
  # PS 5.x inline-if 함정 회피: 변수 미리 할당
  $sx = $vx; if ($RegionX -ge 0) { $sx = $RegionX }
  $sy = $vy; if ($RegionY -ge 0) { $sy = $RegionY }
  $sw = $vw; if ($RegionW -gt 0) { $sw = $RegionW }
  $sh = $vh; if ($RegionH -gt 0) { $sh = $RegionH }

  # OCR 엔진의 픽셀 한도 (보통 10000) 검사
  $maxDim = 10000
  try { $maxDim = [Windows.Media.Ocr.OcrEngine]::MaxImageDimension } catch { }
  if ($sw -gt $maxDim -or $sh -gt $maxDim) {
    return [pscustomobject]@{
      Path = $null; X = $sx; Y = $sy; W = $sw; H = $sh
      Error = "region_exceeds_max_image_dimension"; MaxDim = $maxDim
    }
  }

  $tmp = [System.IO.Path]::Combine([System.IO.Path]::GetTempPath(),
    "$Prefix-$([System.Guid]::NewGuid().ToString('N')).png")
  $bmp = New-Object System.Drawing.Bitmap $sw, $sh
  $g = [System.Drawing.Graphics]::FromImage($bmp)
  try {
    $g.CopyFromScreen($sx, $sy, 0, 0, (New-Object System.Drawing.Size $sw, $sh))
    $bmp.Save($tmp, [System.Drawing.Imaging.ImageFormat]::Png)
  } catch {
    return [pscustomobject]@{
      Path = $null; X = $sx; Y = $sy; W = $sw; H = $sh
      Error = "screenshot_unavailable"; Detail = $_.Exception.Message
    }
  } finally {
    $g.Dispose()
    $bmp.Dispose()
  }
  return [pscustomobject]@{
    Path = $tmp; X = $sx; Y = $sy; W = $sw; H = $sh; Error = $null
  }
}

# _Convert-OcrResult body -> OCR candidates.
# Includes line, word, and adjacent 2/3-word n-grams so labels like
# "Save As" or "Send Message" get a tighter center than the whole line.
function _Match-OcrCandidates {
  param($Body, [string]$Needle, [string]$Mode)
  # Compatibility only: matching now lives in the bounded C# kernel. No shell or desktop calls.
  $native = $env:CUCP_NATIVE_HOST
  if (-not $native) { $native = Join-Path $PSScriptRoot '..\pcucp-next\bin\native\PcuCp.NativeHost.exe' }
  $native = [System.IO.Path]::GetFullPath($native)
  if (-not (Test-Path -LiteralPath $native -PathType Leaf)) {
    throw 'Matching native runtime missing. Publish pcucp-next/packaging/publish_native.py or set CUCP_NATIVE_HOST to the matching executable/DLL.'
  }
  $psi = New-Object System.Diagnostics.ProcessStartInfo
  $extension = [System.IO.Path]::GetExtension($native).ToLowerInvariant()
  if ($extension -eq '.dll') {
    $dotnet = Get-Command dotnet.exe -CommandType Application -ErrorAction Stop
    if ($native.Contains('"') -or $native.Contains("`r") -or $native.Contains("`n")) { throw 'Invalid native DLL path' }
    $psi.FileName = $dotnet.Source
    $psi.Arguments = '"' + $native + '" legacy-ocr-match'
  } elseif ($extension -eq '.exe') {
    $psi.FileName = $native
    $psi.Arguments = 'legacy-ocr-match'
  } else { throw 'CUCP_NATIVE_HOST must be an executable or DLL, never a shell script.' }
  $payload = @{schema='cucp.legacy-ocr-match/v1'; body=$Body; needle=$Needle; mode=$Mode; culture=[Globalization.CultureInfo]::CurrentCulture.Name} | ConvertTo-Json -Depth 24 -Compress
  $utf8 = New-Object System.Text.UTF8Encoding($false, $true)
  $bytes = $utf8.GetBytes($payload)
  if ($bytes.Length -gt 1048576) { throw 'Legacy OCR request exceeds 1 MiB.' }
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
      throw 'Legacy OCR matching timed out; no retry was attempted.'
    }
    $out = $stdout.GetAwaiter().GetResult()
    $err = $stderr.GetAwaiter().GetResult()
    if ($out.Length -gt 16777216 -or $err.Length -gt 65536) { throw 'Legacy OCR response exceeds the protocol budget.' }
    $response = $out | ConvertFrom-Json -ErrorAction Stop
    if ($process.ExitCode -ne 0 -or $response.status -ne 'ok' -or $response.data.compatibility -ne 'legacy-dotnet-utf16/v1') {
      throw ('Legacy OCR matching failed; rebuild matching native runtime. ' + ($response.errors | ConvertTo-Json -Compress))
    }
    return @($response.data.candidates)
  } finally { $process.Dispose() }
}

function _Get-UiaSupportedPatternName {
  param($Element)
  if (-not $Element) { return $null }
  try {
    $p = $Element.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern)
    if ($p) { return "InvokePattern" }
  } catch { }
  try {
    $p = $Element.GetCurrentPattern([System.Windows.Automation.TogglePattern]::Pattern)
    if ($p) { return "TogglePattern" }
  } catch { }
  try {
    $p = $Element.GetCurrentPattern([System.Windows.Automation.SelectionItemPattern]::Pattern)
    if ($p) { return "SelectionItemPattern" }
  } catch { }
  return $null
}

function _New-UiaMatchPayload {
  param($Cur, [string]$PatternName)
  $r = $Cur.BoundingRectangle
  $name = ""; try { $name = "$($Cur.Name)" } catch { }
  $autoId = ""; try { $autoId = "$($Cur.AutomationId)" } catch { }
  $localizedRole = ""; try { $localizedRole = $Cur.LocalizedControlType } catch { }
  $clazz = ""; try { $clazz = "$($Cur.ClassName)" } catch { }
  $enabled = $true; try { $enabled = [bool]$Cur.IsEnabled } catch { }
  $offscreen = $false; try { $offscreen = [bool]$Cur.IsOffscreen } catch { }
  $preferredId = "none"
  if ($name -and $name.Trim().Length -gt 0) { $preferredId = "name" }
  elseif ($autoId -and $autoId.Trim().Length -gt 0) { $preferredId = "automation_id" }
  elseif ($clazz -and $clazz.Trim().Length -gt 0) { $preferredId = "class_name" }
  return [ordered]@{
    name = $name
    automation_id = $autoId
    class_name = $clazz
    role = $localizedRole
    rect = [ordered]@{ x=[int]$r.X; y=[int]$r.Y; width=[int]$r.Width; height=[int]$r.Height }
    center = [ordered]@{ x=[int]($r.X + $r.Width / 2); y=[int]($r.Y + $r.Height / 2) }
    area = [int]($r.Width * $r.Height)
    is_enabled = $enabled
    is_offscreen = $offscreen
    invoke_pattern = $PatternName
    preferred_identifier = $preferredId
  }
}

function _Get-RoleWeight {
  param([string]$Role)
  if (-not $Role) { return 0 }
  $r = $Role.ToLowerInvariant()
  if ($r -match 'button|hyperlink|menu item|tab|check|radio|combo|split button') { return 40 }
  if ($r -match 'edit|document|list item|tree item|data item') { return 18 }
  if ($r -match 'pane|window|group|custom') { return -8 }
  return 0
}

function _Clamp-UiaPointToRect {
  param(
    [double]$X,
    [double]$Y,
    $Rect,
    [int]$Inset = 3,
    [string]$Source = "center",
    [bool]$NativeClickable = $false
  )
  if (-not $Rect -or $Rect.IsEmpty -or $Rect.Width -le 0 -or $Rect.Height -le 0) { return $null }
  $safeInset = [Math]::Max(0, $Inset)
  $insetX = [Math]::Min([double]$safeInset, [Math]::Max(0.0, ([double]$Rect.Width - 1.0) / 2.0))
  $insetY = [Math]::Min([double]$safeInset, [Math]::Max(0.0, ([double]$Rect.Height - 1.0) / 2.0))
  $minX = [double]$Rect.X + $insetX
  $maxX = [double]$Rect.X + [double]$Rect.Width - $insetX
  $minY = [double]$Rect.Y + $insetY
  $maxY = [double]$Rect.Y + [double]$Rect.Height - $insetY
  if ($maxX -lt $minX) { $minX = [double]$Rect.X + ([double]$Rect.Width / 2.0); $maxX = $minX }
  if ($maxY -lt $minY) { $minY = [double]$Rect.Y + ([double]$Rect.Height / 2.0); $maxY = $minY }
  $cx = [Math]::Max($minX, [Math]::Min($maxX, $X))
  $cy = [Math]::Max($minY, [Math]::Min($maxY, $Y))
  return [pscustomobject]@{
    X = [int][Math]::Round($cx)
    Y = [int][Math]::Round($cy)
    Source = $Source
    NativeClickable = $NativeClickable
  }
}

function _Get-UiaPreferredClickPoint {
  param(
    $Element,
    $Rect,
    [int]$Inset = 3
  )
  if (-not $Element -or -not $Rect -or $Rect.IsEmpty) { return $null }

  try {
    $pt = New-Object System.Windows.Point
    $ok = $Element.TryGetClickablePoint([ref]$pt)
    if ($ok) {
      return (_Clamp-UiaPointToRect -X ([double]$pt.X) -Y ([double]$pt.Y) -Rect $Rect -Inset $Inset -Source "clickable_point" -NativeClickable $true)
    }
  } catch { }

  $centerX = [double]$Rect.X + ([double]$Rect.Width / 2.0)
  $centerY = [double]$Rect.Y + ([double]$Rect.Height / 2.0)
  return (_Clamp-UiaPointToRect -X $centerX -Y $centerY -Rect $Rect -Inset $Inset -Source "rect_center" -NativeClickable $false)
}

function _Resolve-UiaPointRefinement {
  param(
    [int]$X,
    [int]$Y,
    [int]$MaxWidth = 360,
    [int]$MaxHeight = 220,
    [int]$Inset = 3
  )
  if (-not (_Ensure-UIA)) { return $null }
  try {
    $pt = New-Object System.Windows.Point($X, $Y)
    $el = [System.Windows.Automation.AutomationElement]::FromPoint($pt)
  } catch { return $null }
  if (-not $el) { return $null }

  $walker = [System.Windows.Automation.TreeWalker]::ControlViewWalker
  $best = $null
  for ($depth = 0; $depth -le 5 -and $el; $depth++) {
    try {
      $cur = $el.Current
      $r = $cur.BoundingRectangle
      if (-not $r.IsEmpty -and $r.Width -gt 1 -and $r.Height -gt 1) {
        $pattern = _Get-UiaSupportedPatternName -Element $el
        $role = ""; try { $role = "$($cur.LocalizedControlType)" } catch { }
        $enabled = $true; try { $enabled = [bool]$cur.IsEnabled } catch { }
        $offscreen = $false; try { $offscreen = [bool]$cur.IsOffscreen } catch { }
        $area = [double]($r.Width * $r.Height)
        $bounded = ($r.Width -le $MaxWidth -and $r.Height -le $MaxHeight)
        $roleWeight = _Get-RoleWeight -Role $role
        $score = 0
        if ($pattern) { $score += 80 }
        $score += $roleWeight
        if ($bounded) { $score += 30 } else { $score -= 45 }
        if ($enabled) { $score += 10 } else { $score -= 40 }
        if ($offscreen) { $score -= 60 }
        if ($depth -gt 0) { $score -= ($depth * 4) }
        if ($area -le 800) { $score += 10 }
        if ($area -gt 120000) { $score -= 30 }

        $point = $null
        try { $point = _Get-UiaPreferredClickPoint -Element $el -Rect $r -Inset $Inset } catch { $point = $null }
        if ($point -and $point.NativeClickable) { $score += 8 }

        if ($score -ge 45 -and $point) {
          $payload = _New-UiaMatchPayload -Cur $cur -PatternName $pattern
          $candidate = [pscustomobject]@{
            X = [int]$point.X
            Y = [int]$point.Y
            Score = $score
            Depth = $depth
            PatternName = $pattern
            Role = $role
            Area = $area
            PointSource = $point.Source
            NativeClickable = [bool]$point.NativeClickable
            Match = $payload
          }
          if (-not $best -or $candidate.Score -gt $best.Score) { $best = $candidate }
        }
      }
      $parent = $null
      try { $parent = $walker.GetParent($el) } catch { $parent = $null }
      if (-not $parent) { break }
      $el = $parent
    } catch { break }
  }
  return $best
}

function _Find-SmallestUiaElementAtPoint {
  param($Elements, [int]$X, [int]$Y)
  $bestArea = [double]::MaxValue
  $bestEl = $null
  $bestCur = $null
  foreach ($el in $Elements) {
    try {
      $cur = $el.Current
      $r = $cur.BoundingRectangle
      if ($r.IsEmpty) { continue }
      if ($X -lt $r.X -or $X -gt ($r.X + $r.Width)) { continue }
      if ($Y -lt $r.Y -or $Y -gt ($r.Y + $r.Height)) { continue }
      $area = [double]($r.Width * $r.Height)
      if ($area -lt $bestArea) {
        $bestArea = $area
        $bestEl = $el
        $bestCur = $cur
      }
    } catch { continue }
  }
  if (-not $bestEl) { return $null }
  return [pscustomobject]@{ Element=$bestEl; Current=$bestCur; Area=$bestArea }
}

function _Resolve-OcrUiaFusionCandidate {
  param(
    $RootEl,
    $Elements,
    [object[]]$OcrCandidates,
    [int]$Limit = 8
  )
  $results = @()
  $walker = [System.Windows.Automation.TreeWalker]::ControlViewWalker
  $limited = @($OcrCandidates | Select-Object -First $Limit)
  foreach ($ocr in $limited) {
    $cx = [int]$ocr.cx
    $cy = [int]$ocr.cy
    $hit = _Find-SmallestUiaElementAtPoint -Elements $Elements -X $cx -Y $cy
    if (-not $hit) { continue }
    $el = $hit.Element
    for ($depth = 0; $depth -le 6 -and $el; $depth++) {
      try {
        $cur = $el.Current
        $r = $cur.BoundingRectangle
        if ($r.IsEmpty) { break }
        $pattern = _Get-UiaSupportedPatternName -Element $el
        $payload = _New-UiaMatchPayload -Cur $cur -PatternName $pattern
        $role = ""; try { $role = "$($cur.LocalizedControlType)" } catch { }
        $enabled = $true; try { $enabled = [bool]$cur.IsEnabled } catch { }
        $offscreen = $false; try { $offscreen = [bool]$cur.IsOffscreen } catch { }
        $fusionScore = [int]$ocr.score
        if ($pattern) { $fusionScore += 100 }
        if ($role -match 'button|menu|hyperlink|tab|list item|check|radio') { $fusionScore += 20 }
        if ($enabled) { $fusionScore += 10 } else { $fusionScore -= 20 }
        if ($offscreen) { $fusionScore -= 30 }
        if ($depth -gt 0) { $fusionScore -= ($depth * 3) }
        $results += [pscustomobject]@{
          Ocr = $ocr
          Element = $el
          Current = $cur
          PatternName = $pattern
          CanInvoke = [bool]$pattern
          UiaMatch = $payload
          FusionScore = $fusionScore
          ParentClimbDepth = $depth
        }
        if ($pattern) { break }
        $parent = $null
        try { $parent = $walker.GetParent($el) } catch { $parent = $null }
        if (-not $parent) { break }
        try { if ($parent.Equals($RootEl)) { break } } catch { }
        $el = $parent
      } catch { break }
    }
  }
  $ranked = @($results | Sort-Object -Property @{Expression="CanInvoke";Descending=$true}, @{Expression="FusionScore";Descending=$true}, @{Expression={ [int]$_.Ocr.score };Descending=$true})
  if ($ranked.Count -gt 0) { return $ranked[0] }
  return $null
}

# ============================================================================
# v1.3.0 — Chrome DevTools Protocol (CDP) 통합
# ============================================================================
# Electron 앱 (Electron app / VS Code / Slack / Discord 등) 의 DOM 직접 제어를 위한
# CDP 클라이언트. 좌표 / Win32 SendInput / UIA 우회 — DOM API 로 element 직접
# focus / value set / dispatchEvent.
#
# 사용 흐름:
#   1. Electron 앱이 --remote-debugging-port=9222 옵션으로 떠있어야 함
#   2. cdp-detect 로 9222 포트 + 페이지 목록 확인
#   3. cdp-eval 로 임의 JavaScript 실행
#   4. cdp-type / cdp-click 으로 selector 기반 actuation
#
# 설계 결정:
#   - HttpClient 대신 .NET WebRequest (PS 5.x 기본 .NET 4.x 에서 안정)
#   - WebSocket 은 ClientWebSocket 사용 (System.Net.WebSockets, .NET 4.5+)
#   - 단일 WS connection 으로 여러 CDP 명령 전송 → race condition 없음
#   - JSON message id auto-increment, response correlation by id
# ============================================================================

# CDP HTTP endpoint 호출 — /json/version, /json/list 등


# CDP WebSocket 단일 명령 호출 — open + send + recv (until matching id) + close
# 다중 명령은 호출자가 각각 호출 (간단함 우선, 성능 원하면 향후 connection pool)






# CDP 자동 detect — 9222 포트 + Electron 앱 페이지 목록
# 반환: { available, version, pages[] (id, title, url, webSocketDebuggerUrl) }


# ============================================================================
# Output helpers
# ============================================================================
$Script:_StartedAt = Get-Date

function _Emit { param($Payload, [int]$ExitCode = 0)
  $elapsed = [int]((Get-Date) - $Script:_StartedAt).TotalMilliseconds
  if ($Payload -is [hashtable] -or $Payload -is [System.Collections.Specialized.OrderedDictionary]) {
    $Payload["elapsed_ms"] = $elapsed
    $Payload["action"] = $Action
    $obj = [pscustomobject]$Payload
  } else {
    $obj = $Payload
    if ($obj -and -not ($obj.PSObject.Properties.Name -contains "elapsed_ms")) {
      $obj | Add-Member -NotePropertyName elapsed_ms -NotePropertyValue $elapsed -Force
    }
    if ($obj -and -not ($obj.PSObject.Properties.Name -contains "action")) {
      $obj | Add-Member -NotePropertyName action -NotePropertyValue $Action -Force
    }
  }
  [Console]::Out.WriteLine(($obj | ConvertTo-Json -Depth 8))
  exit $ExitCode
}

# ============================================================================
# Action: health  ─ helper 자체 검증
# ============================================================================
function _Action-Health {
  $win32 = _Ensure-Win32Native
  $uia = _Ensure-UIA
  $ocr = _Ensure-OCR
  $ocrLangs = @()
  if ($ocr) {
    try {
      foreach ($l in [Windows.Media.Ocr.OcrEngine]::AvailableRecognizerLanguages) {
        $ocrLangs += $l.LanguageTag
      }
    } catch { }
  }
  $payload = [ordered]@{
    status = if ($win32) { "ok" } else { "error" }
    win32 = $win32
    uia = $uia
    ocr = $ocr
    ocr_languages = $ocrLangs
    ocr_engine_language = if ($Script:_OCREngine) { $Script:_OCREngine.RecognizerLanguage.LanguageTag } else { $null }
    ocr_error = $Script:_OCRError
    psversion = "$($PSVersionTable.PSVersion)"
    pid = $PID
  }
  $exitCode = 1
  if ($win32) { $exitCode = 0 }
  _Emit $payload $exitCode
}

# ============================================================================
# Action: windows  ─ EnumWindows 기반 윈도우 목록
# ============================================================================
function _Action-Windows {
  if (-not (_Ensure-Win32Native)) { _Emit @{status="error"; reason="win32_load_failed"} 1 }
  $list = [CucpNative]::EnumerateTopLevel()
  $items = @()
  foreach ($w in $list) {
    if ($Match) {
      $needle = $Match.ToLowerInvariant()
      $tt = if ($w.Title) { $w.Title.ToLowerInvariant() } else { "" }
      $pp = if ($w.ProcessName) { $w.ProcessName.ToLowerInvariant() } else { "" }
      if ($tt.IndexOf($needle) -lt 0 -and $pp.IndexOf($needle) -lt 0) { continue }
    }
    $items += [ordered]@{
      hwnd = [int64]$w.Hwnd
      title = $w.Title
      class = $w.ClassName
      pid = [int]$w.Pid
      process = $w.ProcessName
      visible = $w.Visible
      minimized = $w.Minimized
      foreground = $w.Foreground
      rect = [ordered]@{ x=$w.X; y=$w.Y; width=$w.Width; height=$w.Height }
    }
  }
  _Emit ([ordered]@{
    status = "ok"
    match = $Match
    count = $items.Count
    windows = $items
  })
}

# ============================================================================
# Action: focused  ─ foreground window 한 개 반환
# ============================================================================
function _Action-Focused {
  if (-not (_Ensure-Win32Native)) { _Emit @{status="error"; reason="win32_load_failed"} 1 }
  $list = [CucpNative]::EnumerateTopLevel()
  $fg = $list | Where-Object { $_.Foreground } | Select-Object -First 1
  if (-not $fg) { _Emit @{status="partial"; reason="no_foreground_window"} 2 }
  _Emit ([ordered]@{
    status = "ok"
    foreground = [ordered]@{
      hwnd = [int64]$fg.Hwnd
      title = $fg.Title
      class = $fg.ClassName
      pid = [int]$fg.Pid
      process = $fg.ProcessName
      rect = [ordered]@{ x=$fg.X; y=$fg.Y; width=$fg.Width; height=$fg.Height }
    }
  })
}

# ============================================================================
# Action: focus  ─ 윈도우 포커스 (BringWindowToTop + SetForegroundWindow)
# ============================================================================
function _Action-Focus {
  if (-not (_Ensure-Win32Native)) { _Emit @{status="error"; reason="win32_load_failed"} 1 }
  $hwnd = [IntPtr]::Zero
  if ($WindowHwnd -gt 0) { $hwnd = [IntPtr]$WindowHwnd }
  elseif ($WindowTitle) {
    $list = [CucpNative]::EnumerateTopLevel()
    $needle = $WindowTitle.ToLowerInvariant()
    $hit = $list | Where-Object { $_.Title -and $_.Title.ToLowerInvariant().Contains($needle) } | Select-Object -First 1
    if ($hit) { $hwnd = $hit.Hwnd }
  } else {
    _Emit @{status="error"; reason="missing_target"; recommended_action="provide -WindowHwnd or -WindowTitle"} 1
  }
  if ($hwnd -eq [IntPtr]::Zero) {
    _Emit @{status="partial"; reason="no_matching_window"; window_title=$WindowTitle; window_hwnd=$WindowHwnd} 2
  }
  [void][CucpNative]::ShowWindow($hwnd, [CucpNative]::SW_RESTORE)
  [void][CucpNative]::BringWindowToTop($hwnd)
  $ok = [CucpNative]::SetForegroundWindow($hwnd)
  Start-Sleep -Milliseconds 80
  $newFg = [CucpNative]::GetForegroundWindow()
  $verified = ($newFg -eq $hwnd)
  $statusStr = "partial"; $exitCode = 2
  if ($verified) { $statusStr = "ok"; $exitCode = 0 }
  _Emit ([ordered]@{
    status = $statusStr
    set_foreground_returned = $ok
    verified = $verified
    target_hwnd = [int64]$hwnd
    actual_foreground_hwnd = [int64]$newFg
  }) $exitCode
}

# ============================================================================
# Action: screenshot  ─ Graphics.CopyFromScreen → PNG 파일
# ============================================================================
function _Action-Screenshot {
  if (-not $OutPath) {
    _Emit @{status="error"; reason="missing_outpath"; recommended_action="provide -OutPath <png file>"} 1
  }
  if (-not (_Ensure-Win32Native)) { _Emit @{status="error"; reason="win32_load_failed"} 1 }
  Add-Type -AssemblyName System.Drawing -ErrorAction Stop

  # 영역 결정: 명시 지정 없으면 전체 가상 데스크톱
  $vx = [CucpNative]::GetSystemMetrics([CucpNative]::SM_XVIRTUALSCREEN)
  $vy = [CucpNative]::GetSystemMetrics([CucpNative]::SM_YVIRTUALSCREEN)
  $vw = [CucpNative]::GetSystemMetrics([CucpNative]::SM_CXVIRTUALSCREEN)
  $vh = [CucpNative]::GetSystemMetrics([CucpNative]::SM_CYVIRTUALSCREEN)

  $sx = if ($ScreenshotX -ge 0) { $ScreenshotX } else { $vx }
  $sy = if ($ScreenshotY -ge 0) { $ScreenshotY } else { $vy }
  $sw = if ($ScreenshotW -gt 0) { $ScreenshotW } else { $vw }
  $sh = if ($ScreenshotH -gt 0) { $ScreenshotH } else { $vh }

  $bmp = $null
  $g = $null
  try {
    $bmp = New-Object System.Drawing.Bitmap $sw, $sh
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $g.CopyFromScreen($sx, $sy, 0, 0, (New-Object System.Drawing.Size $sw, $sh))
  } catch {
    if ($g) { $g.Dispose() }
    if ($bmp) { $bmp.Dispose() }
    _Emit ([ordered]@{
      status = "partial"
      reason = "screenshot_unavailable"
      detail = $_.Exception.Message
      recommended_action = "Run from an interactive unlocked desktop session, or retry with a smaller visible region."
      out_path = $OutPath
      rect = [ordered]@{ x=$sx; y=$sy; width=$sw; height=$sh }
    }) 2
  } finally {
    if ($g) { $g.Dispose() }
  }

  # 출력 폴더 생성
  $dir = Split-Path -Parent $OutPath
  if ($dir -and -not (Test-Path -LiteralPath $dir)) {
    New-Item -ItemType Directory -Path $dir -Force | Out-Null
  }
  $bmp.Save($OutPath, [System.Drawing.Imaging.ImageFormat]::Png)
  $bmp.Dispose()

  _Emit ([ordered]@{
    status = "ok"
    out_path = $OutPath
    rect = [ordered]@{ x=$sx; y=$sy; width=$sw; height=$sh }
    bytes = (Get-Item -LiteralPath $OutPath).Length
  })
}

# ============================================================================
# v1.2.0: hit-test 헬퍼 + click/type 사전 검증
# ============================================================================
# 목표: 라이브 actuation (click / type / shortcut) 직전에 좌표가 진짜 의도한
# 윈도우 안인지 Win32 WindowFromPoint 로 검증.
#
# 사고 사례:
#   1. click (1500, 935) — Electron app 가 전체화면일 땐 codex 패널, 창모드일 땐 코드 에디터
#   2. click (1700, 945) — toolbar 의 maximize 영역에 떨어져서 창 모드 토글
#
# 해결: click 직전에 _Test-CoordsInTarget 호출 → 다른 윈도우면 exit 3 (블록).
# ============================================================================

# 좌표가 -TargetHwnd 또는 -TargetMatch (title 부분일치) 와 매칭되는지 검사.
# 반환: PSCustomObject { matched, actual_hwnd, actual_root_hwnd, actual_title, reason }
function _Test-CoordsInTarget {
  param(
    [int]$X,
    [int]$Y,
    [int]$ExpectedHwnd,
    [string]$ExpectedMatch
  )
  $pt = New-Object CucpNative+POINT
  $pt.X = $X; $pt.Y = $Y
  $childHwnd = [CucpNative]::WindowFromPoint($pt)
  if ($childHwnd -eq [IntPtr]::Zero) {
    return [pscustomobject]@{
      matched = $false; actual_hwnd = 0; actual_root_hwnd = 0
      actual_title = ""; reason = "no_window_at_coords"
    }
  }
  $rootHwnd = [CucpNative]::GetAncestor($childHwnd, [CucpNative]::GA_ROOT)
  # title 추출
  $sb = New-Object System.Text.StringBuilder 256
  [void][CucpNative]::GetWindowText($rootHwnd, $sb, 256)
  $title = $sb.ToString()

  # 가드 매칭 — TargetHwnd 우선, 없으면 TargetMatch (title 부분일치)
  $matched = $false
  $reason = ""
  if ($ExpectedHwnd -gt 0) {
    $matched = ([int64]$rootHwnd -eq [int64]$ExpectedHwnd)
    if (-not $matched) { $reason = "hwnd_mismatch" }
  } elseif ($ExpectedMatch) {
    $needle = $ExpectedMatch.ToLowerInvariant()
    if ($title -and $title.ToLowerInvariant().Contains($needle)) { $matched = $true }
    else { $reason = "title_mismatch" }
  } else {
    # 가드 명시 없음 — 통과
    $matched = $true
  }

  return [pscustomobject]@{
    matched = $matched
    actual_hwnd = [int64]$childHwnd
    actual_root_hwnd = [int64]$rootHwnd
    actual_title = $title
    reason = $reason
  }
}

# ============================================================================
# Action: hit-test  ─ 좌표가 어떤 윈도우에 있는지 read-only 조회
# ============================================================================
# 입력: -X <n> -Y <n>
# 출력: { hwnd, root_hwnd, title, process, class }
# read-only — 클릭하지 않음. wrapper 가 dry-run 검증할 때 사용.
# ============================================================================
function _Action-HitTest {
  if (-not (_Ensure-Win32Native)) { _Emit @{status="error"; reason="win32_load_failed"} 1 }
  if (-not $Script:_HasCoordinates) {
    _Emit @{status="error"; reason="missing_coords"; recommended_action="provide -X and -Y (zero and negative screen coordinates are valid)"} 1
  }
  $pt = New-Object CucpNative+POINT
  $pt.X = $X; $pt.Y = $Y
  $childHwnd = [CucpNative]::WindowFromPoint($pt)
  if ($childHwnd -eq [IntPtr]::Zero) {
    _Emit @{status="partial"; reason="no_window_at_coords"; x=$X; y=$Y} 2
  }
  $rootHwnd = [CucpNative]::GetAncestor($childHwnd, [CucpNative]::GA_ROOT)
  $sb = New-Object System.Text.StringBuilder 256
  [void][CucpNative]::GetWindowText($rootHwnd, $sb, 256)
  $rootTitle = $sb.ToString()
  $sb2 = New-Object System.Text.StringBuilder 256
  [void][CucpNative]::GetWindowText($childHwnd, $sb2, 256)
  $childTitle = $sb2.ToString()
  $sbCls = New-Object System.Text.StringBuilder 256
  [void][CucpNative]::GetClassName($rootHwnd, $sbCls, 256)
  $rootClass = $sbCls.ToString()
  $procId = [uint32]0
  [void][CucpNative]::GetWindowThreadProcessId($rootHwnd, [ref]$procId)
  $procName = ""
  try { $procName = (Get-Process -Id $procId -ErrorAction SilentlyContinue).ProcessName } catch { }
  $uiaPoint = $null
  if (-not $SkipUia) {
    try { $uiaPoint = _Resolve-UiaPointRefinement -X $X -Y $Y -Inset $ClickInset } catch { $uiaPoint = $null }
  }

  # 매칭 검증 (TargetHwnd / TargetMatch 명시 시)
  $matched = $true
  $matchReason = "no_target_specified"
  if ($TargetHwnd -gt 0) {
    $matched = ([int64]$rootHwnd -eq [int64]$TargetHwnd)
    $matchReason = if ($matched) { "hwnd_match" } else { "hwnd_mismatch" }
  } elseif ($TargetMatch) {
    $needle = $TargetMatch.ToLowerInvariant()
    $matched = ($rootTitle -and $rootTitle.ToLowerInvariant().Contains($needle))
    $matchReason = if ($matched) { "title_match" } else { "title_mismatch" }
  }

  $statusStr = "ok"
  $exitCode = 0
  if ((($TargetHwnd -gt 0) -or $TargetMatch) -and -not $matched) {
    $statusStr = "partial"
    $exitCode = 2
  }

  $payload = [ordered]@{
    status = $statusStr
    x = $X; y = $Y
    child_hwnd = [int64]$childHwnd
    root_hwnd = [int64]$rootHwnd
    root_title = $rootTitle
    child_title = $childTitle
    root_class = $rootClass
    process_id = [int]$procId
    process_name = $procName
    target_hwnd = $TargetHwnd
    target_match = $TargetMatch
    matched = $matched
    match_reason = $matchReason
    uia_skipped = [bool]$SkipUia
  }
  if ($uiaPoint) {
    $payload["uia_point"] = [ordered]@{
      refined_x = [int]$uiaPoint.X
      refined_y = [int]$uiaPoint.Y
      score = [int]$uiaPoint.Score
      role = $uiaPoint.Role
      pattern = $uiaPoint.PatternName
      point_source = $uiaPoint.PointSource
      native_clickable = [bool]$uiaPoint.NativeClickable
      match = $uiaPoint.Match
    }
  }
  _Emit $payload $exitCode
}

function _Action-HitScan {
  if (-not (_Ensure-Win32Native)) { _Emit @{status="error"; reason="win32_load_failed"} 1 }
  if (-not $Script:_HasCoordinates) {
    _Emit @{status="error"; reason="missing_coords"; recommended_action="provide -X and -Y (zero and negative screen coordinates are valid)"} 1
  }
  if ($ScanRadius -lt 0) { $ScanRadius = 0 }
  if ($ScanRadius -gt 64) { $ScanRadius = 64 }
  if ($ScanStep -le 0) { $ScanStep = 6 }
  if ($ScanStep -gt 16) { $ScanStep = 16 }
  if ($ClickInset -le 0) { $ClickInset = 3 }

  $vx = [CucpNative]::GetSystemMetrics([CucpNative]::SM_XVIRTUALSCREEN)
  $vy = [CucpNative]::GetSystemMetrics([CucpNative]::SM_YVIRTUALSCREEN)
  $vw = [CucpNative]::GetSystemMetrics([CucpNative]::SM_CXVIRTUALSCREEN)
  $vh = [CucpNative]::GetSystemMetrics([CucpNative]::SM_CYVIRTUALSCREEN)
  $swScan = [System.Diagnostics.Stopwatch]::StartNew()
  $candidates = New-Object System.Collections.ArrayList
  $sampleCount = 0
  $targetMatchedSamples = 0
  $offsets = New-Object System.Collections.ArrayList
  [void]$offsets.Add(0)
  for ($o = $ScanStep; $o -le $ScanRadius; $o += $ScanStep) {
    [void]$offsets.Add(-$o)
    [void]$offsets.Add($o)
  }
  if ($ScanRadius -gt 0 -and ($ScanRadius % $ScanStep) -ne 0) {
    [void]$offsets.Add(-$ScanRadius)
    [void]$offsets.Add($ScanRadius)
  }
  $offsets = @($offsets | Sort-Object -Unique)

  foreach ($dy in $offsets) {
    foreach ($dx in $offsets) {
      $sx = $X + $dx
      $sy = $Y + $dy
      if ($sx -lt $vx -or $sx -ge ($vx + $vw) -or $sy -lt $vy -or $sy -ge ($vy + $vh)) { continue }
      $sampleCount++

      $sampleHit = _Test-CoordsInTarget -X $sx -Y $sy -ExpectedHwnd $TargetHwnd -ExpectedMatch $TargetMatch
      if (-not $sampleHit.matched) { continue }
      $targetMatchedSamples++

      $uiaPoint = $null
      try { $uiaPoint = _Resolve-UiaPointRefinement -X $sx -Y $sy -Inset $ClickInset } catch { $uiaPoint = $null }
      if (-not $uiaPoint) { continue }

      $refinedHit = _Test-CoordsInTarget -X ([int]$uiaPoint.X) -Y ([int]$uiaPoint.Y) -ExpectedHwnd $TargetHwnd -ExpectedMatch $TargetMatch
      if (-not $refinedHit.matched) { continue }

      $identifier = ""
      try { $identifier = "$($uiaPoint.Match.preferred_identifier)" } catch { $identifier = "" }
      if (-not $identifier) {
        try { $identifier = "$($uiaPoint.Match.name)|$($uiaPoint.Match.automation_id)|$($uiaPoint.Role)" } catch { $identifier = "$($uiaPoint.Role)" }
      }
      $key = "$identifier|$($uiaPoint.Role)|$($uiaPoint.PatternName)|$([int]$uiaPoint.X),$([int]$uiaPoint.Y)"
      [void]$candidates.Add([pscustomobject]@{
        key = $key
        sample_x = $sx
        sample_y = $sy
        dx = $dx
        dy = $dy
        refined_x = [int]$uiaPoint.X
        refined_y = [int]$uiaPoint.Y
        score = [int]$uiaPoint.Score
        role = "$($uiaPoint.Role)"
        pattern = "$($uiaPoint.PatternName)"
        point_source = "$($uiaPoint.PointSource)"
        native_clickable = [bool]$uiaPoint.NativeClickable
        depth = [int]$uiaPoint.Depth
        area = [int]$uiaPoint.Area
        match = $uiaPoint.Match
      })
    }
  }

  $groups = @{}
  foreach ($c in @($candidates)) {
    if (-not $groups.ContainsKey($c.key)) {
      $groups[$c.key] = [pscustomobject]@{ count = 0; max_score = 0 }
    }
    $groups[$c.key].count = [int]$groups[$c.key].count + 1
    if ([int]$c.score -gt [int]$groups[$c.key].max_score) { $groups[$c.key].max_score = [int]$c.score }
  }

  $ranked = New-Object System.Collections.ArrayList
  foreach ($c in @($candidates)) {
    $support = [int]$groups[$c.key].count
    $dist = [Math]::Sqrt(([double](($c.refined_x - $X) * ($c.refined_x - $X))) + ([double](($c.refined_y - $Y) * ($c.refined_y - $Y))))
    $distPenalty = [int][Math]::Round($dist)
    $clickBonus = 0
    if ($c.native_clickable) { $clickBonus += 12 }
    if ($c.point_source -eq "clickable_point") { $clickBonus += 8 }
    $finalScore = [int]$c.score + ($support * 7) + $clickBonus - $distPenalty
    [void]$ranked.Add([pscustomobject]@{
      sample_x = $c.sample_x
      sample_y = $c.sample_y
      dx = $c.dx
      dy = $c.dy
      refined_x = $c.refined_x
      refined_y = $c.refined_y
      final_score = $finalScore
      base_score = $c.score
      support = $support
      distance_from_origin = $dist
      role = $c.role
      pattern = $c.pattern
      point_source = $c.point_source
      native_clickable = $c.native_clickable
      depth = $c.depth
      area = $c.area
      match = $c.match
    })
  }

  $ordered = @($ranked | Sort-Object -Property final_score, support, base_score -Descending)
  $best = $null
  if ($ordered.Count -gt 0) { $best = $ordered[0] }
  $swScan.Stop()

  if (-not $best) {
    _Emit ([ordered]@{
      status = "partial"
      reason = "no_uia_candidate"
      x = $X
      y = $Y
      radius = $ScanRadius
      step = $ScanStep
      click_inset = $ClickInset
      target_hwnd = $TargetHwnd
      target_match = $TargetMatch
      sample_count = $sampleCount
      target_matched_samples = $targetMatchedSamples
      candidate_count = @($candidates).Count
      elapsed_ms = [int]$swScan.Elapsed.TotalMilliseconds
      recommended_action = "Try a slightly larger --radius, narrower --target-match, or DOM/UIA label route."
    }) 2
  }

  $top = @($ordered | Select-Object -First 12)
  _Emit ([ordered]@{
    status = "ok"
    x = $X
    y = $Y
    radius = $ScanRadius
    step = $ScanStep
    click_inset = $ClickInset
    target_hwnd = $TargetHwnd
    target_match = $TargetMatch
    sample_count = $sampleCount
    target_matched_samples = $targetMatchedSamples
    candidate_count = @($candidates).Count
    best = $best
    recommended_point = [ordered]@{
      x = [int]$best.refined_x
      y = [int]$best.refined_y
      point_source = $best.point_source
      native_clickable = [bool]$best.native_clickable
      confidence = if ($best.support -ge 4 -or $best.native_clickable) { "high" } elseif ($best.support -ge 2) { "medium" } else { "low" }
    }
    candidates = $top
    elapsed_ms = [int]$swScan.Elapsed.TotalMilliseconds
  }) 0
}

# ============================================================================
# v1.3.0: CDP Actions
# ============================================================================
$Script:_LastCdpPageSelection = $null



# CDP page 매칭 헬퍼 — title 또는 url 부분일치






# ============================================================================
# Action: cdp-detect ─ 9222 포트 + 페이지 목록
# ============================================================================
# read-only — Electron 앱이 --remote-debugging-port 옵션으로 떠있는지 확인.
# 출력: { available, port, pages[], version }
# ============================================================================


# ============================================================================
# Action: cdp-eval ─ Runtime.evaluate JavaScript 실행
# ============================================================================
# 입력: -CdpExpr "document.title" [-CdpPageMatch "Electron app"]
# 출력: { result_type, result_value, page_id, page_title }
# ============================================================================


# ============================================================================
# Action: cdp-type ─ DOM selector → focus + value set + dispatchEvent
# ============================================================================
# 입력: -CdpSelector "textarea" -Text "msg" [-CdpPageMatch "Electron app"]
#       [-PressEnter] [-ClearFirst]
# 동작:
#   1. element = document.querySelector(selector)
#   2. element.focus()
#   3. (textarea/input) element.value = text + dispatch input/change events
#      (contenteditable) element.textContent = text + dispatch input event
#   4. (옵션) Enter 키 dispatch (KeyboardEvent)
# ============================================================================


# ============================================================================
# Action: cdp-click ─ DOM selector → element.click()
# ============================================================================










# ============================================================================
# Action: click  ─ 좌표 기반 마우스 클릭 (SendInput) + v1.2.0 hit-test 가드
# ============================================================================
function _Action-Click {
  if (-not (_Ensure-Win32Native)) { _Emit @{status="error"; reason="win32_load_failed"} 1 }
  if (-not $Script:_HasCoordinates) {
    _Emit @{status="error"; reason="missing_coords"; recommended_action="provide -X and -Y (zero and negative screen coordinates are valid)"} 1
  }
  # 안전: 가상 데스크톱 범위 밖이면 차단
  $vx = [CucpNative]::GetSystemMetrics([CucpNative]::SM_XVIRTUALSCREEN)
  $vy = [CucpNative]::GetSystemMetrics([CucpNative]::SM_YVIRTUALSCREEN)
  $vw = [CucpNative]::GetSystemMetrics([CucpNative]::SM_CXVIRTUALSCREEN)
  $vh = [CucpNative]::GetSystemMetrics([CucpNative]::SM_CYVIRTUALSCREEN)
  if ($X -lt $vx -or $X -ge ($vx + $vw) -or $Y -lt $vy -or $Y -ge ($vy + $vh)) {
    _Emit @{
      status = "blocked"
      reason = "coords_out_of_virtual_desktop"
      x = $X; y = $Y
      virtual_desktop = @{ x=$vx; y=$vy; width=$vw; height=$vh }
    } 3
  }
  # v1.2.0: hit-test 가드 — TargetHwnd / TargetMatch 명시되면 좌표 검증
  if ($TargetHwnd -gt 0 -or $TargetMatch) {
    $hit = _Test-CoordsInTarget -X $X -Y $Y -ExpectedHwnd $TargetHwnd -ExpectedMatch $TargetMatch
    if (-not $hit.matched) {
      _Emit @{
        status = "blocked"
        reason = "hit_test_target_mismatch"
        x = $X; y = $Y
        actual_root_hwnd = $hit.actual_root_hwnd
        actual_title = $hit.actual_title
        target_hwnd = $TargetHwnd
        target_match = $TargetMatch
        mismatch_reason = $hit.reason
        recommended_action = "verify target window position; coords may have shifted (window moved/resized/full-screen toggle)"
      } 3
    }
  }
  $originalX = $X
  $originalY = $Y
  $refined = $null
  if ($ClickRefine -eq "uia-safe") {
    $refined = _Resolve-UiaPointRefinement -X $X -Y $Y -Inset $ClickInset
    if ($refined) {
      $X = [int]$refined.X
      $Y = [int]$refined.Y
      if ($TargetHwnd -gt 0 -or $TargetMatch) {
        $refinedHit = _Test-CoordsInTarget -X $X -Y $Y -ExpectedHwnd $TargetHwnd -ExpectedMatch $TargetMatch
        if (-not $refinedHit.matched) {
          $X = $originalX
          $Y = $originalY
          $refined = $null
        }
      }
    }
  }
  $isDouble = ($Button -eq "double")
  $btn = if ($isDouble) { "left" } else { $Button }
  [CucpNative]::SendMouseClick($X, $Y, $btn, $isDouble)
  # v1.7.0: 사후 좌표 검증 — SendInput absolute 가 OS scaling / DPI 에 의해 drift 가능
  $postX = $X
  $postY = $Y
  $postOk = $true
  $drift = 0
  try {
    $postX = [int][CucpNative]::PostClickX
    $postY = [int][CucpNative]::PostClickY
    $dx = $postX - $X
    $dy = $postY - $Y
    $drift = [int][Math]::Round([Math]::Sqrt($dx*$dx + $dy*$dy))
    # drift > 3px 면 정확도 경고 (DPI scaling / virtual desktop 경계)
    if ($drift -gt 3) { $postOk = $false }
  } catch { }
  $payload = [ordered]@{
    status = "ok"
    x = $X; y = $Y; button = $Button; double = $isDouble
    target_hwnd = $TargetHwnd
    target_match = $TargetMatch
    click_refine = $ClickRefine
    post_click = [ordered]@{
      requested_x = $X
      requested_y = $Y
      actual_x = $postX
      actual_y = $postY
      drift_px = $drift
      accurate = $postOk
    }
  }
  if ($refined) {
    $payload["original"] = [ordered]@{ x=$originalX; y=$originalY }
    $payload["refined_by"] = "uia-safe"
    $payload["refined_point_source"] = $refined.PointSource
    $payload["native_clickable_point"] = [bool]$refined.NativeClickable
    $payload["refine_score"] = [int]$refined.Score
    $payload["refine_depth"] = [int]$refined.Depth
    $payload["uia_match"] = $refined.Match
  }
  _Emit $payload
}

# ============================================================================
# Action: type  ─ 유니코드 텍스트 입력 (한글, 이모지 OK) + v1.2.0 focus 가드
# ============================================================================
function _Assert-ForegroundTarget {
  # v1.2.0: focus 가드 — TargetHwnd / TargetMatch 명시되면 현재 foreground 검증
  if ($TargetHwnd -gt 0 -or $TargetMatch) {
    $fgHwnd = [CucpNative]::GetForegroundWindow()
    $sb = New-Object System.Text.StringBuilder 256
    [void][CucpNative]::GetWindowText($fgHwnd, $sb, 256)
    $fgTitle = $sb.ToString()
    $matched = $false
    $reason = ""
    if ($TargetHwnd -gt 0) {
      $matched = ([int64]$fgHwnd -eq [int64]$TargetHwnd)
      if (-not $matched) { $reason = "hwnd_mismatch" }
    } elseif ($TargetMatch) {
      $needle = $TargetMatch.ToLowerInvariant()
      if ($fgTitle -and $fgTitle.ToLowerInvariant().Contains($needle)) { $matched = $true }
      else { $reason = "title_mismatch" }
    }
    if (-not $matched) {
      _Emit @{
        status = "blocked"
        reason = "focus_target_mismatch"
        actual_foreground_hwnd = [int64]$fgHwnd
        actual_foreground_title = $fgTitle
        target_hwnd = $TargetHwnd
        target_match = $TargetMatch
        mismatch_reason = $reason
        recommended_action = "Re-focus target window (use focus action) before typing"
      } 3
    }
  }
}

function _Action-Type {
  if (-not (_Ensure-Win32Native)) { _Emit @{status="error"; reason="win32_load_failed"} 1 }
  if (-not $Text -and -not $ClearFirst -and -not $PressEnter) {
    _Emit @{status="error"; reason="missing_text"} 1
  }
  _Assert-ForegroundTarget
  if ($ClearFirst) {
    # Ctrl+A → Backspace
    [CucpNative]::SendVk([CucpNative]::VK_CONTROL, $false)
    Start-Sleep -Milliseconds 20
    $a = [CucpNative]::VkKeyScan([char]'a') -band 0xFF
    [CucpNative]::SendVk([uint16]$a, $false)
    [CucpNative]::SendVk([uint16]$a, $true)
    [CucpNative]::SendVk([CucpNative]::VK_CONTROL, $true)
    Start-Sleep -Milliseconds 30
    [CucpNative]::SendVk([CucpNative]::VK_BACK, $false)
    [CucpNative]::SendVk([CucpNative]::VK_BACK, $true)
    Start-Sleep -Milliseconds 30
  }
  if ($Text) { [CucpNative]::SendUnicodeText($Text) }
  if ($PressEnter) {
    Start-Sleep -Milliseconds 30
    [CucpNative]::SendVk([CucpNative]::VK_RETURN, $false)
    [CucpNative]::SendVk([CucpNative]::VK_RETURN, $true)
  }
  _Emit ([ordered]@{ status="ok"; text_length=($Text.Length); clear=[bool]$ClearFirst; enter=[bool]$PressEnter })
}

# ============================================================================
# Action: shortcut  ─ "ctrl+s", "alt+f4", "win+d" 같은 조합키
# ============================================================================
function _Action-Shortcut {
  if (-not (_Ensure-Win32Native)) { _Emit @{status="error"; reason="win32_load_failed"} 1 }
  if (-not $Keys) { _Emit @{status="error"; reason="missing_keys"} 1 }

  _Assert-ForegroundTarget

  # 키 토큰 → vk 매핑. PowerShell이 직접 vk 변환을 도와줌.
  $tokens = ($Keys.ToLowerInvariant() -split '\+') | ForEach-Object { $_.Trim() }
  $vkList = @()
  foreach ($tok in $tokens) {
    $vk = switch ($tok) {
      "ctrl"   { [CucpNative]::VK_CONTROL }
      "shift"  { [CucpNative]::VK_SHIFT }
      "alt"    { [CucpNative]::VK_MENU }
      "win"    { [CucpNative]::VK_LWIN }
      "enter"  { [CucpNative]::VK_RETURN }
      "tab"    { [CucpNative]::VK_TAB }
      "esc"    { [CucpNative]::VK_ESCAPE }
      "escape" { [CucpNative]::VK_ESCAPE }
      "space"  { [CucpNative]::VK_SPACE }
      "backspace" { [CucpNative]::VK_BACK }
      "delete" { [CucpNative]::VK_DELETE }
      default {
        # F1~F24
        if ($tok -match '^f(\d{1,2})$') {
          [uint16](0x6F + [int]$matches[1])  # VK_F1=0x70, here we use 0x6F + n
        } elseif ($tok.Length -eq 1) {
          $code = [CucpNative]::VkKeyScan([char]$tok[0])
          [uint16]($code -band 0xFF)
        } else {
          $null
        }
      }
    }
    if ($null -eq $vk) { _Emit @{status="error"; reason="unknown_key"; token=$tok} 1 }
    $vkList += [uint16]$vk
  }

  # 누름 → 떼기 순서 (modifier가 먼저)
  foreach ($vk in $vkList) { [CucpNative]::SendVk($vk, $false); Start-Sleep -Milliseconds 8 }
  Start-Sleep -Milliseconds 30
  for ($i = $vkList.Count - 1; $i -ge 0; $i--) { [CucpNative]::SendVk($vkList[$i], $true); Start-Sleep -Milliseconds 8 }

  _Emit ([ordered]@{ status="ok"; keys=$Keys; tokens=$tokens })
}

# ============================================================================
# Action: uia-tree  ─ UIA 기반 affordance 목록 (BoundingRectangle 포함)
# ============================================================================
function _Action-UiaTree {
  if (-not (_Ensure-Win32Native)) { _Emit @{status="error"; reason="win32_load_failed"} 1 }
  if (-not (_Ensure-UIA)) {
    _Emit @{status="partial"; reason="uia_unavailable"; recommended_action="UIAutomationClient assembly load failed"} 2
  }

  # 대상 윈도우 결정
  $targetHwnd = [IntPtr]::Zero
  $list = [CucpNative]::EnumerateTopLevel()
  if ($Match) {
    $needle = $Match.ToLowerInvariant()
    $hit = $list | Where-Object { $_.Title -and $_.Title.ToLowerInvariant().Contains($needle) } | Select-Object -First 1
    if ($hit) { $targetHwnd = $hit.Hwnd }
  } else {
    $fg = $list | Where-Object { $_.Foreground } | Select-Object -First 1
    if ($fg) { $targetHwnd = $fg.Hwnd }
  }

  if ($targetHwnd -eq [IntPtr]::Zero) {
    _Emit @{status="partial"; reason="no_matching_window"; match=$Match} 2
  }

  $rootElement = [System.Windows.Automation.AutomationElement]::FromHandle($targetHwnd)
  if (-not $rootElement) {
    _Emit @{status="partial"; reason="uia_root_null"} 2
  }

  $items = New-Object System.Collections.ArrayList
  $count = 0
  $allElements = $rootElement.FindAll(
    [System.Windows.Automation.TreeScope]::Descendants,
    [System.Windows.Automation.Condition]::TrueCondition
  )
  foreach ($el in $allElements) {
    if ($count -ge $MaxElements) { break }
    try {
      $cur = $el.Current
      $r = $cur.BoundingRectangle
      if ($r.IsEmpty -or $r.Width -lt $MinSize -or $r.Height -lt $MinSize) { continue }
      $name = ""; try { $name = "$($cur.Name)" } catch { }
      $autoId = ""; try { $autoId = "$($cur.AutomationId)" } catch { }
      $help = ""; try { $help = "$($cur.HelpText)" } catch { }
      $accessKey = ""; try { $accessKey = "$($cur.AccessKey)" } catch { }
      $clazz = ""; try { $clazz = "$($cur.ClassName)" } catch { }
      $localizedRole = ""; try { $localizedRole = $cur.LocalizedControlType } catch { }
      $isOffscreen = $false; try { $isOffscreen = [bool]$cur.IsOffscreen } catch { }
      $isEnabled = $true; try { $isEnabled = [bool]$cur.IsEnabled } catch { }
      if ($isOffscreen) { continue }

      $text = if (-not [string]::IsNullOrWhiteSpace($name)) { $name }
              elseif (-not [string]::IsNullOrWhiteSpace($autoId)) { $autoId }
              elseif (-not [string]::IsNullOrWhiteSpace($help)) { $help }
              else { $null }
      if (-not $text) { continue }

      [void]$items.Add([ordered]@{
        text = $text
        name = $name
        automation_id = $autoId
        help_text = $help
        access_key = $accessKey
        class_name = $clazz
        role = $localizedRole
        enabled = $isEnabled
        rect = [ordered]@{ x=[int]$r.X; y=[int]$r.Y; width=[int]$r.Width; height=[int]$r.Height }
        center = [ordered]@{ x=[int]($r.X + $r.Width / 2); y=[int]($r.Y + $r.Height / 2) }
      })
      $count++
    } catch { continue }
  }

  _Emit ([ordered]@{
    status = "ok"
    target_hwnd = [int64]$targetHwnd
    affordance_count = $items.Count
    affordances = @($items)
  })
}

# ============================================================================
# Action: uia-find  ─ 라벨 기반 element 검색
# ============================================================================
function _Action-UiaFind {
  if (-not $Label) { _Emit @{status="error"; reason="missing_label"} 1 }
  # 직접 _Resolve-UiaElement 호출 (이전엔 uia-tree를 SetOut 리다이렉트로
  # 캡처했지만, 그 방식은 _Emit의 exit 호출 시 stdout이 사라지는 race가 있어
  # 빈 출력으로 떨어지는 문제가 있었습니다. 이제 동일한 in-process resolver를
  # 직접 호출해서 안정적으로 결과를 emit합니다.
  if (-not (_Ensure-Win32Native)) { _Emit @{status="error"; reason="win32_load_failed"} 1 }
  if (-not (_Ensure-UIA)) {
    _Emit @{status="partial"; reason="uia_unavailable"} 2
  }

  # 대상 윈도우 결정
  $list = [CucpNative]::EnumerateTopLevel()
  $targetHwnd = [IntPtr]::Zero
  if ($Match) {
    $needleW = $Match.ToLowerInvariant()
    $hit = $list | Where-Object { $_.Title -and $_.Title.ToLowerInvariant().Contains($needleW) } | Select-Object -First 1
    if ($hit) { $targetHwnd = $hit.Hwnd }
  } else {
    $fg = $list | Where-Object { $_.Foreground } | Select-Object -First 1
    if ($fg) { $targetHwnd = $fg.Hwnd }
  }
  if ($targetHwnd -eq [IntPtr]::Zero) {
    _Emit @{status="partial"; reason="no_matching_window"; match=$Match} 2
  }
  $rootEl = [System.Windows.Automation.AutomationElement]::FromHandle($targetHwnd)
  if (-not $rootEl) { _Emit @{status="partial"; reason="uia_root_null"} 2 }

  $needle = $Label.Trim().ToLowerInvariant()
  $needleNorm = ($needle -replace '\s+', ' ').Trim()
  $allElements = $rootEl.FindAll(
    [System.Windows.Automation.TreeScope]::Descendants,
    [System.Windows.Automation.Condition]::TrueCondition
  )

  $candidates = New-Object System.Collections.ArrayList
  $count = 0
  foreach ($el in $allElements) {
    if ($count -ge $MaxElements) { break }
    try {
      $cur = $el.Current
      $r = $cur.BoundingRectangle
      if ($r.IsEmpty -or $r.Width -lt $MinSize -or $r.Height -lt $MinSize) { continue }
      if ($cur.IsOffscreen) { continue }
      $name = ""; try { $name = "$($cur.Name)" } catch { }
      $autoId = ""; try { $autoId = "$($cur.AutomationId)" } catch { }
      $help = ""; try { $help = "$($cur.HelpText)" } catch { }
      $accessKey = ""; try { $accessKey = "$($cur.AccessKey)" } catch { }
      $localizedRole = ""; try { $localizedRole = $cur.LocalizedControlType } catch { }
      if ($Role -and $localizedRole -and ($localizedRole.ToLowerInvariant() -ne $Role.ToLowerInvariant())) { continue }

      $hays = @($name, $autoId, $help, $accessKey) | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } |
              ForEach-Object { ($_.ToLowerInvariant() -replace '\s+', ' ').Trim() }
      if ($hays.Count -eq 0) { continue }
      $score = 0
      $reason = ""
      foreach ($hay in $hays) {
        $local = 0
        if ($hay -eq $needleNorm) { $local = 100 }
        elseif ($hay -match [regex]::Escape($needleNorm)) {
          $diff = [Math]::Abs($hay.Length - $needleNorm.Length)
          $local = 60 + [Math]::Max(0, 40 - $diff)
        } elseif ($needleNorm.Length -ge 2 -and $hay.IndexOf($needleNorm.Substring(0, [Math]::Min(2, $needleNorm.Length))) -ge 0) {
          $local = 15
        }
        if ($local -gt $score) {
          $score = $local
          $reason = if ($local -ge 100) { "exact" } elseif ($local -ge 60) { "substring" } else { "prefix" }
        }
      }
      if ($score -le 0) { continue }
      $pattern = $null
      try { $pattern = _Get-UiaSupportedPatternName -Element $el } catch { $pattern = $null }
      $valuePattern = $false
      $valueReadonly = $null
      try {
        $vp = $el.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern)
        if ($vp) {
          $valuePattern = $true
          $valueReadonly = [bool]$vp.Current.IsReadOnly
        }
      } catch { }
      $point = $null
      try { $point = _Get-UiaPreferredClickPoint -Element $el -Rect $r -Inset $ClickInset } catch { $point = $null }
      [void]$candidates.Add([ordered]@{
        text = if ($name) { $name } elseif ($autoId) { $autoId } else { $help }
        role = $localizedRole
        rect = [ordered]@{ x=[int]$r.X; y=[int]$r.Y; width=[int]$r.Width; height=[int]$r.Height }
        center = [ordered]@{ x=[int]($r.X + $r.Width / 2); y=[int]($r.Y + $r.Height / 2) }
        click_point = if ($point) { [ordered]@{ x=[int]$point.X; y=[int]$point.Y; source=$point.Source; native_clickable=[bool]$point.NativeClickable } } else { $null }
        score = $score
        match_reason = $reason
        automation_id = $autoId
        invoke_pattern = $pattern
        value_pattern = $valuePattern
        value_readonly = $valueReadonly
      })
      $count++
    } catch { continue }
  }
  $ranked = @($candidates | Sort-Object -Property { $_.score } -Descending)
  if ($ranked.Count -eq 0) { _Emit @{status="partial"; reason="no_match"; label=$Label} 2 }
  $top = $ranked[0]
  $second = if ($ranked.Count -gt 1) { $ranked[1] } else { $null }
  $ambiguous = ($second -and (($top.score - $second.score) -lt 8))
  $statusStr = "ok"; $exitCode = 0
  if ($ambiguous) { $statusStr = "partial"; $exitCode = 2 }
  _Emit ([ordered]@{
    status = $statusStr
    label = $Label
    top = $top
    candidates = ($ranked | Select-Object -First 5)
    ambiguous = $ambiguous
  }) $exitCode
}

# ============================================================================
# Action: uia-click  ─ uia-find로 좌표 결정 후 click 실행
# ============================================================================
function _Action-UiaClick {
  if (-not $Label) { _Emit @{status="error"; reason="missing_label"} 1 }
  if (-not (_Ensure-Win32Native)) { _Emit @{status="error"; reason="win32_load_failed"} 1 }
  $resolved = _Resolve-UiaElement -Match $Match -Label $Label -Role $Role -MaxElements $MaxElements -MinSize $MinSize
  if (-not $resolved) { _Emit @{status="partial"; reason="no_match"; label=$Label} 2 }
  $cur = $resolved.Element.Current
  $r = $cur.BoundingRectangle
  $cx = [int]($r.X + $r.Width / 2)
  $cy = [int]($r.Y + $r.Height / 2)
  $isDouble = ($Button -eq "double")
  $btn = if ($isDouble) { "left" } else { $Button }
  [CucpNative]::SendMouseClick($cx, $cy, $btn, $isDouble)
  _Emit ([ordered]@{
    status = "ok"
    label = $Label
    x = $cx; y = $cy
    button = $Button
    matched_text = $cur.Name
    rect = [ordered]@{ x=[int]$r.X; y=[int]$r.Y; width=[int]$r.Width; height=[int]$r.Height }
    score = $resolved.Score
    match_reason = $resolved.Reason
  })
}

# ============================================================================
# UIA Pattern 직접 호출 헬퍼 — _ResolveElement (uia-find의 in-process 버전)
# ============================================================================
# uia-invoke / uia-set-value / uia-toggle은 element를 찾아 BoundingRectangle이
# 아니라 InvokePattern.Invoke() 같은 UIA 명령을 직접 호출합니다.
# 마우스가 움직이지 않고, 화면이 가려져 있어도 동작합니다.
#
# 반환:
#   [pscustomobject] @{ Element, Cur, Found, Reason, Score }
function _Resolve-UiaElement {
  param([string]$Match, [string]$Label, [string]$Role, [int]$MaxElements = 400, [int]$MinSize = 6)
  if (-not (_Ensure-Win32Native)) { return $null }
  if (-not (_Ensure-UIA)) { return $null }

  $list = [CucpNative]::EnumerateTopLevel()
  $targetHwnd = [IntPtr]::Zero
  if ($Match) {
    $needle = $Match.ToLowerInvariant()
    $hit = $list | Where-Object { $_.Title -and $_.Title.ToLowerInvariant().Contains($needle) } | Select-Object -First 1
    if ($hit) { $targetHwnd = $hit.Hwnd }
  } else {
    $fg = $list | Where-Object { $_.Foreground } | Select-Object -First 1
    if ($fg) { $targetHwnd = $fg.Hwnd }
  }
  if ($targetHwnd -eq [IntPtr]::Zero) { return $null }

  $rootEl = [System.Windows.Automation.AutomationElement]::FromHandle($targetHwnd)
  if (-not $rootEl) { return $null }

  $needleLabel = $Label.Trim().ToLowerInvariant()
  $needleNorm = ($needleLabel -replace '\s+', ' ').Trim()

  $candidates = $rootEl.FindAll(
    [System.Windows.Automation.TreeScope]::Descendants,
    [System.Windows.Automation.Condition]::TrueCondition
  )

  $bestEl = $null
  $bestScore = 0
  $bestReason = ""
  $count = 0
  foreach ($el in $candidates) {
    if ($count -ge $MaxElements) { break }
    try {
      $cur = $el.Current
      $r = $cur.BoundingRectangle
      if ($r.IsEmpty -or $r.Width -lt $MinSize -or $r.Height -lt $MinSize) { continue }
      if ($cur.IsOffscreen) { continue }

      $name = ""; try { $name = "$($cur.Name)" } catch { }
      $autoId = ""; try { $autoId = "$($cur.AutomationId)" } catch { }
      $help = ""; try { $help = "$($cur.HelpText)" } catch { }
      $accessKey = ""; try { $accessKey = "$($cur.AccessKey)" } catch { }
      $localizedRole = ""; try { $localizedRole = $cur.LocalizedControlType } catch { }

      if ($Role -and $localizedRole -and ($localizedRole.ToLowerInvariant() -ne $Role.ToLowerInvariant())) { continue }

      $hays = @($name, $autoId, $help, $accessKey) | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
      if ($hays.Count -eq 0) { continue }

      $score = 0
      $reason = ""
      foreach ($h in $hays) {
        $hl = ($h.ToLowerInvariant() -replace '\s+', ' ').Trim()
        $local = 0
        if ($hl -eq $needleNorm) { $local = 100 }
        elseif ($hl -match [regex]::Escape($needleNorm)) {
          $diff = [Math]::Abs($hl.Length - $needleNorm.Length)
          $local = 60 + [Math]::Max(0, 40 - $diff)
        } elseif ($needleNorm.Length -ge 2 -and $hl.IndexOf($needleNorm.Substring(0, [Math]::Min(2, $needleNorm.Length))) -ge 0) {
          $local = 15
        }
        if ($local -gt $score) {
          $score = $local
          $reason = if ($local -ge 100) { "exact" } elseif ($local -ge 60) { "substring" } else { "prefix" }
        }
      }
      if ($score -gt $bestScore) {
        $bestEl = $el
        $bestScore = $score
        $bestReason = $reason
      }
      $count++
    } catch { continue }
  }

  if (-not $bestEl) { return $null }
  return [pscustomobject]@{
    Element = $bestEl
    Score = $bestScore
    Reason = $bestReason
  }
}

# ============================================================================
# Action: uia-invoke ─ InvokePattern 직접 호출 (마우스 안 움직임)
# ============================================================================
# 가장 안정적인 클릭 방법. 다음 컨트롤에서 사용 가능:
#   - Button (대부분 단추)
#   - MenuItem (메뉴 항목)
#   - Hyperlink (하이퍼링크)
#   - 일부 ListItem
# Toggle 가능한 체크박스/라디오버튼은 uia-toggle을 사용해야 함.
# Edit 컨트롤에 값 넣을 때는 uia-set-value 사용.
#
# 안전 정책:
#   - score < 60 (substring 미만) 면 fallback도 거부 — 잘못된 element 클릭 방지.
#   - 좌표 fallback은 명시 옵션이 있을 때만. 기본은 Pattern만 시도.
# ============================================================================
function _Action-UiaInvoke {
  if (-not $Label) { _Emit @{status="error"; reason="missing_label"} 1 }
  $resolved = _Resolve-UiaElement -Match $Match -Label $Label -Role $Role -MaxElements $MaxElements -MinSize $MinSize
  if (-not $resolved) {
    _Emit @{status="partial"; reason="no_match"; label=$Label} 2
  }
  # 안전 가드: 매칭 신뢰도가 낮으면 클릭 자체를 거부
  if ($resolved.Score -lt 60) {
    _Emit ([ordered]@{
      status = "partial"
      reason = "low_confidence_match"
      label = $Label
      score = $resolved.Score
      match_reason = $resolved.Reason
      matched_text = $resolved.Element.Current.Name
      recommended_action = "라벨 정확도 낮음(score<60). 다른 라벨/role/match로 시도하거나 macro find-label --explain 으로 후보 확인."
    }) 2
  }
  $el = $resolved.Element
  $cur = $el.Current
  # 1) InvokePattern 시도 (가장 일반적)
  try {
    $pat = $el.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern)
    if ($pat) {
      $pat.Invoke()
      $r = $cur.BoundingRectangle
      _Emit ([ordered]@{
        status = "ok"
        method = "InvokePattern"
        label = $Label
        matched_text = $cur.Name
        automation_id = $cur.AutomationId
        rect = [ordered]@{ x=[int]$r.X; y=[int]$r.Y; width=[int]$r.Width; height=[int]$r.Height }
        score = $resolved.Score
        match_reason = $resolved.Reason
        mouse_moved = $false
      })
    }
  } catch { }

  # 2) Fallback: SelectionItemPattern (탭/리스트 항목)
  try {
    $sel = $el.GetCurrentPattern([System.Windows.Automation.SelectionItemPattern]::Pattern)
    if ($sel) {
      $sel.Select()
      _Emit ([ordered]@{
        status = "ok"
        method = "SelectionItemPattern"
        label = $Label
        matched_text = $cur.Name
        score = $resolved.Score
        mouse_moved = $false
      })
    }
  } catch { }

  # 3) Fallback: ExpandCollapsePattern (서브메뉴 등)
  try {
    $exp = $el.GetCurrentPattern([System.Windows.Automation.ExpandCollapsePattern]::Pattern)
    if ($exp) {
      $exp.Expand()
      _Emit ([ordered]@{
        status = "ok"
        method = "ExpandCollapsePattern"
        label = $Label
        matched_text = $cur.Name
        score = $resolved.Score
        mouse_moved = $false
      })
    }
  } catch { }

  # 4) UIA pattern 없음 — partial 반환 (마우스 fallback은 명시 호출자가 click-point 사용)
  $r = $cur.BoundingRectangle
  _Emit ([ordered]@{
    status = "partial"
    reason = "no_invoke_pattern"
    label = $Label
    matched_text = $cur.Name
    rect = [ordered]@{ x=[int]$r.X; y=[int]$r.Y; width=[int]$r.Width; height=[int]$r.Height }
    score = $resolved.Score
    recommended_action = "UIA pattern 미지원 element. 좌표 클릭이 필요하면 macro click-point --x N --y N 호출."
  }) 2
}

# ============================================================================
# Action: uia-set-value ─ ValuePattern.SetValue 직접 호출
# ============================================================================
# Edit/ComboBox에 값을 넣을 때 키보드 입력 시뮬레이션 없이 즉시 설정.
# 한글/이모지/긴 텍스트도 한 번에 들어가고 IME 안 거침.
# ============================================================================
function _Action-UiaSetValue {
  if (-not $Label) { _Emit @{status="error"; reason="missing_label"} 1 }
  if ($null -eq $Value) { _Emit @{status="error"; reason="missing_value"} 1 }
  $resolved = _Resolve-UiaElement -Match $Match -Label $Label -Role $Role -MaxElements $MaxElements -MinSize $MinSize
  if (-not $resolved) {
    _Emit @{status="partial"; reason="no_match"; label=$Label} 2
  }
  $el = $resolved.Element
  $cur = $el.Current
  try {
    $pat = $el.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern)
    if ($pat) {
      if ($pat.Current.IsReadOnly) {
        _Emit @{status="partial"; reason="value_readonly"; label=$Label} 2
      }
      $pat.SetValue($Value)
      _Emit ([ordered]@{
        status = "ok"
        method = "ValuePattern.SetValue"
        label = $Label
        matched_text = $cur.Name
        value_length = $Value.Length
        keyboard_used = $false
      })
    }
  } catch { }
  _Emit @{status="partial"; reason="no_value_pattern"; label=$Label; recommended_action="Try macro type-native after focusing the field"} 2
}

# ============================================================================
# Action: uia-toggle ─ TogglePattern.Toggle (체크박스/라디오버튼)
# ============================================================================
function _Action-UiaToggle {
  if (-not $Label) { _Emit @{status="error"; reason="missing_label"} 1 }
  $resolved = _Resolve-UiaElement -Match $Match -Label $Label -Role $Role -MaxElements $MaxElements -MinSize $MinSize
  if (-not $resolved) { _Emit @{status="partial"; reason="no_match"; label=$Label} 2 }
  $el = $resolved.Element
  $cur = $el.Current
  try {
    $pat = $el.GetCurrentPattern([System.Windows.Automation.TogglePattern]::Pattern)
    if ($pat) {
      $beforeState = "$($pat.Current.ToggleState)"
      $pat.Toggle()
      _Emit ([ordered]@{
        status = "ok"
        method = "TogglePattern"
        label = $Label
        matched_text = $cur.Name
        previous_state = $beforeState
        mouse_moved = $false
      })
    }
  } catch { }
  _Emit @{status="partial"; reason="no_toggle_pattern"; label=$Label} 2
}

# ============================================================================
# Action: ocr-image  ─ 임의 PNG 파일을 OCR (브라우저 캔버스 캡처 / 외부 이미지)
# ============================================================================
# 입력: -OcrPath <png>
# 출력: 인식된 라인/단어 + BoundingRectangle. 좌표는 이미지 픽셀 기준.
# 주의: ocr-image는 절대 화면 좌표가 아닌 이미지 내부 좌표를 반환합니다.
# 화면 클릭 좌표가 필요하면 ocr-screen 또는 ocr-find-text를 쓰세요.
# ============================================================================
function _Action-OcrImage {
  _Require-LegacyImages
  $result = [PcuCp.LegacyImages.FileOcr]::ValidatePath($OcrPath)
  if ($null -ne $result) { _Emit $result.Data $result.ExitCode }
  if (-not (_Ensure-OCR)) {
    $result = [PcuCp.LegacyImages.FileOcr]::Unavailable($Script:_OCRError)
    _Emit $result.Data $result.ExitCode
  }
  $result = [PcuCp.LegacyImages.FileOcr]::RecognizeFile($OcrPath, $Script:_OCREngine)
  _Emit $result.Data $result.ExitCode
}

# ============================================================================
# Action: ocr-screen  ─ 화면 캡처 + OCR (UIA가 못 보는 표면용)
# ============================================================================
# 입력: -ScreenshotX/Y/W/H (생략 시 가상 데스크톱 전체)
# 출력: 인식된 라인/단어 + BoundingRectangle. 좌표는 절대 화면 좌표.
# ocr-screen은 임시 PNG를 만든 뒤 OCR하고 PNG는 자동 삭제합니다.
# ============================================================================
function _Action-OcrScreen {
  if (-not (_Ensure-Win32Native)) { _Emit @{status="error"; reason="win32_load_failed"} 1 }
  if (-not (_Ensure-OCR)) {
    _Emit @{status="error"; reason="ocr_unavailable"; ocr_error=$Script:_OCRError; recommended_action="install_windows_ocr_language_pack"} 1
  }
  Add-Type -AssemblyName System.Drawing -ErrorAction Stop

  # 영역 결정 (screenshot action과 동일 규칙)
  $vx = [CucpNative]::GetSystemMetrics([CucpNative]::SM_XVIRTUALSCREEN)
  $vy = [CucpNative]::GetSystemMetrics([CucpNative]::SM_YVIRTUALSCREEN)
  $vw = [CucpNative]::GetSystemMetrics([CucpNative]::SM_CXVIRTUALSCREEN)
  $vh = [CucpNative]::GetSystemMetrics([CucpNative]::SM_CYVIRTUALSCREEN)
  $sx = if ($ScreenshotX -ge 0) { $ScreenshotX } else { $vx }
  $sy = if ($ScreenshotY -ge 0) { $ScreenshotY } else { $vy }
  $sw = if ($ScreenshotW -gt 0) { $ScreenshotW } else { $vw }
  $sh = if ($ScreenshotH -gt 0) { $ScreenshotH } else { $vh }

  # OcrEngine MaxImageDimension 한도 검사 (보통 10000)
  $maxDim = [Windows.Media.Ocr.OcrEngine]::MaxImageDimension
  if ($sw -gt $maxDim -or $sh -gt $maxDim) {
    _Emit @{
      status="error"
      reason="region_exceeds_max_image_dimension"
      max_dim=$maxDim
      width=$sw; height=$sh
      recommended_action="provide_smaller_region_via_ScreenshotW_ScreenshotH"
    } 1
  }

  $tmp = [System.IO.Path]::Combine([System.IO.Path]::GetTempPath(), "cucp-ocr-screen-$([System.Guid]::NewGuid().ToString('N')).png")
  try {
    $bmp = New-Object System.Drawing.Bitmap $sw, $sh
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    try {
      $g.CopyFromScreen($sx, $sy, 0, 0, (New-Object System.Drawing.Size $sw, $sh))
    } finally { $g.Dispose() }
    $bmp.Save($tmp, [System.Drawing.Imaging.ImageFormat]::Png)
    $bmp.Dispose()

    $sb = _Load-SoftwareBitmapFromFile -Path $tmp
    $ocrResult = _Wait-AsyncOp ($Script:_OCREngine.RecognizeAsync($sb)) ([Windows.Media.Ocr.OcrResult])
    # 화면 절대 좌표로 환산
    $payload = _Convert-OcrResult -OcrResult $ocrResult -OffsetX $sx -OffsetY $sy
    $payload["status"] = "ok"
    $payload["engine_language"] = $Script:_OCREngine.RecognizerLanguage.LanguageTag
    $payload["source"] = "screen"
    $payload["region"] = [ordered]@{ x=$sx; y=$sy; width=$sw; height=$sh }
    _Emit $payload
  } catch {
    _Emit @{status="error"; reason="ocr_screen_failed"; detail=$_.Exception.Message} 1
  } finally {
    if (Test-Path -LiteralPath $tmp) {
      Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue
    }
  }
}

# ============================================================================
# Action: ocr-find-text  ─ 화면/이미지에서 특정 텍스트 위치 찾기
# ============================================================================
# 입력: -OcrText "검색어" [-OcrMatch contains|exact|prefix] [-OcrPath png]
#       [-ScreenshotX/Y/W/H] [-OcrMaxCandidates N]
# 출력: 매칭된 후보들 (점수 내림차순), 각 후보는 line + word 단위
# UIA가 안 잡는 브라우저 캔버스/이미지 표면에서 클릭 좌표를 결정할 때 사용.
# ============================================================================
function _Action-OcrFindText {
  if (-not $OcrText) {
    _Emit @{status="error"; reason="missing_ocr_text"; recommended_action="provide -OcrText <search string>"} 1
  }
  # 입력 소스: -OcrPath 우선, 없으면 화면 캡처
  if ($OcrPath) {
    if (-not (Test-Path -LiteralPath $OcrPath)) {
      _Emit @{status="error"; reason="ocr_path_not_found"; ocr_path=$OcrPath} 1
    }
    if (-not (_Ensure-OCR)) {
      _Emit @{status="error"; reason="ocr_unavailable"; ocr_error=$Script:_OCRError} 1
    }
    try {
      $sb = _Load-SoftwareBitmapFromFile -Path $OcrPath
      $ocrResult = _Wait-AsyncOp ($Script:_OCREngine.RecognizeAsync($sb)) ([Windows.Media.Ocr.OcrResult])
      $body = _Convert-OcrResult -OcrResult $ocrResult
      $sourceMeta = [ordered]@{ source="image"; ocr_path=$OcrPath }
    } catch {
      _Emit @{status="error"; reason="ocr_failed"; detail=$_.Exception.Message} 1
    }
  } else {
    # 화면 캡처 + OCR 경로 — ocr-screen과 동일 로직 재사용
    if (-not (_Ensure-Win32Native)) { _Emit @{status="error"; reason="win32_load_failed"} 1 }
    if (-not (_Ensure-OCR)) {
      _Emit @{status="error"; reason="ocr_unavailable"; ocr_error=$Script:_OCRError} 1
    }
    $capX = $ScreenshotX; $capY = $ScreenshotY; $capW = $ScreenshotW; $capH = $ScreenshotH
    if ($Match -and $ScreenshotX -lt 0 -and $ScreenshotY -lt 0 -and $ScreenshotW -le 0 -and $ScreenshotH -le 0) {
      $needle = $Match.ToLowerInvariant()
      $targetWin = [CucpNative]::EnumerateTopLevel() |
        Where-Object { $_.Title -and $_.Title.ToLowerInvariant().Contains($needle) } |
        Select-Object -First 1
      if ($targetWin) {
        $capX = [int]$targetWin.X
        $capY = [int]$targetWin.Y
        $capW = [int]$targetWin.Width
        $capH = [int]$targetWin.Height
      }
    }
    $cap = _Capture-ScreenRegionToTempPng -RegionX $capX -RegionY $capY `
                                          -RegionW $capW -RegionH $capH `
                                          -Prefix "cucp-ocr-find"
    if ($cap.Error) {
      $exitCode = 1
      $statusText = "error"
      if ($cap.Error -eq "screenshot_unavailable") {
        $exitCode = 2
        $statusText = "partial"
      }
      _Emit @{
        status=$statusText
        reason=$cap.Error
        detail=$cap.Detail
        max_dim=$cap.MaxDim
        recommended_action="Retry from an interactive unlocked desktop session, provide -OcrPath, or use a smaller visible region."
      } $exitCode
    }
    $sx = $cap.X; $sy = $cap.Y; $sw = $cap.W; $sh = $cap.H
    $tmp = $cap.Path
    try {
      $sb = _Load-SoftwareBitmapFromFile -Path $tmp
      $ocrResult = _Wait-AsyncOp ($Script:_OCREngine.RecognizeAsync($sb)) ([Windows.Media.Ocr.OcrResult])
      $body = _Convert-OcrResult -OcrResult $ocrResult -OffsetX $sx -OffsetY $sy
      $sourceMeta = [ordered]@{
        source="screen"
        region = [ordered]@{ x=$sx; y=$sy; width=$sw; height=$sh }
      }
    } catch {
      _Emit @{status="error"; reason="ocr_screen_failed"; detail=$_.Exception.Message} 1
    } finally {
      if (Test-Path -LiteralPath $tmp) { Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue }
    }
  }

  $sorted = @(_Match-OcrCandidates -Body $body -Needle $OcrText -Mode $OcrMatch | Select-Object -First $OcrMaxCandidates)

  if (-not $sorted -or @($sorted).Count -eq 0) {
    $payload = [ordered]@{
      status = "partial"
      reason = "no_text_match"
      ocr_text = $OcrText
      ocr_match = $OcrMatch
      engine_language = $Script:_OCREngine.RecognizerLanguage.LanguageTag
      total_lines = $body.line_count
      total_words = $body.word_count
    }
    foreach ($k in $sourceMeta.Keys) { $payload[$k] = $sourceMeta[$k] }
    _Emit $payload 2
  }

  $payload = [ordered]@{
    status = "ok"
    ocr_text = $OcrText
    ocr_match = $OcrMatch
    engine_language = $Script:_OCREngine.RecognizerLanguage.LanguageTag
    candidate_count = @($sorted).Count
    candidates = @($sorted)
    top = $sorted[0]
  }
  foreach ($k in $sourceMeta.Keys) { $payload[$k] = $sourceMeta[$k] }
  _Emit $payload
}

# ============================================================================
# Action: ocr-uia-fuse  ─ OCR 좌표 위에 UIA element 가 있으면 invoke 가능 보고
# ============================================================================
# 사용 사례:
#   OCR 이 "Send" 텍스트 좌표를 잡았는데 그 위에 UIA Button element 가 있으면
#   좌표 클릭 대신 InvokePattern.Invoke() 로 호출 가능 → 마우스 안 움직임.
#
# Electron / 일부 WPF 같이 "UIA에는 element 가 있지만 Name 이 비어있어서
# uia-find 로는 못 찾는" 표면을 OCR 텍스트로 식별 + UIA 좌표 매칭으로 invoke.
#
# 입력: -OcrText "<찾을 텍스트>" [-OcrMatch contains|exact|prefix]
#       [-Match <window 부분 매칭>] [-Region x,y,w,h via -ScreenshotX/Y/W/H]
#       [-OcrLanguage ko]
# 출력: { ocr_top, uia_match, can_invoke, invoke_pattern, recommendation }
#   - ocr_top: OCR 1순위 후보 (text + cx/cy + score + rect)
#   - uia_match: OCR rect 중심점이 들어있는 UIA element (없을 수 있음)
#   - can_invoke: UIA element 가 Invoke/Toggle/SelectionItem 패턴 지원하면 true
#   - invoke_pattern: "InvokePattern" / "TogglePattern" / "SelectionItemPattern"
#   - recommendation: "uia_invoke" / "ocr_click" / "low_confidence_skip"
#
# read-only — 실제 클릭/호출은 안 함. wrapper 의 smart-click 이 해석.
# ============================================================================
function _Action-OcrUiaFuse {
  if (-not $OcrText) {
    _Emit @{status="error"; reason="missing_ocr_text"} 1
  }
  if (-not (_Ensure-Win32Native)) { _Emit @{status="error"; reason="win32_load_failed"} 1 }
  if (-not (_Ensure-UIA)) {
    _Emit @{status="error"; reason="uia_unavailable"} 1
  }
  if (-not (_Ensure-OCR)) {
    _Emit @{status="error"; reason="ocr_unavailable"; ocr_error=$Script:_OCRError} 1
  }

  $list = [CucpNative]::EnumerateTopLevel()
  $targetHwnd = [IntPtr]::Zero
  $targetWin = $null
  if ($Match) {
    $needle = $Match.ToLowerInvariant()
    $targetWin = $list | Where-Object { $_.Title -and $_.Title.ToLowerInvariant().Contains($needle) } | Select-Object -First 1
  }
  if (-not $targetWin) {
    $targetWin = $list | Where-Object { $_.Foreground } | Select-Object -First 1
  }
  if ($targetWin) { $targetHwnd = $targetWin.Hwnd }
  if ($targetHwnd -eq [IntPtr]::Zero) {
    _Emit @{status="partial"; reason="no_target_window"} 2
  }

  $capX = $ScreenshotX; $capY = $ScreenshotY; $capW = $ScreenshotW; $capH = $ScreenshotH
  if ($targetWin -and $ScreenshotX -lt 0 -and $ScreenshotY -lt 0 -and $ScreenshotW -le 0 -and $ScreenshotH -le 0) {
    $capX = [int]$targetWin.X
    $capY = [int]$targetWin.Y
    $capW = [int]$targetWin.Width
    $capH = [int]$targetWin.Height
  }

  # 1) 화면 캡처 + OCR (v1.0.0 헬퍼로 추출)
  $cap = _Capture-ScreenRegionToTempPng -RegionX $capX -RegionY $capY `
                                          -RegionW $capW -RegionH $capH `
                                          -Prefix "cucp-fuse"
  if ($cap.Error) {
    $exitCode = 1
    $statusText = "error"
    if ($cap.Error -eq "screenshot_unavailable") {
      $exitCode = 2
      $statusText = "partial"
    }
    _Emit @{
      status=$statusText
      reason=$cap.Error
      detail=$cap.Detail
      max_dim=$cap.MaxDim
      recommended_action="Retry from an interactive unlocked desktop session, provide a matching foreground window, or use a smaller visible region."
    } $exitCode
  }
  $sx = $cap.X; $sy = $cap.Y; $sw = $cap.W; $sh = $cap.H
  $tmp = $cap.Path
  $ocrTop = $null
  $ocrCandidates = @()
  try {
    $sb = _Load-SoftwareBitmapFromFile -Path $tmp
    $ocrResult = _Wait-AsyncOp ($Script:_OCREngine.RecognizeAsync($sb)) ([Windows.Media.Ocr.OcrResult])
    $body = _Convert-OcrResult -OcrResult $ocrResult -OffsetX $sx -OffsetY $sy
    $ocrCandidates = @(_Match-OcrCandidates -Body $body -Needle $OcrText -Mode $OcrMatch | Select-Object -First $OcrMaxCandidates)
    if ($ocrCandidates.Count -gt 0) { $ocrTop = $ocrCandidates[0] }
  } finally {
    if (Test-Path -LiteralPath $tmp) { Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue }
  }

  if (-not $ocrTop) {
    _Emit @{
      status="partial"
      reason="no_ocr_match"
      ocr_text=$OcrText
      ocr_match=$OcrMatch
      recommendation="low_confidence_skip"
    } 2
  }

  $uiaMatch = $null
  $canInvoke = $false
  $invokePattern = $null
  $fusion = $null
  if ($targetHwnd -ne [IntPtr]::Zero) {
    try {
      $rootEl = [System.Windows.Automation.AutomationElement]::FromHandle($targetHwnd)
      if ($rootEl) {
        $allEls = $rootEl.FindAll(
          [System.Windows.Automation.TreeScope]::Descendants,
          [System.Windows.Automation.Condition]::TrueCondition
        )
        $fusion = _Resolve-OcrUiaFusionCandidate -RootEl $rootEl -Elements $allEls -OcrCandidates $ocrCandidates -Limit $OcrMaxCandidates
        if ($fusion) {
          $ocrTop = $fusion.Ocr
          $uiaMatch = $fusion.UiaMatch
          $canInvoke = [bool]$fusion.CanInvoke
          $invokePattern = $fusion.PatternName
        }
      }
    } catch { }
  }

  # 3) 추천 결정
  $recommendation = "ocr_click"  # default — UIA element 못 찾음
  if ([int]$ocrTop.score -lt 70) { $recommendation = "low_confidence_skip" }
  elseif ($canInvoke) { $recommendation = "uia_invoke" }

  _Emit ([ordered]@{
    status = "ok"
    ocr_text = $OcrText
    ocr_match = $OcrMatch
    target_hwnd = [int64]$targetHwnd
    ocr_top = $ocrTop
    uia_match = $uiaMatch
    can_invoke = $canInvoke
    invoke_pattern = $invokePattern
    recommendation = $recommendation
    candidate_count = @($ocrCandidates).Count
    candidates = @($ocrCandidates)
    region = [ordered]@{ x=$sx; y=$sy; width=$sw; height=$sh }
  })
}

# ============================================================================
# Action: ocr-uia-invoke  ─ fusion 탐색 + 곧바로 InvokePattern 호출 (v1.0.0)
# ============================================================================
# ocr-uia-fuse 와 같은 로직으로 OCR 좌표 위 UIA element 를 찾되,
# **그 자리에서 element handle 로 InvokePattern.Invoke() 직접 호출**한다.
#
# fusion (read-only) → wrapper 가 element name 으로 다시 uia-invoke 하는 패턴은
# Name 비어있는 element 에 대해 못 동작했음. 이제 한 프로세스 안에서 element
# AutomationElement 인스턴스를 그대로 invoke 하므로 Name 없어도 동작.
#
# 입력: -OcrText "<찾을 텍스트>" [-OcrMatch contains|exact|prefix]
#       [-Match <window 부분 매칭>] [-OcrLanguage ko]
# 출력: { status, method (InvokePattern/TogglePattern/SelectionItemPattern),
#         matched_ocr_text, uia_name, uia_automation_id, uia_class_name,
#         mouse_moved=false }
# 안전:
#   - OCR score < 70 → low_confidence_match → partial(2) 거부
#   - 어떤 pattern 도 지원 안 하면 partial(2)
# ============================================================================
function _Action-OcrUiaInvoke {
  if (-not $OcrText) { _Emit @{status="error"; reason="missing_ocr_text"} 1 }
  if (-not (_Ensure-Win32Native)) { _Emit @{status="error"; reason="win32_load_failed"} 1 }
  if (-not (_Ensure-UIA)) { _Emit @{status="error"; reason="uia_unavailable"} 1 }
  if (-not (_Ensure-OCR)) {
    _Emit @{status="error"; reason="ocr_unavailable"; ocr_error=$Script:_OCRError} 1
  }

  $list = [CucpNative]::EnumerateTopLevel()
  $targetHwnd = [IntPtr]::Zero
  $targetWin = $null
  if ($Match) {
    $needle = $Match.ToLowerInvariant()
    $targetWin = $list | Where-Object { $_.Title -and $_.Title.ToLowerInvariant().Contains($needle) } | Select-Object -First 1
  }
  if (-not $targetWin) {
    $targetWin = $list | Where-Object { $_.Foreground } | Select-Object -First 1
  }
  if ($targetWin) { $targetHwnd = $targetWin.Hwnd }
  if ($targetHwnd -eq [IntPtr]::Zero) {
    _Emit @{status="partial"; reason="no_target_window"} 2
  }

  $capX = $ScreenshotX; $capY = $ScreenshotY; $capW = $ScreenshotW; $capH = $ScreenshotH
  if ($targetWin -and $ScreenshotX -lt 0 -and $ScreenshotY -lt 0 -and $ScreenshotW -le 0 -and $ScreenshotH -le 0) {
    $capX = [int]$targetWin.X
    $capY = [int]$targetWin.Y
    $capW = [int]$targetWin.Width
    $capH = [int]$targetWin.Height
  }

  # 1) 화면 캡처 + OCR (v1.0.0 헬퍼로 추출)
  $cap = _Capture-ScreenRegionToTempPng -RegionX $capX -RegionY $capY `
                                          -RegionW $capW -RegionH $capH `
                                          -Prefix "cucp-ouinv"
  if ($cap.Error) {
    $exitCode = 1
    $statusText = "error"
    if ($cap.Error -eq "screenshot_unavailable") {
      $exitCode = 2
      $statusText = "partial"
    }
    _Emit @{
      status=$statusText
      reason=$cap.Error
      detail=$cap.Detail
      max_dim=$cap.MaxDim
      recommended_action="Retry from an interactive unlocked desktop session, provide a matching foreground window, or use a smaller visible region."
    } $exitCode
  }
  $sx = $cap.X; $sy = $cap.Y; $sw = $cap.W; $sh = $cap.H
  $tmp = $cap.Path
  $ocrTop = $null
  $ocrCandidates = @()
  try {
    $sb = _Load-SoftwareBitmapFromFile -Path $tmp
    $ocrResult = _Wait-AsyncOp ($Script:_OCREngine.RecognizeAsync($sb)) ([Windows.Media.Ocr.OcrResult])
    $body = _Convert-OcrResult -OcrResult $ocrResult -OffsetX $sx -OffsetY $sy
    $ocrCandidates = @(_Match-OcrCandidates -Body $body -Needle $OcrText -Mode $OcrMatch | Select-Object -First $OcrMaxCandidates)
    if ($ocrCandidates.Count -gt 0) { $ocrTop = $ocrCandidates[0] }
  } finally {
    if (Test-Path -LiteralPath $tmp) { Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue }
  }

  if (-not $ocrTop) { _Emit @{status="partial"; reason="no_ocr_match"; ocr_text=$OcrText} 2 }
  if ([int]$ocrTop.score -lt 70) {
    _Emit @{
      status = "partial"
      reason = "low_confidence_match"
      score = [int]$ocrTop.score
      matched_ocr_text = $ocrTop.text
      threshold = 70
    } 2
  }

  $rootEl = [System.Windows.Automation.AutomationElement]::FromHandle($targetHwnd)
  if (-not $rootEl) { _Emit @{status="partial"; reason="uia_root_null"} 2 }

  $allEls = $rootEl.FindAll(
    [System.Windows.Automation.TreeScope]::Descendants,
    [System.Windows.Automation.Condition]::TrueCondition
  )
  $fusion = _Resolve-OcrUiaFusionCandidate -RootEl $rootEl -Elements $allEls -OcrCandidates $ocrCandidates -Limit $OcrMaxCandidates
  if (-not $fusion) {
    _Emit @{status="partial"; reason="no_uia_element_at_ocr_coord"; ocr_top=$ocrTop} 2
  }
  $ocrTop = $fusion.Ocr
  $bestEl = $fusion.Element
  $bestCur = $fusion.Current
  $cx = [int]$ocrTop.cx
  $cy = [int]$ocrTop.cy
  if ([int]$ocrTop.score -lt 70) {
    _Emit @{
      status = "partial"
      reason = "low_confidence_match"
      score = [int]$ocrTop.score
      matched_ocr_text = $ocrTop.text
      threshold = 70
    } 2
  }

  # 3) Pattern 찾고 곧바로 invoke
  $name = ""; try { $name = "$($bestCur.Name)" } catch { }
  $autoId = ""; try { $autoId = "$($bestCur.AutomationId)" } catch { }
  $clazz = ""; try { $clazz = "$($bestCur.ClassName)" } catch { }

  # InvokePattern 우선 — 가장 안전하고 확실
  try {
    $invP = $bestEl.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern)
    if ($invP) {
      $invP.Invoke()
      _Emit ([ordered]@{
        status = "ok"
        method = "InvokePattern"
        matched_ocr_text = $ocrTop.text
        ocr_score = [int]$ocrTop.score
        uia_name = $name
        uia_automation_id = $autoId
        uia_class_name = $clazz
        mouse_moved = $false
      })
    }
  } catch { }

  # TogglePattern (체크박스/라디오)
  try {
    $togP = $bestEl.GetCurrentPattern([System.Windows.Automation.TogglePattern]::Pattern)
    if ($togP) {
      $beforeState = "$($togP.Current.ToggleState)"
      $togP.Toggle()
      _Emit ([ordered]@{
        status = "ok"
        method = "TogglePattern"
        matched_ocr_text = $ocrTop.text
        ocr_score = [int]$ocrTop.score
        uia_name = $name
        uia_automation_id = $autoId
        previous_state = $beforeState
        mouse_moved = $false
      })
    }
  } catch { }

  # SelectionItemPattern (탭/리스트 항목)
  try {
    $selP = $bestEl.GetCurrentPattern([System.Windows.Automation.SelectionItemPattern]::Pattern)
    if ($selP) {
      $selP.Select()
      _Emit ([ordered]@{
        status = "ok"
        method = "SelectionItemPattern"
        matched_ocr_text = $ocrTop.text
        ocr_score = [int]$ocrTop.score
        uia_name = $name
        uia_automation_id = $autoId
        mouse_moved = $false
      })
    }
  } catch { }

  # 어떤 pattern 도 안 잡히면 partial — wrapper 가 좌표 click fallback 해야 함
  _Emit ([ordered]@{
    status = "partial"
    reason = "no_invoke_pattern"
    matched_ocr_text = $ocrTop.text
    ocr_score = [int]$ocrTop.score
    uia_name = $name
    uia_automation_id = $autoId
    uia_class_name = $clazz
    fallback_coord = [ordered]@{ x = $cx; y = $cy }
  }) 2
}

# ============================================================================
# Action: screenshot-diff  ─ 두 PNG 의 픽셀 변화 비율 측정
# ============================================================================
# 클릭 직후 화면이 정말 바뀌었는지 검증하는 용도.
#
# 입력: -DiffBefore <png>  -DiffAfter <png>  [-DiffThreshold 16]
#       [-ScreenshotX/Y/W/H — 비교 영역, 비어있으면 두 PNG 의 교집합 영역 사용]
# 출력: { width, height, total_pixels, changed_pixels, changed_ratio,
#         changed=bool, threshold }
# 알고리즘:
#   - 픽셀 단위 ARGB 비교, |R1-R2| + |G1-G2| + |B1-B2| > threshold 면 변화로 카운트
#   - changed_ratio = changed_pixels / total_pixels
#   - changed = (changed_ratio > 0.001)  // 0.1% 이상 달라야 의미있는 변화
# 정확도/속도: LockBits + 마샬링으로 픽셀 직접 접근, 1920x1080 ~150ms 수준
# ============================================================================
function _Action-ScreenshotDiff {
  _Require-LegacyImages
  $result = [PcuCp.LegacyImages.ScreenshotDiff]::Compare($DiffBefore, $DiffAfter, $ScreenshotX, $ScreenshotY, $ScreenshotW, $ScreenshotH, $DiffThreshold, $DiffIgnoreRegions)
  _Emit $result.Data $result.ExitCode
}

# ============================================================================
# v1.4.0 Action: cdp-deep-find  ─ Shadow DOM + same-origin iframe traversal report
# ============================================================================
# 동기: smart-find/smart-type 가 deepCollect 로 shadow/iframe 안까지 보지만,
# 그 traversal 메타정보 (몇 개 shadow root, iframe 통과했는지) 가 외부에 안 보임.
# 이 액션은 read-only 로 그 정보를 노출해서 디버깅/검증/벤치마크에 사용.
#
# 입력: -CdpText "<label>" [-CdpPort 9222] [-CdpPageMatch <s>]
# 출력: {
#   status, page_id, page_url, page_title,
#   traversal: { hops, shadow_roots_seen, iframes_seen, iframes_blocked, total_nodes },
#   found_count, top_matches: [...]
# }
# ============================================================================


# ============================================================================
# v1.4.0 Action: ime-paste  ─ 한국어 IME-safe 텍스트 입력 (clipboard route)
# ============================================================================
# 동기: SendInput WM_CHAR 로 한글을 보내면 IME 가 조합 모드일 때 깨지거나 분리됨.
# Notepad, Word, 브라우저 contenteditable 등에서 발생.
# 해결: System.Windows.Forms.Clipboard 로 텍스트 임시 저장 → Ctrl+V 단축키로 paste.
# 원래 클립보드 내용은 복원.
#
# 입력: -Text <string> [-PressEnter] [-TargetMatch <s>] [-TargetHwnd N]
# 출력: { status, method=clipboard_paste, text_len, restored_clipboard, mouse_moved=false }
#
# 안전성:
#   - hit-test 가드 (TargetMatch/TargetHwnd) 통과해야 paste
#   - 클립보드 백업/복구
#   - 마우스 안 움직임
# ============================================================================
function _Action-ImePaste {
  if (-not $Text) {
    _Emit @{status="error"; reason="missing_text"; recommended_action="provide -Text"} 1
  }
  Add-Type -AssemblyName System.Windows.Forms -ErrorAction Stop
  Add-Type -AssemblyName System.Drawing -ErrorAction Stop

  # hit-test 가드 — TargetMatch/TargetHwnd 가 있으면 현재 foreground 검증
  $guardEvidence = $null
  if ($TargetHwnd -gt 0 -or $TargetMatch) {
    try {
      $fg = [Win32Helper]::GetForegroundWindow()
      $sb = New-Object System.Text.StringBuilder 512
      [void][Win32Helper]::GetWindowText($fg, $sb, 512)
      $title = $sb.ToString()
      $hwndOk = ($TargetHwnd -gt 0 -and $TargetHwnd -eq [int]$fg)
      $titleOk = ($TargetMatch -and $title -and ($title -match [regex]::Escape($TargetMatch)))
      $guardEvidence = [ordered]@{
        foreground_hwnd = [int]$fg
        foreground_title = $title
        match_hwnd = $hwndOk
        match_title = $titleOk
      }
      if (-not ($hwndOk -or $titleOk)) {
        _Emit @{status="blocked"; reason="target_mismatch"; guard=$guardEvidence; recommended_action="focus the target window first"} 3
      }
    } catch {
      _Emit @{status="error"; reason="hit_test_failed"; detail=$_.Exception.Message} 1
    }
  }

  # 클립보드 백업
  $restored = $false
  $oldText = $null
  try {
    if ([System.Windows.Forms.Clipboard]::ContainsText()) {
      $oldText = [System.Windows.Forms.Clipboard]::GetText()
    }
  } catch { $oldText = $null }

  try {
    # SetText 는 STA thread 필요 — PowerShell 5.x 기본은 MTA 일 수 있음
    # 안전하게 SetDataObject + true (persist) 사용
    [System.Windows.Forms.Clipboard]::SetDataObject($Text, $true, 5, 100)
    Start-Sleep -Milliseconds 60

    # Ctrl+V 단축키 송출 (SendKeys 가 IME 우회)
    [System.Windows.Forms.SendKeys]::SendWait("^v")
    Start-Sleep -Milliseconds 80

    if ($PressEnter) {
      [System.Windows.Forms.SendKeys]::SendWait("{ENTER}")
      Start-Sleep -Milliseconds 40
    }
  } catch {
    _Emit @{status="error"; reason="paste_failed"; detail=$_.Exception.Message} 1
  } finally {
    # 클립보드 복구 (원래 내용이 있었던 경우만)
    try {
      if ($null -ne $oldText) {
        [System.Windows.Forms.Clipboard]::SetDataObject($oldText, $true, 5, 100)
        $restored = $true
      }
    } catch { $restored = $false }
  }

  _Emit ([ordered]@{
    status = "ok"
    method = "clipboard_paste"
    text_len = [int]$Text.Length
    pressed_enter = [bool]$PressEnter
    restored_clipboard = $restored
    guard = $guardEvidence
    mouse_moved = $false
  })
}

# ============================================================================
# ============================================================================
# v1.7.0 Action: cdp-prosemirror-insert  ─ ProseMirror live 텍스트 입력
# ============================================================================
# 동기: ProseMirror / TipTap 같은 contenteditable 에디터는 v1.3.0 부터 부채.
# 이전 cdp-type / cdp-smart-type 의 execCommand('insertText') 는 React/Vue
# state machine 이 거부. CDP `Input.insertText` 는 OS-level keyboard event
# simulation 이라 ProseMirror schema 가 수용함.
#
# 입력: -CdpText <text>  -CdpSelector <css>  [-CdpPort 9222] [-CdpPageMatch <s>]
# 출력: { status, route, before_value, after_value, changed, page_id, page_title }
# ============================================================================


# ============================================================================
# v1.4.0 Action: modal-detect  ─ 모달/팝업/대화상자 감지 (UI recovery loop 용)
# ============================================================================
# 동기: 라이브 step 이 실패한 후, "왜 실패했지?" 를 답하기 위해 화면에 새로 떴거나
# 사라진 모달/대화상자를 자동 감지해서 다음 안전한 retry 경로를 제안.
# 메모: 이 액션은 read-only — 어떤 클릭도 안 하고 UIA tree + window enum 만.
#
# 입력: [-Match <s>] [-TargetHwnd N]
# 출력: {
#   status, foreground: { hwnd, title, class },
#   modal_candidates: [{ hwnd, title, class, role, score, reason }],
#   recommended_action: "dismiss | confirm | wait | observe"
# }
# ============================================================================
function _Action-ModalDetect {
  Add-Type -AssemblyName UIAutomationClient -ErrorAction SilentlyContinue
  Add-Type -AssemblyName UIAutomationTypes -ErrorAction SilentlyContinue
  $candidates = @()
  $fgInfo = $null
  try {
    $fg = [Win32Helper]::GetForegroundWindow()
    $sb = New-Object System.Text.StringBuilder 512
    [void][Win32Helper]::GetWindowText($fg, $sb, 512)
    $clsB = New-Object System.Text.StringBuilder 256
    [void][Win32Helper]::GetClassName($fg, $clsB, 256)
    $fgInfo = [ordered]@{
      hwnd = [int]$fg
      title = $sb.ToString()
      class = $clsB.ToString()
    }
  } catch { $fgInfo = $null }

  # UIA: WindowPattern 의 IsModal=true 또는 control type Window/Pane 중 작은 사이즈
  try {
    $root = [System.Windows.Automation.AutomationElement]::RootElement
    $cond = New-Object System.Windows.Automation.OrCondition @(
      (New-Object System.Windows.Automation.PropertyCondition `
        ([System.Windows.Automation.AutomationElement]::ControlTypeProperty),
        ([System.Windows.Automation.ControlType]::Window)),
      (New-Object System.Windows.Automation.PropertyCondition `
        ([System.Windows.Automation.AutomationElement]::ControlTypeProperty),
        ([System.Windows.Automation.ControlType]::Pane))
    )
    $els = $root.FindAll([System.Windows.Automation.TreeScope]::Children, $cond)
    foreach ($el in $els) {
      try {
        $name = "$($el.Current.Name)"
        $cls  = "$($el.Current.ClassName)"
        $rect = $el.Current.BoundingRectangle
        $isModal = $false
        try {
          $wp = $el.GetCurrentPattern([System.Windows.Automation.WindowPattern]::Pattern)
          if ($wp -and $wp.Current.IsModal) { $isModal = $true }
        } catch { }
        $reason = $null
        $score = 0
        if ($isModal) { $score += 100; $reason = "uia_window_is_modal" }
        # 흔한 dialog class names
        if ($cls -match "(?i)#32770|MessageBox|Dialog|TaskDialog|Popup") {
          $score += 60
          if (-not $reason) { $reason = "dialog_class_name" }
        }
        # 작은 윈도우 (~600x400 이하) + 짧은 제목
        if ($rect -and $rect.Width -gt 0 -and $rect.Width -lt 900 -and $rect.Height -gt 0 -and $rect.Height -lt 600) {
          $score += 20
          if (-not $reason) { $reason = "small_window_size" }
        }
        if ($score -gt 0) {
          $hwndProp = $null
          try { $hwndProp = [int]$el.Current.NativeWindowHandle } catch { $hwndProp = $null }
          $candidates += [ordered]@{
            hwnd = $hwndProp
            title = $name
            class = $cls
            role = "$($el.Current.LocalizedControlType)"
            rect = [ordered]@{ x=[int]$rect.X; y=[int]$rect.Y; w=[int]$rect.Width; h=[int]$rect.Height }
            score = $score
            reason = $reason
            is_modal = $isModal
          }
        }
      } catch { continue }
    }
  } catch { }

  # 가장 점수 높은 후보로 추천 행동
  $sorted = @($candidates | Sort-Object -Property score -Descending)
  $rec = "observe"
  if ($sorted.Count -gt 0) {
    $top = $sorted[0]
    if ($top.is_modal -or ($top.score -ge 100)) { $rec = "dismiss_or_confirm" }
    elseif ($top.score -ge 60) { $rec = "confirm_dialog" }
    else { $rec = "wait" }
  }
  _Emit ([ordered]@{
    status = "ok"
    foreground = $fgInfo
    modal_candidates = $sorted
    candidate_count = [int]$sorted.Count
    recommended_action = $rec
  })
}

# ============================================================================
# Dispatch
# ============================================================================
try {
switch ($Action) {
  "health"        { _Action-Health }
  "windows"       { _Action-Windows }
  "focused"       { _Action-Focused }
  "focus"         { _Action-Focus }
  "screenshot"    { _Action-Screenshot }
  "click"         { _Action-Click }
  "type"          { _Action-Type }
  "shortcut"      { _Action-Shortcut }
  "uia-tree"      { _Action-UiaTree }
  "uia-find"      { _Action-UiaFind }
  "uia-click"     { _Action-UiaClick }
  "uia-invoke"    { _Action-UiaInvoke }
  "uia-set-value" { _Action-UiaSetValue }
  "uia-toggle"    { _Action-UiaToggle }
  "ocr-image"       { _Action-OcrImage }
  "ocr-screen"      { _Action-OcrScreen }
  "ocr-find-text"   { _Action-OcrFindText }
  "ocr-uia-fuse"    { _Action-OcrUiaFuse }
  "ocr-uia-invoke"  { _Action-OcrUiaInvoke }
  "screenshot-diff" { _Action-ScreenshotDiff }
  "hit-test"        { _Action-HitTest }
  "hit-scan"        { _Action-HitScan }
  "cdp-detect"      { _Action-CdpDetect }
  "cdp-eval"        { _Action-CdpEval }
  "cdp-type"        { _Action-CdpType }
  "cdp-click"       { _Action-CdpClick }
  "cdp-smart-click" { _Action-CdpSmartClick }
  "cdp-smart-find"  { _Action-CdpSmartFind }
  "cdp-smart-type-find" { _Action-CdpSmartTypeFind }
  "cdp-smart-type"  { _Action-CdpSmartType }
  "cdp-deep-find"   { _Action-CdpDeepFind }
  "cdp-prosemirror-insert" { _Action-CdpProseMirrorInsert }
  "ime-paste"       { _Action-ImePaste }
  "modal-detect"    { _Action-ModalDetect }
}
} catch {
  _Emit ([ordered]@{
    status = "error"
    reason = "native_action_failed"
    detail = $_.Exception.Message
    retryable = $false
  }) 1
}

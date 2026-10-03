# Candidate-only read observation adapter. Original functions remain in the helper.
# Opt-in is for qualification only; no portable installation or default activation.
function _Require-LegacyObservation {
  if ($Script:_LegacyObservationActions) { return }
  $dll = $env:CUCP_LEGACY_OBSERVATION_DLL
  if (-not $dll) { $dll = Join-Path $PSScriptRoot '..\pcucp-next\bin\legacy-observation\PcuCp.LegacyObservation.dll' }
  $type = 'PcuCp.LegacyObservation.ObservationActions' -as [type]
  if ($type -and $type.Assembly.GetName().Name -ne 'PcuCp.LegacyObservation') { throw 'Unexpected observation assembly.' }
  if (-not $type) {
    if (-not (Test-Path -LiteralPath $dll -PathType Leaf)) { throw 'Candidate observation DLL missing; build the separate net48 observation package.' }
    Add-Type -LiteralPath $dll -ErrorAction Stop
  }
  $Script:_LegacyObservationProvider = New-Object PcuCp.LegacyObservation.WindowsObservationProvider
  $Script:_LegacyObservationPrimitives = New-Object PcuCp.LegacyObservation.ObservationPrimitives($Script:_LegacyObservationProvider)
  $Script:_LegacyObservationActions = New-Object PcuCp.LegacyObservation.ObservationActions($Script:_LegacyObservationProvider)
}
function _New-LegacyObservationOptions {
  _Require-LegacyObservation
  $o = New-Object PcuCp.LegacyObservation.ObservationOptions
  $o.HasCoordinates = $Script:_HasCoordinates
  $o.X=$X; $o.Y=$Y; $o.TargetHwnd=$TargetHwnd; $o.TargetMatch=$TargetMatch
  $o.ClickInset=$ClickInset; $o.ScanRadius=$ScanRadius; $o.ScanStep=$ScanStep; $o.SkipUia=[bool]$SkipUia
  $o.Match=$Match; $o.Label=$Label; $o.Role=$Role; $o.MaxElements=$MaxElements; $o.MinSize=$MinSize
  return $o
}
function _Get-UiaSupportedPatternName {
  param($Element)
  if (-not $Element) { return $null }
  _Require-LegacyObservation
  return $Script:_LegacyObservationPrimitives.SupportedPattern($Element)
}
function _New-UiaMatchPayload {
  param($Cur, [string]$PatternName)
  _Require-LegacyObservation
  return $Script:_LegacyObservationPrimitives.MatchPayload($Cur, $PatternName)
}
function _Get-RoleWeight {
  param([string]$Role)
  _Require-LegacyObservation
  return $Script:_LegacyObservationPrimitives.RoleWeight($Role)
}
function _Clamp-UiaPointToRect {
  param([double]$X, [double]$Y, $Rect, [int]$Inset=3, [string]$Source='center', [bool]$NativeClickable=$false)
  if (-not $Rect) { return $null }
  _Require-LegacyObservation
  return $Script:_LegacyObservationPrimitives.Clamp($X, $Y, [PcuCp.LegacyObservation.WindowsObservationProvider]::RectFromNative($Rect), $Inset, $Source, $NativeClickable)
}
function _Get-UiaPreferredClickPoint {
  param($Element, $Rect, [int]$Inset=3)
  if (-not $Element -or -not $Rect) { return $null }
  _Require-LegacyObservation
  return $Script:_LegacyObservationPrimitives.PreferredClickPoint($Element, [PcuCp.LegacyObservation.WindowsObservationProvider]::RectFromNative($Rect), $Inset)
}
function _Resolve-UiaPointRefinement {
  param([int]$X, [int]$Y, [int]$MaxWidth=360, [int]$MaxHeight=220, [int]$Inset=3)
  _Require-LegacyObservation
  return $Script:_LegacyObservationPrimitives.ResolvePoint($X, $Y, $MaxWidth, $MaxHeight, $Inset)
}
function _Test-CoordsInTarget {
  param([int]$X, [int]$Y, [int]$ExpectedHwnd, [string]$ExpectedMatch)
  _Require-LegacyObservation
  return $Script:_LegacyObservationPrimitives.TestTarget($X, $Y, $ExpectedHwnd, $ExpectedMatch)
}
function _Action-HitTest {
  if (-not (_Ensure-Win32Native)) { _Emit @{status='error'; reason='win32_load_failed'} 1 }
  if (-not $Script:_HasCoordinates) { _Emit @{status='error'; reason='missing_coords'; recommended_action='provide -X and -Y (zero and negative screen coordinates are valid)'} 1 }
  $options = _New-LegacyObservationOptions
  $result = $Script:_LegacyObservationActions.HitTest($options)
  _Emit $result.Payload $result.ExitCode
}
function _Action-HitScan {
  if (-not (_Ensure-Win32Native)) { _Emit @{status='error'; reason='win32_load_failed'} 1 }
  if (-not $Script:_HasCoordinates) { _Emit @{status='error'; reason='missing_coords'; recommended_action='provide -X and -Y (zero and negative screen coordinates are valid)'} 1 }
  $options = _New-LegacyObservationOptions
  $result = $Script:_LegacyObservationActions.HitScan($options)
  _Emit $result.Payload $result.ExitCode
}
function _Action-UiaTree {
  if (-not (_Ensure-Win32Native)) { _Emit @{status='error'; reason='win32_load_failed'} 1 }
  if (-not (_Ensure-UIA)) { _Emit @{status='partial'; reason='uia_unavailable'; recommended_action='UIAutomationClient assembly load failed'} 2 }
  $options = _New-LegacyObservationOptions
  $result = $Script:_LegacyObservationActions.UiaTree($options)
  _Emit $result.Payload $result.ExitCode
}
function _Action-UiaFind {
  if (-not $Label) { _Emit @{status='error'; reason='missing_label'} 1 }
  if (-not (_Ensure-Win32Native)) { _Emit @{status='error'; reason='win32_load_failed'} 1 }
  if (-not (_Ensure-UIA)) { _Emit @{status='partial'; reason='uia_unavailable'} 2 }
  $options = _New-LegacyObservationOptions
  $result = $Script:_LegacyObservationActions.UiaFind($options)
  _Emit $result.Payload $result.ExitCode
}

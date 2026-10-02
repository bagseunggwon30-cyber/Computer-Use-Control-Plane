# Qualification-only exact adapter draft. The integrator owns promotion.
function _Require-LegacyImages {
  if ('PcuCp.LegacyImages.FileOcr' -as [type]) { return }
  $dll = $env:CUCP_LEGACY_IMAGES_DLL
  if (-not $dll) { $dll = Join-Path $PSScriptRoot '..\pcucp-next\bin\legacy\PcuCp.LegacyImages.dll' }
  if (-not (Test-Path -LiteralPath $dll -PathType Leaf)) { throw 'Legacy images DLL missing. Run python pcucp-next/packaging/publish_legacy_images.py or set CUCP_LEGACY_IMAGES_DLL.' }
  Add-Type -LiteralPath $dll -ErrorAction Stop
}

function _Action-ScreenshotDiff {
  _Require-LegacyImages
  $result = [PcuCp.LegacyImages.ScreenshotDiff]::Compare($DiffBefore, $DiffAfter, $ScreenshotX, $ScreenshotY, $ScreenshotW, $ScreenshotH, $DiffThreshold, $DiffIgnoreRegions)
  _Emit $result.Data $result.ExitCode
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

function _Wait-AsyncOp {
  param($AsyncOp, [Type]$ResultType)
  _Require-LegacyImages
  $result = [PcuCp.LegacyImages.FileOcr]::TryWaitAsyncOperation($AsyncOp, $ResultType)
  if ($null -ne $result.Error) { throw $result.Error }
  return $result.Value
}

function _Load-SoftwareBitmapFromFile {
  param([string]$Path)
  _Require-LegacyImages
  $result = [PcuCp.LegacyImages.FileOcr]::TryLoadSoftwareBitmapFromFile($Path)
  if ($null -ne $result.Error) { throw $result.Error }
  return $result.Value
}

function _Convert-OcrResult {
  param($OcrResult, [int]$OffsetX = 0, [int]$OffsetY = 0)
  _Require-LegacyImages
  return [PcuCp.LegacyImages.FileOcr]::ConvertResult($OcrResult, $OffsetX, $OffsetY)
}

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

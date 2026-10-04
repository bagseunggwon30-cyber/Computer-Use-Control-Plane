param([Parameter(Mandatory=$true)][string]$Root,
      [Parameter(Mandatory=$true)][string]$OutputPath)
$ErrorActionPreference = 'Stop'
$rootPath = [IO.Path]::GetFullPath($Root).TrimEnd([char[]]@('\','/'))
$utf8 = New-Object Text.UTF8Encoding($false, $true)
$sha = [Security.Cryptography.SHA256]::Create()
function SourceHash([string]$Text) {
  return [BitConverter]::ToString($sha.ComputeHash($utf8.GetBytes($Text))).Replace('-','').ToLowerInvariant()
}
try {
  $paths = @(Get-ChildItem -LiteralPath (Join-Path $rootPath 'scripts') -Filter '*.ps1' -File)
  $paths += @(Get-ChildItem -LiteralPath (Join-Path $rootPath 'tests\fixtures') -Filter 'legacy-*-adapter.ps1' -File)
  $files = @(foreach ($file in ($paths | Sort-Object FullName)) {
    # Git stores LF source. ReadAllText removes the optional UTF-8 BOM; parsing
    # normalized text makes offsets identical across Windows/cloud checkouts.
    $text = [IO.File]::ReadAllText($file.FullName, $utf8).Replace("`r`n", "`n")
    $tokens = $null; $errors = $null
    $ast = [Management.Automation.Language.Parser]::ParseInput($text, [ref]$tokens, [ref]$errors)
    if ($errors.Count) { throw "Source-map parse failed for $($file.Name): $($errors[0].Message)" }
    $functions = @(foreach ($fn in $ast.FindAll({param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst]}, $true)) {
      $parentName = $null; $parent = $fn.Parent
      while ($null -ne $parent) {
        if ($parent -is [Management.Automation.Language.FunctionDefinitionAst]) { $parentName = $parent.Name; break }
        $parent = $parent.Parent
      }
      [pscustomobject][ordered]@{
        name = $fn.Name; parent_function = $parentName
        start_utf16 = $fn.Extent.StartOffset; end_utf16 = $fn.Extent.EndOffset
        sha256 = SourceHash $fn.Extent.Text
      }
    })
    [pscustomobject][ordered]@{
      path = $file.FullName.Substring($rootPath.Length).TrimStart([char[]]@('\','/')).Replace('\','/')
      sha256 = SourceHash $text
      utf16_length = [int64]($text.Length)
      functions = $functions
    }
  })
  if (-not $files.Count) { throw 'No migration source files were mapped.' }
  $result = [ordered]@{schema='cucp.migration-source-map/v1';encoding='utf-8-no-bom-lf';files=$files}
  [IO.File]::WriteAllText([IO.Path]::GetFullPath($OutputPath), (ConvertTo-Json -InputObject $result -Depth 8 -Compress), $utf8)
  [Console]::Out.WriteLine("Mapped $($files.Count) source files without executing their contents.")
} finally { $sha.Dispose() }

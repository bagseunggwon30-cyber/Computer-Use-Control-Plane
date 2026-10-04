# Opt-in diagnostic only. Breakpoint actions observe the unchanged wrapper;
# they do not replace functions, captured replies, providers or JSON payloads.
# A killed process cannot run finally: the process owner must also hash the
# wrapper after termination. Neither markers nor this probe earn parity credit.

function Get-ObservationTraceSourceHash {
 param([string]$Path)
 $sha=[Security.Cryptography.SHA256]::Create()
 try { return ([BitConverter]::ToString($sha.ComputeHash([IO.File]::ReadAllBytes($Path)))).Replace('-','').ToLowerInvariant() }
 finally { $sha.Dispose() }
}

function global:Write-ObservationSmartPlanTrace {
 param([string]$Phase,$CapturedArguments,$RawText,$ErrorText,[string]$SourceHash)
 $traceState=$global:__CucpObservationSmartPlanTrace
 if($null -eq $traceState){throw 'SmartPlan trace state is unavailable.'}
 $captureCount=-1
 if($CapturedArguments -is [Collections.IDictionary] -and $CapturedArguments.Contains('captured_replies')){
  $traceCaptures=@($CapturedArguments.captured_replies)
  $captureCount=$traceCaptures.Count
  if($captureCount -gt 0){
   $lastReply=$traceCaptures[$captureCount-1].result
   if($null -ne $lastReply){
    $rawProperty=$lastReply.PSObject.Properties['Raw']
    $errProperty=$lastReply.PSObject.Properties['Err']
    if($null -ne $rawProperty){$RawText=$rawProperty.Value}
    if($null -ne $errProperty){$ErrorText=$errProperty.Value}
   }
  }
 }
 $parts=New-Object 'Collections.Generic.List[string]'
 $parts.Add('cucp.smart-plan-trace/v1')
 $parts.Add('phase='+$Phase)
 $parts.Add('elapsed_ms='+$traceState.Clock.ElapsedMilliseconds)
 $parts.Add('captures='+$captureCount)
 foreach($field in @(@{Name='raw';Value=$RawText},@{Name='err';Value=$ErrorText})){
  $value=$field.Value
  $baseType='null';$length='null';$names=''
  if($null -ne $value){
   $baseType=$value.PSObject.BaseObject.GetType().FullName
   if($value -is [string]){$length=[string]$value.Length}
   # Inspect only property names, never values of PSDrive/PSProvider or any
   # recursive JSON serialization of the decorated object being diagnosed.
   $propertyNames=@($value.PSObject.Properties | ForEach-Object { $_.Name })
   $names=$propertyNames -join '|'
  }
  $parts.Add($field.Name+'.type='+$baseType)
  $parts.Add($field.Name+'.length='+$length)
  $parts.Add($field.Name+'.properties='+$names)
 }
 if($SourceHash){$parts.Add('wrapper_sha256='+$SourceHash)}
 $line=$parts -join "`t"
 # Close/flush every marker before returning to a potentially hung statement.
 $stream=[IO.File]::Open($traceState.Path,[IO.FileMode]::Append,[IO.FileAccess]::Write,[IO.FileShare]::ReadWrite)
 try {
  $bytes=$traceState.Utf8.GetBytes($line+[Environment]::NewLine)
  $stream.Write($bytes,0,$bytes.Length)
  $stream.Flush($true)
 } finally {$stream.Dispose()}
 [Console]::Error.WriteLine($line)
 [Console]::Error.Flush()
}

function Enable-ObservationSmartPlanTrace {
 param([string]$WrapperPath,[string]$TracePath)
 if($null -ne (Get-Variable -Name __CucpObservationSmartPlanTrace -Scope Global -ErrorAction SilentlyContinue)){throw 'SmartPlan trace is already active.'}
 $wrapper=[IO.Path]::GetFullPath($WrapperPath)
 $traceFile=[IO.Path]::GetFullPath($TracePath)
 if($wrapper -eq $traceFile){throw 'TracePath must not be the wrapper source.'}
 if(-not [IO.Directory]::Exists([IO.Path]::GetDirectoryName($traceFile))){throw 'TracePath parent directory must already exist.'}
 $before=Get-ObservationTraceSourceHash -Path $wrapper
 $tokens=$null;$errors=$null
 $ast=[Management.Automation.Language.Parser]::ParseFile($wrapper,[ref]$tokens,[ref]$errors)
 if($errors.Count){throw 'Cannot trace a wrapper with parse errors.'}
 $lines=[IO.File]::ReadAllLines($wrapper)
 $points=@(
  @{Phase='compat.serialize.enter';Function='_Invoke-LegacyCompatibility';Statement='$payload = @{schema=''cucp.legacy-compat/v1''; operation=$Operation; args=$Arguments; culture=[Globalization.CultureInfo]::CurrentCulture.Name} | ConvertTo-Json -Depth 24 -Compress'},
  @{Phase='compat.serialize.done';Function='_Invoke-LegacyCompatibility';Statement='$utf8 = New-Object System.Text.UTF8Encoding($false, $true)'},
  @{Phase='compat.process.start';Function='_Invoke-LegacyCompatibility';Statement='[void]$process.Start()'},
  @{Phase='compat.process.wait.done';Function='_Invoke-LegacyCompatibility';Statement='$out = $stdout.GetAwaiter().GetResult()'},
  @{Phase='native.call.enter';Function='Invoke-MacroSmartPlan';Statement='''native'' { $capture.result = Invoke-NativeHelper -ArgList $descriptor.argv }'},
  @{Phase='native.text.read.done';Function='Invoke-NativeHelper';Statement='$json = $null'},
  @{Phase='capture.replay';Function='Invoke-MacroSmartPlan';Statement='$state=_Invoke-LegacyCompatibility -Operation ''smart-plan-advance'' -Arguments $arguments'},
  @{Phase='plan.complete';Function='Invoke-MacroSmartPlan';Statement='$sw.Stop();$elapsed=[int]$sw.Elapsed.TotalMilliseconds'}
 )
 # Resolve every marker before installing any breakpoint. Exact statements
 # must remain unique within the actual parsed production function extent.
 foreach($point in $points){
  $name=$point.Function
  $functions=@($ast.FindAll({param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -ceq $name},$true))
  if($functions.Count -ne 1){throw ('Expected one trace function: '+$name)}
  $matchingLines=@(for($number=$functions[0].Extent.StartLineNumber;$number -le $functions[0].Extent.EndLineNumber;$number++){
   if($lines[$number-1].Trim() -ceq $point.Statement){$number}
  })
  if($matchingLines.Count -ne 1){throw ('Expected one trace statement: '+$point.Phase)}
  $point.Line=$matchingLines[0]
 }
 $trace=[pscustomobject]@{Wrapper=$wrapper;Path=$traceFile;BeforeHash=$before;Breakpoints=@();Clock=[Diagnostics.Stopwatch]::StartNew();Utf8=(New-Object Text.UTF8Encoding($false))}
 $global:__CucpObservationSmartPlanTrace=$trace
 try {
  Write-ObservationSmartPlanTrace -Phase 'wrapper.sha.before' -SourceHash $before
  foreach($point in $points){
   # All phase names are fixed fixture literals. Argument values are read from
   # the debugged scope and passed directly; no source/data is interpolated.
   $action=[scriptblock]::Create("Write-ObservationSmartPlanTrace -Phase '"+$point.Phase+"' -CapturedArguments `$Arguments -RawText `$raw -ErrorText `$err")
   $trace.Breakpoints+=Set-PSBreakpoint -Script $wrapper -Line $point.Line -Action $action
  }
  $installed=Get-ObservationTraceSourceHash -Path $wrapper
  Write-ObservationSmartPlanTrace -Phase 'wrapper.sha.after.install' -SourceHash $installed
  if($installed -cne $before){throw 'Trace installation changed wrapper source.'}
  return $trace
 } catch {
  foreach($breakpoint in $trace.Breakpoints){Remove-PSBreakpoint -Breakpoint $breakpoint -ErrorAction SilentlyContinue}
  Remove-Variable -Name __CucpObservationSmartPlanTrace -Scope Global -ErrorAction SilentlyContinue
  throw
 }
}

function Disable-ObservationSmartPlanTrace {
 param($Trace)
 try {
  $after=Get-ObservationTraceSourceHash -Path $Trace.Wrapper
  Write-ObservationSmartPlanTrace -Phase 'wrapper.sha.after.invocation' -SourceHash $after
  if($after -cne $Trace.BeforeHash){throw 'Wrapper source changed during diagnostic invocation.'}
 } finally {
  foreach($breakpoint in $Trace.Breakpoints){Remove-PSBreakpoint -Breakpoint $breakpoint -ErrorAction SilentlyContinue}
  Remove-Variable -Name __CucpObservationSmartPlanTrace -Scope Global -ErrorAction SilentlyContinue
 }
}

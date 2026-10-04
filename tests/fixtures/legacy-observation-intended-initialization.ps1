# Oracle-only insertion immediately before the otherwise unchanged dispatch.
# This ordinary counted file is never loaded by the shipping helper.
if ($Action -notin @('hit-test','hit-scan','uia-tree','uia-find')) { throw 'Intended initialization permits read-only observation actions only.' }
if (-not (_Ensure-Win32Native) -or -not (_Ensure-UIA)) { throw 'Intended initialization requires original Win32/UIA loaders.' }
if (-not $env:CUCP_OBSERVATION_INTENDED_DLL -or -not $env:CUCP_OBSERVATION_INTENDED_READY -or -not $env:CUCP_OBSERVATION_INTENDED_EVIDENCE) { throw 'Missing owned intended-initialization fixture paths.' }
$intendedReady=[IO.File]::ReadAllText($env:CUCP_OBSERVATION_INTENDED_READY) | ConvertFrom-Json
if ($intendedReady.schema -cne 'cucp.owned-observation-window/v1' -or $intendedReady.hwnd -le 0 -or $intendedReady.pid -le 0) { throw 'Invalid owned intended-initialization target.' }
Add-Type -LiteralPath $env:CUCP_OBSERVATION_INTENDED_DLL
$intendedRoot=[PcuCp.ObservationIntendedProvider.PublicUiaInitialization]::FromOwnedHandle([long]$intendedReady.hwnd)
if ($null -eq $intendedRoot -or $intendedRoot.Current.NativeWindowHandle -ne $intendedReady.hwnd -or $intendedRoot.Current.ProcessId -ne $intendedReady.pid) { throw 'Intended initialization escaped the owned HWND/PID.' }
$intendedEvidence=[ordered]@{schema='cucp.observation-intended-initialization/v1';pid=$PID;target_pid=[int]$intendedReady.pid;target_hwnd=[long]$intendedReady.hwnd;returned_pid=$intendedRoot.Current.ProcessId;returned_hwnd=$intendedRoot.Current.NativeWindowHandle;element_type=$intendedRoot.GetType().AssemblyQualifiedName;current_type=$intendedRoot.Current.GetType().AssemblyQualifiedName;client_proxies_loaded=@([AppDomain]::CurrentDomain.GetAssemblies() | Where-Object {$_.GetName().Name -eq 'UIAutomationClientsideProviders'}).Count -eq 1}
if (-not $intendedEvidence.client_proxies_loaded) { throw 'Normal compiled UIA initialization did not load client providers.' }
[IO.File]::WriteAllText((Join-Path $env:CUCP_OBSERVATION_INTENDED_EVIDENCE ("initialization-$PID-"+[Guid]::NewGuid().ToString('N')+'.json')),(ConvertTo-Json -InputObject $intendedEvidence -Depth 5 -Compress),(New-Object Text.UTF8Encoding($false)))

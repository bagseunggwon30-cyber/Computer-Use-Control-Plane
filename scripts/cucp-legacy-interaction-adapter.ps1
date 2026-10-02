# Interaction-only hooks for the qualified shared execution transport.
# This file owns no process startup, framing, permission policy, or fallback.
function _Interaction-Integer($Value) {return ($Value -is [int] -or $Value -is [long])}
function _Interaction-Number($Value) {return (_Interaction-Integer $Value) -or $Value -is [double] -or $Value -is [decimal]}
function _Interaction-Text($Value) {return $null -eq $Value -or $Value -is [string]}
function _Interaction-Point($Point,[switch]$Normalized) {
  _Execution-Fields $Point @('x','y')
  if($Normalized){_Execution-Require ((_Interaction-Number $Point.x) -and (_Interaction-Number $Point.y)) 'Invalid normalized interaction point.'}
  else {_Execution-Require ((_Interaction-Integer $Point.x) -and (_Interaction-Integer $Point.y)) 'Invalid interaction point.'}
}
function _Interaction-Arguments([string[]]$Argv,[int]$Start,[string[]]$Allowed,[string[]]$Required) {
  _Execution-Require (($Argv.Count-$Start)%2 -eq 0) 'Interaction argument arity mismatch.'
  $seen=@{}
  for($i=$Start;$i -lt $Argv.Count;$i+=2){
    _Execution-Require ($Argv[$i] -cin $Allowed -and -not $seen.ContainsKey($Argv[$i])) 'Unknown or duplicate interaction argument.'
    $seen[$Argv[$i]]=$Argv[$i+1]
  }
  foreach($field in $Required){_Execution-Require ($seen.ContainsKey($field)) 'Missing required interaction argument.'}
  return $seen
}
function _Interaction-Record($Record) {
  _Execution-Fields $Record @('ts','anchor_id','anchor_type','target_match','target_hwnd_current','process','class','title','source_point','screen_point','normalized_window_point','visible_normalized_point','safe_to_reuse','coordinate_risk','coord_signature','window_rect')
  _Execution-Require ($Record.ts -is [string] -and $Record.anchor_id -is [string] -and $Record.anchor_id -cmatch '\A[a-f0-9]{32}\z' -and $Record.anchor_type -ceq 'click_point_live_route' -and
    (_Interaction-Text $Record.target_match) -and (_Interaction-Integer $Record.target_hwnd_current) -and $Record.process -is [string] -and $Record.class -is [string] -and
    $Record.title -is [string] -and $Record.safe_to_reuse -is [bool] -and $Record.coordinate_risk -is [string] -and $Record.coord_signature -is [string]) 'Invalid interaction anchor record.'
  _Interaction-Point $Record.source_point;_Interaction-Point $Record.screen_point
  _Interaction-Point $Record.normalized_window_point -Normalized;_Interaction-Point $Record.visible_normalized_point -Normalized
}
function _Interaction-ValidateEffect($Effect,$State) {
  _Execution-Fields $Effect @('kind','name','argv','data','live','quiet','brief','confirm_sensitive')
  _Execution-Require ($Effect.kind -is [string] -and $Effect.name -is [string] -and $Effect.argv -is [array] -and
    @($Effect.argv|Where-Object {$_ -isnot [string]}).Count -eq 0 -and $Effect.live -is [bool] -and $Effect.quiet -is [bool] -and
    $Effect.brief -is [bool] -and $Effect.confirm_sensitive -is [bool]) 'Malformed interaction effect descriptor.'
  _Execution-Require (-not $Effect.live -or $State.live) 'Effect exceeds immutable live startup authority.'
  _Execution-Require (-not $Effect.confirm_sensitive -or $State.sensitive) 'Effect exceeds immutable sensitive startup authority.'
  _Execution-Require (-not $Effect.quiet -and -not $Effect.brief -and -not $Effect.confirm_sensitive) 'Unexpected interaction effect options.'
  # The shared validator decodes exactly once before this closed family hook.
  $kind=$Effect.kind;$n=$Effect.name;$a=[string[]]$Effect.argv;$d=$Effect.data
  _Execution-Require ($kind -cin @('Native','Appshot','Win32Windows','UIAffordances','Cucp','Vision','HitTestPoint','PointCacheRead','PointCacheWrite','CoordProfile','AnchorScore','AnchorAppend','Notice','PipelineOutput','ObservationId','TrajectoryAppend','Clock','Timestamp','Sleep','Console')) 'Unknown interaction effect.'
  $allowedKinds=switch -CaseSensitive ($State.operation) {
    'find-label' {@('Clock','Timestamp','Win32Windows','Appshot')}
    'icon-find' {@('Clock','Timestamp','UIAffordances')}
    'click-label' {@('Clock','Timestamp','UIAffordances','Appshot','Notice','Vision','Cucp','TrajectoryAppend','PipelineOutput')}
    'icon-click' {@('Clock','Timestamp','UIAffordances','Appshot','ObservationId','Cucp')}
    'safe-type' {@('Native')}
    'ocr-click' {@('Native','TrajectoryAppend','Console')}
    'click-point' {@('Clock','Timestamp','HitTestPoint','PointCacheRead','PointCacheWrite','CoordProfile','AnchorScore','AnchorAppend','Native','TrajectoryAppend','Console')}
    'precision-validate' {@('Clock','Native','Sleep')}
    default {throw 'Unknown interaction startup operation.'}
  }
  _Execution-Require ($kind -cin $allowedKinds) 'Effect is outside the selected interaction operation.'
  if($kind -notin @('Native','Cucp')){_Execution-Require (-not $Effect.live) 'Unexpected live interaction effect.'}
  if($kind -notin @('Native','Cucp')){_Execution-Require ($a.Count -eq 0) 'Unexpected interaction effect arguments.'}
  if($kind -notin @('Notice','ObservationId','TrajectoryAppend','Clock','Timestamp','Console')){_Execution-Require ($n -ceq '') 'Unexpected interaction effect name.'}
  switch -CaseSensitive ($kind) {
    'Native' {
      _Execution-Require ($n -ceq '' -and $null -eq $d -and $a.Count -ge 2 -and $a[0] -ceq '-Action') 'Invalid interaction native descriptor.'
      $action=$a[1]
      $actions=switch -CaseSensitive ($State.operation) {
        'safe-type' {@('windows','focus','click','type','shortcut')}
        'ocr-click' {@('ocr-find-text','click')}
        'click-point' {@('hit-scan','click')}
        'precision-validate' {@('hit-scan')}
        default {@()}
      }
      _Execution-Require ($action -cin $actions) 'Native action is outside the selected interaction operation.'
      $live=$action -cin @('focus','click','type','shortcut')
      _Execution-Require ($Effect.live -eq $live) 'Interaction native action/live classification mismatch.'
      $required=@();$allowed=@()
      switch -CaseSensitive ($action) {
        'windows' {}
        'focus' {$required=@('-WindowHwnd');$allowed=$required}
        'click' {$required=@('-X','-Y');$allowed=@('-X','-Y','-Button','-TargetMatch','-TargetHwnd','-ClickRefine','-ClickInset')}
        'type' {$required=@('-Text','-TargetHwnd');$allowed=$required}
        'shortcut' {$required=@('-Keys','-TargetHwnd');$allowed=$required}
        'ocr-find-text' {$required=@('-OcrText','-OcrMatch','-OcrMaxCandidates');$allowed=@('-OcrText','-OcrMatch','-OcrMaxCandidates','-OcrLanguage','-Match','-ScreenshotX','-ScreenshotY','-ScreenshotW','-ScreenshotH')}
        'hit-scan' {$required=@('-X','-Y','-ScanRadius','-ScanStep');$allowed=@('-X','-Y','-ClickInset','-ScanRadius','-ScanStep','-TargetMatch','-TargetHwnd')}
        default {throw 'Native action is outside interaction planning.'}
      }
      $seen=_Interaction-Arguments -Argv $a -Start 2 -Allowed $allowed -Required $required
      if($action -ceq 'shortcut'){_Execution-Require ($seen['-Keys'] -cin @('enter','ctrl+enter')) 'Unexpected interaction submit shortcut.'}
      if($action -ceq 'ocr-find-text'){
        _Execution-Require ($seen['-OcrMaxCandidates'] -ceq '8') 'Unexpected interaction OCR candidate count.'
        $count=@(@('-ScreenshotX','-ScreenshotY','-ScreenshotW','-ScreenshotH')|Where-Object {$seen.ContainsKey($_)}).Count
        _Execution-Require ($count -in @(0,4)) 'Incomplete interaction OCR region.'
      }
    }
    'Cucp' {
      _Execution-Require ($n -ceq '' -and $null -eq $d -and $Effect.live -and $a.Count -ge 2 -and $a[0] -ceq 'act' -and $a[1] -cin @('click','right-click')) 'Invalid interaction core action.'
      $actArgs=_Interaction-Arguments -Argv $a -Start 2 -Allowed @('--x','--y','--after','--target-window') -Required @('--x','--y','--after')
      _Execution-Require ($null -ne $State.interaction_observations -and $State.interaction_observations.Contains([string]$actArgs['--after'])) 'Interaction action observation was not acquired by this session.'
    }
    'Appshot' {_Execution-Fields $d @('match','semantic','no_cache');_Execution-Require ($d.match -is [string] -and $d.semantic -is [bool] -and $d.semantic -and $d.no_cache -is [bool]) 'Invalid interaction appshot.'}
    'Win32Windows' {_Execution-Fields $d @('match');_Execution-Require ($d.match -is [string]) 'Invalid interaction window enumeration.'}
    'UIAffordances' {_Execution-Fields $d @('focused_window','max_elements');_Execution-Require ($d.focused_window -is [string] -and (_Interaction-Integer $d.max_elements) -and $d.max_elements -eq 800) 'Invalid interaction UIA acquisition.'}
    'Vision' {
      _Execution-Fields $d @('screenshot_path','description');_Execution-Require ($d.screenshot_path -is [string] -and $d.description -is [string]) 'Invalid interaction vision acquisition.'
      _Execution-Require ($null -ne $State.interaction_screenshots -and $State.interaction_screenshots.Contains([string]$d.screenshot_path)) 'Interaction vision screenshot was not acquired by this session.'
    }
    'HitTestPoint' {_Execution-Fields $d @('x','y','target_hwnd','target_match');_Execution-Require ((_Interaction-Integer $d.x) -and (_Interaction-Integer $d.y) -and (_Interaction-Integer $d.target_hwnd) -and $d.target_match -is [string]) 'Invalid interaction hit-test.'}
    'PointCacheRead' {_Execution-Fields $d @('key','max_age_seconds');_Execution-Require ($d.key -is [string] -and $d.key -cmatch '\A[a-f0-9]{32}\z' -and (_Interaction-Integer $d.max_age_seconds) -and $d.max_age_seconds -gt 0) 'Invalid interaction cache read.'}
    'PointCacheWrite' {
      _Execution-Fields $d @('key','payload');_Execution-Require ($d.key -is [string] -and $d.key -cmatch '\A[a-f0-9]{32}\z') 'Invalid interaction cache write key.'
      _Execution-Require ($null -ne $State.interaction_cache_keys -and $State.interaction_cache_keys.Contains([string]$d.key)) 'Interaction cache write has no matching queried key.'
      _Execution-Fields $d.payload @('schema','status','mode','source','x','y','radius','step','click_inset','target_hwnd','target_match','from_cache','cache_ttl_seconds','cache_key','confidence','safe_to_act','mouse_moved','reason','precheck','best','recommended_point','recommended_command','checks','scan')
      _Execution-Require ($d.payload.schema -ceq 'cucp.point-plan/v1' -and $d.payload.status -ceq 'ok' -and $d.payload.mode -ceq 'coordinate_click' -and $d.payload.source -ceq 'click_point_micro_refine' -and $d.payload.cache_key -ceq $d.key) 'Invalid interaction cache write payload.'
      foreach($field in @('x','y','radius','step','click_inset','target_hwnd','cache_ttl_seconds')){_Execution-Require (_Interaction-Integer $d.payload.$field) 'Invalid numeric interaction cache field.'}
      _Execution-Require ((_Interaction-Text $d.payload.target_match) -and $d.payload.from_cache -is [bool] -and -not $d.payload.from_cache -and
        $d.payload.safe_to_act -is [bool] -and $d.payload.safe_to_act -and $d.payload.mouse_moved -is [bool] -and $d.payload.mouse_moved -and
        $d.payload.reason -ceq '' -and $d.payload.confidence -is [string] -and $null -eq $d.payload.recommended_command -and
        $d.payload.checks -is [array] -and $d.payload.checks.Count -eq 2) 'Invalid interaction cache evidence.'
    }
    'CoordProfile' {_Execution-Fields $d @('has_point','x','y','target_hwnd','target_match');_Execution-Require ($d.has_point -is [bool] -and $d.has_point -and (_Interaction-Integer $d.x) -and (_Interaction-Integer $d.y) -and (_Interaction-Integer $d.target_hwnd) -and $d.target_match -is [string]) 'Invalid interaction coordinate profile.'}
    'AnchorScore' {_Execution-Fields $d @('record');_Interaction-Record $d.record}
    'AnchorAppend' {
      _Execution-Fields $d @('record');_Interaction-Record $d.record
      $recordKey=ConvertTo-Json -InputObject $d.record -Depth 100 -Compress
      _Execution-Require ($null -ne $State.interaction_anchor_records -and $State.interaction_anchor_records.Contains([string]$recordKey)) 'Interaction anchor append has no matching scored record.'
    }
    'Notice' {_Execution-Require ($n -cin @('WARN','ERROR') -and $d -is [string]) 'Invalid interaction notice.'}
    'PipelineOutput' {_Execution-Require ($d -is [string]) 'Invalid interaction pipeline output.'}
    'ObservationId' {_Execution-Require ($n -ceq 'icon-click' -and $null -eq $d) 'Invalid interaction observation identifier.'}
    'TrajectoryAppend' {
      _Execution-Require ($n -ceq 'click') 'Invalid interaction trajectory kind.'
      if($null -eq $d.source){_Execution-Fields $d @('label','window','role','x','y','observation_id','exit','double','right')}
      else {switch -CaseSensitive ($d.source) {
        'icon_find_fallback' {_Execution-Fields $d @('label','window','source','confidence','x','y','rect_w','rect_h','observation_id','exit')}
        'vision_fallback' {_Execution-Fields $d @('label','window','source','confidence','x','y','observation_id','exit')}
        'ocr_click' {_Execution-Fields $d @('source','x','y','button','text','matched_text','score','exit')}
        'native_click_point' {
          if($d.reason -ceq 'fast_guard_mismatch'){_Execution-Fields $d @('source','x','y','button','target_match','target_hwnd','exit','reason')}
          elseif($d.reason -ceq 'micro_refine_failed'){_Execution-Fields $d @('source','x','y','button','target_match','target_hwnd','refine','exit','reason')}
          else {_Execution-Fields $d @('source','x','y','button','target_match','target_hwnd','refine','micro_refine','auto_micro_refine','anchor_reuse','exit')}
        }
        default {throw 'Invalid interaction trajectory source.'}
      }}
    }
    'Clock' {_Execution-Require ($n -cin @('start','stop','elapsed') -and $d -is [string] -and $d -cin @('find-label','icon-find','click-point-precheck','precision-validate')) 'Invalid interaction clock.'}
    'Timestamp' {_Execution-Require ($n -ceq 'o' -and $null -eq $d) 'Invalid interaction timestamp.'}
    'Sleep' {_Execution-Require ($n -ceq '' -and (_Interaction-Integer $d) -and $d -eq 30) 'Invalid interaction precision delay.'}
    'Console' {_Execution-Require ($n -ceq 'write' -and $d -is [string]) 'Invalid interaction raw console output.'}
  }
}

function _Interaction-Dispatch($Effect,$State) {
  $a=[string[]]$Effect.argv;$d=$Effect.data;$n=$Effect.name
  switch -CaseSensitive ($Effect.kind) {
    'Native' {return ,(Invoke-NativeHelper -ArgList $a)}
    'Cucp' {return ,(Invoke-Cucp -ArgList $a)}
    'Appshot' {
      $shot=Invoke-Appshot -Match $d.match -Semantic:([bool]$d.semantic) -NoCache:([bool]$d.no_cache)
      if($shot){[void]$State.interaction_observations.Add([string]$shot.ObservationId);[void]$State.interaction_screenshots.Add([string]$shot.ScreenshotPath)}
      return ,$shot
    }
    'Win32Windows' {return ,(_Enumerate-Win32Windows -Match $d.match)}
    'UIAffordances' {return ,(_Get-UIAffordances -FocusedWindow $d.focused_window -MaxElements ([int]$d.max_elements))}
    'Vision' {return ,(_Invoke-CodexVision -ScreenshotPath $d.screenshot_path -Description $d.description)}
    'HitTestPoint' {return ,(_Native-HitTestPoint -X ([int]$d.x) -Y ([int]$d.y) -TargetHwnd ([int]$d.target_hwnd) -TargetMatch $d.target_match)}
    'PointCacheRead' {
      $hit=_PointPlan-ReadCache -Key $d.key -MaxAgeSeconds ([int]$d.max_age_seconds)
      [void]$State.interaction_cache_keys.Add([string]$d.key)
      return ,$hit
    }
    'PointCacheWrite' {_PointPlan-WriteCache -Key $d.key -Payload $d.payload;return}
    'CoordProfile' {return ,(_Build-CoordProfile -HasPoint ([bool]$d.has_point) -X ([int]$d.x) -Y ([int]$d.y) -TargetHwnd ([long]$d.target_hwnd) -TargetMatch $d.target_match)}
    'AnchorScore' {
      $recordKey=ConvertTo-Json -InputObject $d.record -Depth 100 -Compress
      $score=_AnchorHistory-Score -Record $d.record
      [void]$State.interaction_anchor_records.Add([string]$recordKey)
      return ,$score
    }
    'AnchorAppend' {return ,(_AnchorHistory-Append -Record $d.record)}
    'Notice' {Write-Notice -Level $n -Message $d;return}
    'PipelineOutput' {[void]$State.pipeline_output.Add([string]$d);return}
    'ObservationId' {
      $observation='icon-click-'+[guid]::NewGuid().ToString('N').Substring(0,12)
      [void]$State.interaction_observations.Add([string]$observation)
      return $observation
    }
    'TrajectoryAppend' {$payload=@{};foreach($p in $d.PSObject.Properties){$payload[$p.Name]=$p.Value};_Trajectory-Append -Kind $n -Payload $payload;return}
    'Clock' {
      if($n -ceq 'start'){$State.clocks[$d]=[Diagnostics.Stopwatch]::StartNew();return 0}
      if(-not $State.clocks.ContainsKey($d)){throw 'Interaction clock has not been started.'}
      if($n -ceq 'stop'){$State.clocks[$d].Stop()}
      return [int]$State.clocks[$d].Elapsed.TotalMilliseconds
    }
    'Timestamp' {return (Get-Date).ToString('o')}
    'Sleep' {Start-Sleep -Milliseconds ([int]$d);return}
    'Console' {[Console]::Out.Write([string]$d);return}
    default {throw 'Unknown interaction effect.'}
  }
}

function _Invoke-LegacyInteractionFamily {
  param([ValidateSet('find-label','click-point','click-label','safe-type','icon-find','icon-click','ocr-click','precision-validate')][string]$Operation,
    [string[]]$Rest,[string]$ScriptPath,[bool]$Double=$false,[bool]$RightClick=$false)
  $liveCeiling=[bool]$AllowLiveControl
  $sensitiveCeiling=[bool](_Read-StandaloneConfirmation -Rest $Rest)
  $startup=[ordered]@{schema='cucp.interaction-start/v1';operation=$Operation;rest=@($Rest);brief=[bool]$Brief;
    cache_seconds=[int]$CacheSeconds;vision_available=[bool]$Script:CliPath;culture=[Globalization.CultureInfo]::CurrentCulture.Name;
    double=[bool]$Double;right_click=[bool]$RightClick}
  $state=@{family='interaction';operation=$Operation;rest=@($Rest);live=$liveCeiling;sensitive=$sensitiveCeiling;
    script_path=$ScriptPath;cache_dir=$Script:CacheDir;paths=@{};clocks=@{};pipeline_output=(New-Object Collections.ArrayList);writer=$null;live_effect_seen=$false;
    interaction_observations=(New-Object Collections.ArrayList);interaction_screenshots=(New-Object Collections.ArrayList);
    interaction_cache_keys=(New-Object Collections.ArrayList);interaction_anchor_records=(New-Object Collections.ArrayList)}
  return _Invoke-LegacyExecutionHost -EntryPoint 'legacy-interaction-session' -Startup $startup -State $state
}

function Invoke-MacroFindLabel {param([string[]]$Rest) return _Invoke-LegacyInteractionFamily -Operation 'find-label' -Rest $Rest -ScriptPath $PSCommandPath}
function Invoke-MacroClickPoint {param([string[]]$Rest) return _Invoke-LegacyInteractionFamily -Operation 'click-point' -Rest $Rest -ScriptPath $PSCommandPath}
function Invoke-MacroClickLabel {param([string[]]$Rest,[switch]$Double,[switch]$RightClick) return _Invoke-LegacyInteractionFamily -Operation 'click-label' -Rest $Rest -ScriptPath $PSCommandPath -Double ([bool]$Double) -RightClick ([bool]$RightClick)}
function Invoke-MacroSafeType {param([string[]]$Rest) return _Invoke-LegacyInteractionFamily -Operation 'safe-type' -Rest $Rest -ScriptPath $PSCommandPath}
function Invoke-MacroIconFind {param([string[]]$Rest) return _Invoke-LegacyInteractionFamily -Operation 'icon-find' -Rest $Rest -ScriptPath $PSCommandPath}
function Invoke-MacroIconClick {param([string[]]$Rest) return _Invoke-LegacyInteractionFamily -Operation 'icon-click' -Rest $Rest -ScriptPath $PSCommandPath}
function Invoke-MacroOcrClick {param([string[]]$Rest) return _Invoke-LegacyInteractionFamily -Operation 'ocr-click' -Rest $Rest -ScriptPath $PSCommandPath}
function Invoke-MacroPrecisionValidate {param([string[]]$Rest) return _Invoke-LegacyInteractionFamily -Operation 'precision-validate' -Rest $Rest -ScriptPath $PSCommandPath}

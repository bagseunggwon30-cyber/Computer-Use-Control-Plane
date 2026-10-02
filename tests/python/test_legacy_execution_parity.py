"""Closed-effect execution coordination versus the pinned original PS5.1 source.

No captured command is executed. All native/input/process/history/clock/sleep seams
are replaced before evaluating the selected original function definitions.
"""
import copy
from functools import lru_cache
import itertools
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
BASELINE_TREE = "bf895d3120dd5e145f360cb1c41e1d79a061d048"
PROJECT = ROOT / "pcucp-next/dotnet/PcuCp.LegacyExecution.ContractTests"


def first_difference(actual, expected, path="$"):
    """Bounded failure context; equality assertions remain the qualification gate."""
    if type(actual) is not type(expected):
        return f"{path}: actual {type(actual).__name__}, expected {type(expected).__name__}"
    if isinstance(actual, dict):
        for key in expected:
            if key not in actual:return f"{path}.{key}: missing actual key"
            if actual[key] != expected[key]:return first_difference(actual[key], expected[key], f"{path}.{key}")
        for key in actual:
            if key not in expected:return f"{path}.{key}: unexpected actual key"
    elif isinstance(actual, list):
        if len(actual) != len(expected):return f"{path}: actual count {len(actual)}, expected {len(expected)}"
        for index, (left, right) in enumerate(zip(actual, expected)):
            if left != right:return first_difference(left, right, f"{path}[{index}]")
    elif actual != expected:
        return f"{path}: actual {repr(actual)[:256]}, expected {repr(expected)[:256]}"
    return None


def reply(value=None, exit=0, raw="captured 한글"):
    return dict(exit=exit, raw=raw, json=value)


def workflow(steps=1, live=False, safe=True, sensitive=False):
    return dict(safe_to_run=safe, step_count=steps, live_step_count=steps if live else 0,
                sensitive_step_count=steps if sensitive else 0, errors=[], steps=[dict(
                    index=i+1, macro="shortcut" if live else "windows", live_required=live,
                    command=["macro", "shortcut", "--keys", "F1"] if live else ["macro", "windows"],
                    requires_sensitive_confirmation=sensitive, safety=dict(risk_level="high", risk_score=65,
                    categories=[], recommended_action="confirm")) for i in range(steps)])


def form_plan(safe=True, count=2):
    return dict(safe_to_act=safe, safe_step_count=count, step_count=count, elapsed_ms=37,
                errors=[], unsafe_steps=[], command_plan=[dict(index=i+1, kind="field", label="Name", route="uia",
                safe_to_act=True, command=["macro", "uia-set-value", "--label", "Name", "--value", str(i)]) for i in range(count)])


def cases():
    result=[]
    def add(operation, rest=(), replies=(), **kw):
        result.append(dict(operation=operation, rest=list(rest), replies=copy.deepcopy(list(replies)), allow_live=True,
                           confirm_sensitive="--confirm-sensitive" in rest, **kw))
    for safe,dry,include in itertools.product((True,False),(True,False),(True,False)):
        rest=(["--dry-run"] if dry else [])+(["--include-plan"] if include else [])
        p=workflow(safe=safe); add("workflow-run",rest,[p]+([] if dry or not safe else [reply(dict(status="ok"))]))
        fp=form_plan(safe=safe); add("form-run",rest,[reply(fp)]+([] if dry or not safe else [reply(dict(status="ok"))]*2))
    for live,retry_live,verify,label,keep in itertools.product((False,True),(False,True),(False,True),(False,True),(False,True)):
        rest=["--retry-failed-step","2","--retry-delay-ms","17","--settle-ms","9","--include-plan"]
        if retry_live:rest += ["--retry-live-steps"]
        if verify:rest += ["--verify-after-step","--verify-match","W"]
        if label:rest += ["--verify-after-label","Done","--verify-label-window","Window"]
        if keep:rest += ["--continue-on-error"]
        replies=[workflow(2,live=live)]
        for _ in range(6):
            replies.append(reply(dict(status="partial",recoverable_errors=[dict(recommended_action="inspect fixture")]),exit=2))
            if verify:replies.append(reply(None,exit=7,raw="no window"))
            if label:replies.append(reply(None,exit=2,raw="no label"))
        add("workflow-run",rest,replies)
    for operation in ("workflow-run","task-run","form-run","recovery-run","smart-click"):
        for dry in (False,True):
            rest=["--dry-run"] if dry else []
            if operation=="smart-click":rest += ["--label","Name"]
            captures=[workflow(live=True)] if operation=="workflow-run" else [reply(dict(safe_to_run=True,live_step_count=1,recommended_command=["macro","workflow-run"],dry_run_command=["macro","workflow-run","--dry-run"])),reply(dict(status="ready"))] if operation=="task-run" else [reply(form_plan())] if operation=="form-run" else [reply(None)]
            add(operation,rest,captures);result[-1]["allow_live"]=False
    for operation in ("task-run","form-run"):
        for value in (None,False,[],[False],{},dict(safe_to_run=False,safe_to_act=False,errors=["bad"],unsafe_steps=[dict(index=3)])):
            add(operation,["--include-plan"],[reply(value,exit=2)])
    for safe,dry,child_exit,status in itertools.product((False,True),(False,True),(0,2,3),("ok","ready","partial")):
        p=dict(safe_to_run=safe,live_step_count=0,errors=[],recommended_command=["macro","workflow-run"],dry_run_command=["macro","workflow-run","--dry-run"])
        add("task-run",["--include-plan"]+(["--dry-run"] if dry else []),[reply(p),reply(dict(status=status,next_action="inspect",failure_summary=dict(index=1)),exit=child_exit)])
    for confirm in (False,True):
        add("workflow-run",["--confirm-sensitive"] if confirm else [],[workflow(live=True,sensitive=True),reply(dict(status="ok"))])
        p=form_plan(count=1);p["command_plan"][0].update(label="Submit",command=["macro","smart-click","--label","Submit"])
        add("form-run",["--confirm-sensitive"] if confirm else [],[reply(p),reply(dict(status="ok"))])
    for keep in (False,True):
        p=form_plan();p["command_plan"][0]["safe_to_act"]=False
        add("form-run",["--continue-on-error"] if keep else [],[reply(p),reply(None,exit=2)])
    for n in (1,3):
        for until in (False,True):
            rs=[]
            for i in range(n):
                rs.append(reply(dict(foreground=dict(title="W" if i<2 else "Other",hwnd=123 if i<2 else 456))))
                if until:rs.append(reply(dict(status="ok" if i==n-1 else "partial")))
            add("watch",["--max-cycles",str(n),"--interval-ms","3"]+(["--until-label","Done"] if until else []),rs)
    for score,modal in itertools.product((0,59,60,99,100),(False,True)):
        m=dict(candidate_count=1,modal_candidates=[dict(score=score,is_modal=modal,title="Modal",**{"class":"Dialog"})])
        add("recovery-plan",["--match","W","--failed-step","macro click-label --label Name","--failed-reason","fixture"],[reply(m),reply(dict(foreground={}))])
        for dry,confirm in itertools.product((False,True),(False,True)):
            add("recovery-run",(["--dry-run"] if dry else [])+(["--confirm-sensitive"] if confirm else []),[reply(m),None])
    for failure in ("native","escape"):
        add("recovery-run",["--confirm-sensitive"],[dict(throw="fixture failure")] if failure=="native" else [reply(dict(candidate_count=1,modal_candidates=[dict(is_modal=True)])),dict(throw="fixture failure")])
    for stage in ("uia","coord","precision","icon","fusion","fusion_coord","ocr","cdp","vision","hint","hint_fallback","low","none"):
        rest=["--label","Name","--match","Window","--role","Button"]
        history="uia_coord" if stage=="hint" else "unknown" if stage=="hint_fallback" else None
        rs=[history]
        if stage=="cdp":rest += ["--allow-cdp"];rs += [True,reply(dict(status="ok",matched_text="Name",score=99,tag_name="button"))]
        elif stage=="hint_fallback":rs += [reply(dict(status="ok",method="Invoke"))]
        else:
            if stage != "hint":rs += [reply(dict(status="ok",method="Invoke")) if stage=="uia" else reply(dict(status="partial",reason="low_confidence_match",score=20)) if stage=="low" else reply(dict(status="partial"))]
            if stage in ("coord","precision","icon","fusion_coord","ocr","hint"):
                rest += ["--allow-mouse-fallback"]
                if stage=="precision":rest += ["--precision-points"];rs += [reply(dict(status="ok",ambiguous=False,top=dict(click_point=dict(x=2,y=3)))),reply(dict(status="ok"))]
                else:
                    rs += [reply(dict(status="ok",x=2,y=3)) if stage in ("coord","hint") else reply(dict(status="partial"))]
                    if stage not in ("coord","hint"):
                        rs += [reply(dict(status="ok",top=dict(score=90,center=dict(x=5,y=6)))) if stage=="icon" else reply(dict(status="partial"))]
                        if stage=="icon":rs += [reply(dict(status="ok"))]
            if stage in ("fusion","fusion_coord","ocr","none","vision"):
                rs += [reply(dict(status="ok",method="Invoke",uia_name="Name")) if stage=="fusion" else reply(dict(status="partial",reason="no_invoke_pattern",fallback_coord=dict(x=8,y=9),ocr_score=80)) if stage=="fusion_coord" else reply(dict(status="partial"))]
                if stage=="fusion_coord":rs += [reply(dict(status="ok"))]
                if stage=="ocr":rs += [reply(dict(status="ok",top=dict(score=85,cx=3,cy=4,text="Name"))),reply(dict(status="ok"))]
                if stage=="vision":rest += ["--allow-vision"];rs += [reply(None)]
        add("smart-click",rest,rs,vision_available=True)
    # Screen verification preserves partial outcomes and explicit retry count.
    for changed,retry in itertools.product((False,True),(0,2)):
        rest=["--label","Name","--verify-screen-changed","--retry-on-no-change",str(retry)]
        rs=[None,reply(dict(foreground=dict(rect=dict(x=1,y=2,width=30,height=40)))),reply(dict(status="ok")),reply(dict(status="ok",method="Invoke")),reply(dict(status="ok")),reply(dict(status="ok",changed=changed,changed_ratio=0.2))]
        if not changed:
            for _ in range(retry):rs += [reply(dict(status="ok")),reply(dict(status="ok")),reply(dict(status="ok")),reply(dict(status="ok",changed=False,changed_ratio=0))]
        add("smart-click",rest,rs)
    for operation,option in (("workflow-run","--settle-ms"),("watch","--max-cycles"),("smart-click","--verify-timeout-ms")):
        for value in ("bad"," ","2147483648","1.5","0x10"):
            rs=[workflow(),reply(None)] if operation=="workflow-run" else [reply(None)]*30 if operation=="watch" else [None,reply(dict(status="ok"))]
            add(operation,["--label","Name",option,value],rs)
    # Fail individual effects without performing them. Later inert replies keep
    # legacy fallback branches observable after a caught acquisition failure.
    seeds=[next(c for c in result if c["operation"]==operation and len(c["replies"])>=minimum)
           for operation,minimum in (("workflow-run",4),("task-run",2),("form-run",3),("watch",6),("recovery-plan",2),("smart-click",6))]
    for seed in seeds:
        for index in range(min(6,len(seed["replies"]))):
            f=copy.deepcopy(seed);f["replies"][index]={"throw":"captured effect failure"}
            f["replies"] += [reply(None,exit=2)]*24;result.append(f)
    for command in (None,[],[None],"macro",["macro","windows"],["macro","windows","--match","-AllowLiveControl"]):
        p=dict(safe_to_run=True,live_step_count=0,errors=[],recommended_command=command,dry_run_command=command)
        add("task-run",["--include-plan"],[reply(p),reply(None,exit=2)])
    for c in copy.deepcopy(result):c["brief"]=True;result.append(c)
    return result


@lru_cache(maxsize=1)
def built_candidate():
    dotnet=os.environ.get("DOTNET") or shutil.which("dotnet")
    if not dotnet:raise unittest.SkipTest("dotnet SDK not available")
    dll=PROJECT/"bin/Release/net8.0/PcuCp.LegacyExecution.ContractTests.dll"
    # Rebuild once per test process; an existing DLL can predate source edits.
    subprocess.run([dotnet,"build",str(PROJECT),"-c","Release"],check=True,capture_output=True,timeout=180)
    return dotnet,dll


def captured_failure_effects(fixture, effects):
    """Bind thrown fixture replies to the original captured effect, in order.

    Non-reply effects never advance the reply cursor. Startup permission and
    command text are deliberately not used to infer whether a live call happened.
    """
    no_reply={"Sleep","TrajectoryAppend","HistoryAppend","RemoveFile","Console"}
    failures=[];reply_index=0
    for trace_index,effect in enumerate(effects):
        if effect["kind"] in no_reply:continue
        if reply_index<len(fixture["replies"]):
            captured=fixture["replies"][reply_index]
            if isinstance(captured,dict) and "throw" in captured:
                failures.append(dict(trace_index=trace_index,reply_index=reply_index,effect=effect,message=captured["throw"]))
        reply_index+=1
    return failures


def contains_uncertainty(value):
    if isinstance(value,dict):
        return value.get("mutation_may_have_occurred") is True or any(contains_uncertainty(v) for v in value.values())
    return isinstance(value,list) and any(contains_uncertainty(v) for v in value)


def run_candidate(fixtures):
    dotnet,dll=built_candidate()
    p=subprocess.run([dotnet,str(dll),"--fixtures"],input=json.dumps(fixtures).encode(),capture_output=True,timeout=120)
    if p.returncode:raise AssertionError(p.stderr.decode(errors="replace"))
    return json.loads(p.stdout)


class ExecutionPortableTests(unittest.TestCase):
    def test_first_difference_reports_nested_path_without_dumping_large_payload(self):
        self.assertIsNone(first_difference({"effects":[]},{"effects":[]}))
        self.assertEqual(first_difference({"effects":[{"live":False}]},{"effects":[{"live":True}]}),
                         "$.effects[0].live: actual False, expected True")
        self.assertEqual(first_difference({},{"payload":{"secret":"not printed"}}),"$.payload: missing actual key")
        self.assertLess(len(first_difference("a"*100000,"b"*100000)),600)

    def test_all_family_corpus_is_closed(self):
        cs=cases();self.assertGreaterEqual(len(cs),400)
        self.assertEqual({c["operation"] for c in cs},{"workflow-run","task-run","form-run","smart-click","watch","recovery-plan","recovery-run"})
        for p in (PROJECT.parent/"PcuCp.LegacyExecution").glob("*.cs"):
            text=p.read_text()
            for token in ("Process.Start(","ProcessStartInfo","DllImport","System.Management.Automation","File.Read","File.Write","SendKeys"):
                self.assertNotIn(token,text,str(p))
    def test_portable_corpus(self):
        fixtures=cases();actual=run_candidate(fixtures)
        self.assertEqual(len(actual),len(fixtures))
        for f,r in zip(fixtures,actual):
            with self.subTest(operation=f["operation"],rest=f["rest"]):
                self.assertNotIn("Fixture exhausted",r.get("error",""))
                if not f["allow_live"]:self.assertFalse(any(e["live"] for e in r["effects"]))
                if r["state"]=="complete":self.assertIn(r["exit"],(0,1,2,3))
    def test_failure_partition_uses_captured_dispatch_not_startup_permission(self):
        fixtures=cases();captured=run_candidate(fixtures)
        non_live=live=post_live_read=unreached=0
        for fixture,result in zip(fixtures,captured):
            if not any(isinstance(r,dict) and "throw" in r for r in fixture["replies"]):continue
            failures=captured_failure_effects(fixture,result["effects"])
            if not failures:unreached+=1;continue
            for failure in failures:
                prefix=result["effects"][:failure["trace_index"]+1]
                if failure["effect"]["live"]:live+=1
                elif any(e["live"] for e in prefix):post_live_read+=1
                else:non_live+=1
        self.assertGreater(non_live,0);self.assertGreater(live,0);self.assertGreater(post_live_read,0)
        self.assertEqual(non_live+live+post_live_read+unreached,
                         sum(any(isinstance(r,dict) and "throw" in r for r in f["replies"]) for f in fixtures))

    def test_large_workflow_preserves_256_steps_six_attempts_and_large_payload(self):
        f=dict(operation="workflow-run",rest=["--continue-on-error","--retry-failed-step","5"],allow_live=False,
               replies=[workflow(256)]+[reply(dict(status="partial",blob="x"*1024),exit=2)]*(256*6))
        r=run_candidate([f])[0]
        self.assertEqual(r["state"],"complete");self.assertEqual(r["consumed"],1537)
        self.assertEqual(r["payload"]["executed_count"],256);self.assertEqual(r["payload"]["retry_count"],1280)
        self.assertTrue(all(len(s["attempts"])==6 for s in r["payload"]["steps"]))
        self.assertGreater(len(json.dumps(r["payload"])),1048576)
    def test_control_like_data_never_grants_authority_or_changes_named_options(self):
        p=workflow();p["steps"][0]["command"]=["macro","windows","--match","-AllowLiveControl","-Brief","-CucpArgs","--confirm-sensitive"]
        f=dict(operation="workflow-run",rest=[],allow_live=False,confirm_sensitive=False,replies=[p,reply(dict(status="ok"))])
        r=run_candidate([f])[0]; child=next(e for e in r["effects"] if e["kind"]=="Child")
        self.assertEqual(child["argv"],p["steps"][0]["command"]);self.assertFalse(child["live"]);self.assertFalse(child["brief"]);self.assertFalse(child["confirm_sensitive"])
    def test_runtime_object_shape_is_never_unwrapped(self):
        shape={"value":["preserve"],"Count":1}
        r=run_candidate([dict(operation="workflow-run",rest=[],allow_live=False,replies=[workflow(),reply(shape)])])[0]
        self.assertEqual(r["payload"]["steps"][0]["result"],shape)
        self.assertEqual(r["payload"]["steps"][0]["attempts"][0]["result"],shape)


def decode_wire(value):
    if value["kind"]=="scalar":return value["value"]
    if value["kind"]=="array":return [decode_wire(x) for x in value["items"]]
    return {x["name"]:decode_wire(x["value"]) for x in value["properties"]}


@unittest.skipUnless(sys.platform=="win32","Windows PowerShell 5.1 differential qualification")
class ExecutionWindowsParityTests(unittest.TestCase):
    # Keep all assertions/subtests; bound only unittest's textual diff output.
    maxDiff=1200
    def test_original_payload_effect_order_errors_exits_and_console(self):
        fixtures=cases();actual=run_candidate(fixtures)
        with tempfile.TemporaryDirectory(prefix="CUCP execution 한글 ") as temp:
            d=Path(temp);source=d/"original.ps1";inputs=d/"cases.json";runner=d/"capture.ps1"
            source.write_bytes(subprocess.check_output(["git","show",f"{BASELINE_TREE}:scripts/cucp.ps1"],cwd=ROOT))
            inputs.write_text(json.dumps(fixtures),encoding="utf-8-sig");runner.write_text(PS_CAPTURE,encoding="utf-8-sig")
            ps=shutil.which("powershell.exe")
            p=subprocess.run([ps,"-NoProfile","-NonInteractive","-File",str(runner),"-Source",str(source),"-InputPath",str(inputs)],capture_output=True,timeout=240)
            self.assertEqual(p.returncode,0,p.stderr.decode(errors="replace"));baseline=json.loads(p.stdout.decode("utf-8-sig"))
            self.assertEqual(len(baseline),len(fixtures))
            render=[]
            for index,(f,old,new) in enumerate(zip(fixtures,baseline,actual)):
                with self.subTest(case=index,operation=f["operation"],rest=f["rest"],brief=f.get("brief")):
                    self.assertEqual(new["state"],old["state"])
                    self.assertEqual(new["effects"],decode_wire(old["effects"]))
                    self.assertEqual(new["consumed"],old["consumed"])
                    if new["state"]=="error":self.assertEqual(new["error"],old["error"])
                    else:
                        self.assertEqual(new["exit"],old["exit"])
                        if old["payload"] is not None:self.assertEqual(new["payload"],decode_wire(old["payload"]))
                        render.append(dict(result=new,expected=old["console"]))
            ri=d/"render.json";rs=d/"render.ps1";ri.write_text(json.dumps(render),encoding="utf-8-sig");rs.write_text(PS_RENDER,encoding="utf-8-sig")
            p=subprocess.run([ps,"-NoProfile","-NonInteractive","-File",str(rs),"-InputPath",str(ri)],capture_output=True,timeout=120)
            self.assertEqual(p.returncode,0,p.stderr.decode(errors="replace"));rendered=json.loads(p.stdout.decode("utf-8-sig"))
            self.assertEqual(len(rendered),len(render))
            for value,original in zip(rendered,render):self.assertEqual(value,original["expected"])

    @unittest.skipUnless(bool(os.environ.get("CUCP_EXECUTION_TEST_HOST")), "Actual execution family adapter is not enabled")
    def test_actual_session_adapter_matches_original_payload_console_and_effects(self):
        fixtures=cases()
        with tempfile.TemporaryDirectory(prefix="CUCP actual execution 한글 ") as temp:
            d=Path(temp);source=d/"original.ps1";inputs=d/"cases.json";runner=d/"capture.ps1"
            source.write_bytes(subprocess.check_output(["git","show",f"{BASELINE_TREE}:scripts/cucp.ps1"],cwd=ROOT))
            inputs.write_text(json.dumps(fixtures),encoding="utf-8-sig");runner.write_text(PS_CAPTURE,encoding="utf-8-sig")
            command=[shutil.which("powershell.exe"),"-NoProfile","-NonInteractive","-File",str(runner),"-Source",str(source),"-InputPath",str(inputs)]
            original=subprocess.run(command,capture_output=True,timeout=240)
            self.assertEqual(original.returncode,0,original.stderr.decode(errors="replace"))
            adapted=subprocess.run(command+["-AdapterSource",os.environ.get("CUCP_EXECUTION_ADAPTER_SOURCE",str(ROOT/"scripts/cucp.ps1")),"-BridgeSource",str(ROOT/"scripts/cucp.ps1")],
                env={**os.environ,"CUCP_NATIVE_HOST":os.environ["CUCP_EXECUTION_TEST_HOST"],"CUCP_EXECUTION_DIAGNOSTICS":"1"},capture_output=True,timeout=600)
            if adapted.stderr:
                print("Execution adapter diagnostics (first 16 KiB):\n"+adapted.stderr.decode("utf-8-sig",errors="replace")[:16384],flush=True)
            self.assertEqual(adapted.returncode,0,adapted.stderr.decode(errors="replace"))
            old=json.loads(original.stdout.decode("utf-8-sig"));new=json.loads(adapted.stdout.decode("utf-8-sig"))
            self.assertEqual(len(old),len(fixtures));self.assertEqual(len(new),len(fixtures))
            def unbrief_key(fixture):
                return json.dumps({k:v for k,v in fixture.items() if k!="brief"},sort_keys=True)
            unbrief_results={unbrief_key(f):r for f,r in zip(fixtures,new) if not f.get("brief")}
            exact_failures=0;uncertain_failures=0;diagnostic_shown=False
            for index,(fixture,before,after) in enumerate(zip(fixtures,old,new)):
                with self.subTest(case=index,operation=fixture["operation"],rest=fixture["rest"],brief=fixture.get("brief")):
                    original_effects=decode_wire(before["effects"])
                    failures=captured_failure_effects(fixture,original_effects)
                    # Any earlier live dispatch is relevant too: losing a later
                    # observation must not erase an already dispatched mutation.
                    uncertain=next((failure for failure in failures if any(
                        e["live"] for e in original_effects[:failure["trace_index"]+1])),None)
                    if uncertain is None:
                        # Includes every captured failure before a live dispatch,
                        # plus fixture throws that the original never reached.
                        if after != before and not diagnostic_shown:
                            diagnostic_shown=True
                            print(f"First exact adapter mismatch, case {index}, {fixture['operation']}: "+str(first_difference(after,before))+
                                  "; actual error="+str(after.get("error",""))[:1024],flush=True)
                        self.assertEqual(after,before)
                        exact_failures+=bool(failures)
                        continue
                    uncertain_failures+=1
                    index=uncertain["trace_index"];failed=uncertain["effect"]
                    actual_effects=decode_wire(after["effects"])
                    self.assertEqual(actual_effects[:index+1],original_effects[:index+1])
                    self.assertEqual(after["consumed"],uncertain["reply_index"]+1)
                    # Reporting the partial outcome is allowed; another child,
                    # observation, input, sleep, cleanup or history action isn't.
                    self.assertTrue(all(e["kind"]=="TrajectoryAppend" and not e["live"]
                                        for e in actual_effects[index+1:]),actual_effects[index+1:])
                    if failed["live"]:
                        self.assertIn(failed["kind"],("Child","Native","LocalMacro","SendEscape"))
                        self.assertEqual(after["state"],"complete");self.assertEqual(after["exit"],2)
                        # Brief mode intentionally emits no JSON; its identical
                        # non-brief capture proves the underlying uncertainty data.
                        report_row=unbrief_results[unbrief_key(fixture)] if fixture.get("brief") else after
                        self.assertIsNotNone(report_row["payload"])
                        report=decode_wire(report_row["payload"])
                        self.assertEqual(report["status"],"partial");self.assertTrue(contains_uncertainty(report))
                        if fixture.get("brief"):self.assertTrue(after["console"].startswith("partial "),after["console"])
                    else:
                        # The failing read followed a captured live action. The
                        # session's deliberate terminal-loss correction is exact.
                        self.assertEqual(after["state"],"error")
                        self.assertEqual(after["error"],"mutation_may_have_occurred=true; automatic_retry=false; "+uncertain["message"])
            self.assertGreater(exact_failures,0);self.assertGreater(uncertain_failures,0)
            print(f"Compared all {len(fixtures)} actual-adapter cases: {exact_failures} exact non-live failure cases and {uncertain_failures} explicit post-dispatch uncertainty cases")


PS_CAPTURE = r'''
param([string]$Source,[string]$InputPath,[string]$AdapterSource,[string]$BridgeSource)
$ErrorActionPreference='Stop';[Console]::OutputEncoding=New-Object Text.UTF8Encoding($false)
if($PSVersionTable.PSVersion.Major -ne 5 -or $PSVersionTable.PSVersion.Minor -ne 1){throw 'Expected Windows PowerShell 5.1'}
$tokens=$null;$errors=$null;$ast=[Management.Automation.Language.Parser]::ParseFile($Source,[ref]$tokens,[ref]$errors)
function Encode-Wire($Value) {
 if($null -eq $Value){return @{kind='scalar';value=$null}}
 if($Value -is [string] -or $Value -is [ValueType]){return @{kind='scalar';value=$Value}}
 if($Value -is [System.Collections.IDictionary]) {
  $pairs=@(foreach($key in $Value.Keys){@{name=[string]$key;value=(Encode-Wire $Value[$key])}})
  return @{kind='object';properties=$pairs}
 }
 if($Value -is [System.Collections.IEnumerable]) {
  $items=@(foreach($item in $Value){Encode-Wire $item})
  return @{kind='array';items=$items}
 }
 return @{kind='object';properties=@(foreach($p in $Value.PSObject.Properties){@{name=$p.Name;value=(Encode-Wire $p.Value)}})}
}
function Capture-Effect {
 param([string]$Kind,[string]$Name='', [string[]]$Argv=@(),$Data=$null,[bool]$Live=$false,[bool]$Quiet=$false,[bool]$Brief=$false,[bool]$Confirm=$false)
 [void]$script:trace.Add([ordered]@{kind=$Kind;name=$Name;argv=@($Argv);data=$Data;live=$Live;quiet=$Quiet;brief=$Brief;confirm_sensitive=$Confirm})
 if($Kind -in @('Sleep','TrajectoryAppend','HistoryAppend','RemoveFile')){return}
 if($Kind -eq 'Console'){[Console]::Out.WriteLine([string]$Data);return}
 if($script:cursor -ge $script:fixture.replies.Count){throw "Fixture exhausted at ${Kind}:$Name"}
 $value=$script:fixture.replies[$script:cursor];$script:cursor++
 if($value -and $value.PSObject.Properties['throw']){throw $value.throw}
 Write-Output -NoEnumerate $value
}
function Capture-Child {
 param([string[]]$Argv)
 $quiet=$false;$live=$false;$brief=$false;$i=0
 while($i -lt $Argv.Count -and $Argv[$i] -in @('-Quiet','-AllowLiveControl','-Brief')) {
  switch($Argv[$i]){'-Quiet'{$quiet=$true};'-AllowLiveControl'{$live=$true};'-Brief'{$brief=$true}};$i++
 }
 $cmd=@();if($i -lt $Argv.Count){$cmd=@($Argv[$i..($Argv.Count-1)])}
 $confirm=$live -and ($cmd -contains '--confirm-sensitive')
 Capture-Effect 'Child' -Argv $cmd -Live $live -Quiet $quiet -Brief $brief -Confirm $confirm
}
function Invoke-CapturedDirect {
 param([string[]]$Argv,[switch]$Live,[switch]$Quiet,[switch]$Brief)
 $r=Capture-Effect 'Child' -Name 'direct' -Argv $Argv -Live ([bool]$Live) -Quiet ([bool]$Quiet) -Brief ([bool]$Brief)
 $global:LASTEXITCODE=[int]$r.exit
 return $r.raw
}
function New-FakeStopwatch {
 $v=[pscustomobject]@{Elapsed=[pscustomobject]@{TotalMilliseconds=37}}
 $v|Add-Member ScriptMethod Stop {};return $v
}
function Invoke-NativeHelper {
 param([string[]]$ArgList)
 $live=$ArgList[1] -in @('uia-invoke','uia-click','click','ocr-uia-invoke','cdp-smart-click')
 Capture-Effect 'Native' -Argv $ArgList -Live $live
}
function _Build-WorkflowPlan {param([string[]]$Rest) Capture-Effect 'WorkflowPlan' -Argv $Rest}
function Start-Sleep {param([int]$Milliseconds) Capture-Effect 'Sleep' -Data $Milliseconds}
function Get-Date {return [DateTime]::Parse('2026-10-02T00:00:00.0000000Z').ToUniversalTime()}
function Test-Path {param([string]$LiteralPath,[string]$PathType) if($PathType -eq 'Leaf'){return Microsoft.PowerShell.Management\Test-Path -LiteralPath $LiteralPath -PathType Leaf};Capture-Effect 'FileExists' -Data $LiteralPath}
function Remove-Item {param([string]$LiteralPath,[switch]$Force,[string]$ErrorAction) Capture-Effect 'RemoveFile' -Data $LiteralPath}
function _History-PickBestStrategy {param($Label,$Match,$LookbackN) Capture-Effect 'HistoryRead' -Argv @("$Label","$Match","$LookbackN")}
function _History-Append {param($Label,$Match,$Strategy,$Success,$ElapsedMs) Capture-Effect 'HistoryAppend' -Argv @("$Label","$Match","$Strategy") -Data ([ordered]@{success=[bool]$Success;elapsed_ms=[int]$ElapsedMs})}
function _Trajectory-Append {param($Kind,$Payload) Capture-Effect 'TrajectoryAppend' -Name $Kind -Data $Payload}
function Test-CdpPortQuick {param($Port,$TimeoutMs) Capture-Effect 'CdpPort' -Argv @("$Port","$TimeoutMs")}
function Invoke-MacroClickPoint {param([string[]]$Rest) $r=Capture-Effect 'LocalMacro' -Name 'click-point' -Argv $Rest -Live $true;[Console]::Out.WriteLine($r.raw);return [int]$r.exit}
function Invoke-MacroIconFind {param([string[]]$Rest) $r=Capture-Effect 'LocalMacro' -Name 'icon-find' -Argv $Rest;[Console]::Out.WriteLine((Microsoft.PowerShell.Utility\ConvertTo-Json -InputObject $r.json -Depth 64));return [int]$r.exit}
function ConvertTo-Json {
 [CmdletBinding()]param([Parameter(ValueFromPipeline=$true)]$InputObject,[int]$Depth=2,[switch]$Compress)
 process{if($InputObject -and $InputObject.PSObject.Properties['schema'] -and $InputObject.schema -in @('cucp.workflow-run/v1','cucp.task-run/v1','cucp.form-run/v1','cucp.smart-click/v1','cucp.watch/v1','cucp.recovery-plan/v1','cucp.recovery-run/v1')){$script:payload=Encode-Wire $InputObject};Microsoft.PowerShell.Utility\ConvertTo-Json -InputObject $InputObject -Depth $Depth -Compress:$Compress}
}
$names=@('_Read-OptValue','_Read-Switch','_Safety-Truncate','_Classify-SafetyFromText','Invoke-MacroWorkflowRun','Invoke-MacroTaskRun','Invoke-MacroFormRun','Invoke-MacroSmartClick','Invoke-MacroWatch','Invoke-MacroRecoveryPlan','Invoke-MacroRecoveryRun')
foreach($name in $names){
 $fn=@($ast.FindAll({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq $name},$true))
 if($fn.Count -ne 1){throw "Expected one original function: $name"};$text=$fn[0].Extent.Text
 $nested=@($fn[0].FindAll({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -in @('_InvokeWorkflowChild','_InvokeTaskRunChildJson','_InvokeSelfJson')},$true))
 foreach($n in ($nested|Sort-Object {$_.Extent.StartOffset} -Descending)){
  $replacement='function '+$n.Name+' {param([string[]]$ChildArgs) Capture-Child -Argv $ChildArgs}'
  $offset=$n.Extent.StartOffset-$fn[0].Extent.StartOffset;$text=$text.Remove($offset,$n.Extent.Text.Length).Insert($offset,$replacement)
 }
 $text=$text.Replace('[System.Diagnostics.Stopwatch]::StartNew()','(New-FakeStopwatch)')
 $text=$text.Replace('& $PSCommandPath -AllowLiveControl -Quiet -Brief @vargs','Invoke-CapturedDirect -Argv $vargs -Live -Quiet -Brief')
 $text=$text.Replace('& $PSCommandPath @waitArgs','Invoke-CapturedDirect -Argv $waitArgs')
 $text=$text.Replace('Add-Type -AssemblyName System.Windows.Forms -ErrorAction Stop','$null = Capture-Effect ''SendEscape'' -Live $true -Confirm $true')
 $text=$text.Replace('[System.Windows.Forms.SendKeys]::SendWait("{ESC}")','$null = $null')
 # Capture Console effect order for branches whose output precedes history, and
 # for watch's incremental lines; all other output is still the original Console.
 if($name -eq 'Invoke-MacroWatch'){$text=$text.Replace('[Console]::Out.WriteLine($line)','Capture-Effect ''Console'' -Data $line')}
 if($name -eq 'Invoke-MacroSmartClick'){
  $text=$text.Replace('[Console]::Out.WriteLine("partial smart-click ''$label'' low_confidence score=$($r1.Json.score) strategy=stopped")','Capture-Effect ''Console'' -Data "partial smart-click ''$label'' low_confidence score=$($r1.Json.score) strategy=stopped"')
  $text=$text.Replace('[Console]::Out.WriteLine("partial smart-click ''$label'' all_strategies_failed allow_vision=$allowVision allow_mouse=$allowMouseFallback")','Capture-Effect ''Console'' -Data "partial smart-click ''$label'' all_strategies_failed allow_vision=$allowVision allow_mouse=$allowMouseFallback"')
 }
 if($text.Contains('& powershell') -or $text.Contains('& $PSCommandPath') -or $text.Contains('SendKeys]::')){throw "Unintercepted effect in $name"}
 . ([scriptblock]::Create($text))
}
if($AdapterSource){
 $bt=$null;$be=$null;$ba=[Management.Automation.Language.Parser]::ParseFile($BridgeSource,[ref]$bt,[ref]$be)
 if($be.Count){throw 'Central startup bridge did not parse'}
 foreach($name in @('_Read-StandaloneConfirmation','_Invoke-LegacyCompatibility')){
  $df=@($ba.FindAll({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq $name},$true))
  if($df.Count -ne 1){throw "Missing central startup function $name"};. ([scriptblock]::Create($df[0].Extent.Text))
 }
 $at=$null;$ae=$null;$aa=[Management.Automation.Language.Parser]::ParseFile($AdapterSource,[ref]$at,[ref]$ae)
 if($ae.Count){throw 'Execution adapter source did not parse'}
 $public=@('Invoke-MacroWorkflowRun','Invoke-MacroTaskRun','Invoke-MacroFormRun','Invoke-MacroSmartClick','Invoke-MacroWatch','Invoke-MacroRecoveryPlan','Invoke-MacroRecoveryRun')
 $defs=@($aa.FindAll({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst] -and ($n.Name -like '_Execution-*' -or $n.Name -like '_Invoke-LegacyExecution*' -or $n.Name -in $public)},$true))
 foreach($def in $defs){
  $body=$def.Extent.Text
  if($def.Name -eq '_Execution-Dispatch'){$body=$body.Replace('[Diagnostics.Stopwatch]::StartNew()','(New-FakeStopwatch)')}
  . ([scriptblock]::Create($body))
 }
 # Only the child process boundary is captured; session framing, descriptor
 # validation, closed dispatch and original public wrappers execute unchanged.
 function _Invoke-LegacyExecutionChild {
  param([string]$ScriptPath,$Effect,[bool]$LiveCeiling,[bool]$SensitiveCeiling,[switch]$SensitiveCeilingContractVerified)
  Capture-Effect 'Child' -Name $Effect.name -Argv $Effect.argv -Live ([bool]$Effect.live) -Quiet ([bool]$Effect.quiet) -Brief ([bool]$Effect.brief) -Confirm ([bool]$Effect.confirm_sensitive)
 }
}
$Script:CucpV14Schema=@{RecoveryPlan='cucp.recovery-plan/v1';RecoveryRun='cucp.recovery-run/v1'};$Script:CacheDir='C:\fixture'
$all=New-Object Collections.ArrayList
foreach($fixture in (Get-Content -LiteralPath $InputPath -Raw -Encoding UTF8|ConvertFrom-Json)){
 $script:fixture=$fixture;$script:trace=New-Object Collections.ArrayList;$script:cursor=0;$script:payload=$null
 $AllowLiveControl=[bool]$fixture.allow_live;$Brief=[bool]$fixture.brief;$CacheSeconds=5;$Script:CliPath=if($fixture.vision_available){'fixture'}else{$null}
 $writer=New-Object IO.StringWriter;$old=[Console]::Out;[Console]::SetOut($writer)
 try {
  $function=switch($fixture.operation){'workflow-run'{'Invoke-MacroWorkflowRun'};'task-run'{'Invoke-MacroTaskRun'};'form-run'{'Invoke-MacroFormRun'};'smart-click'{'Invoke-MacroSmartClick'};'watch'{'Invoke-MacroWatch'};'recovery-plan'{'Invoke-MacroRecoveryPlan'};'recovery-run'{'Invoke-MacroRecoveryRun'}}
  $exit=& $function -Rest $fixture.rest
  $r=@{state='complete';payload=$script:payload;exit=[int]$exit;effects=(Encode-Wire @($script:trace));consumed=$script:cursor;console=$writer.ToString()}
 }catch{$r=@{state='error';error=$_.Exception.Message;effects=(Encode-Wire @($script:trace));consumed=$script:cursor;console=$writer.ToString()}}
 finally{[Console]::SetOut($old);$writer.Dispose()}
 [void]$all.Add($r)
}
[Console]::Out.WriteLine((Microsoft.PowerShell.Utility\ConvertTo-Json -InputObject @($all) -Depth 100 -Compress))
'''

PS_RENDER = r'''
param([string]$InputPath)
$ErrorActionPreference='Stop';[Console]::OutputEncoding=New-Object Text.UTF8Encoding($false)
$all=New-Object Collections.ArrayList
foreach($f in (Get-Content -LiteralPath $InputPath -Raw -Encoding UTF8|ConvertFrom-Json)){
 $r=$f.result;$writer=New-Object IO.StringWriter
 foreach($line in @($r.console)){$writer.WriteLine([string]$line)}
 if($r.emit_json){$writer.WriteLine((ConvertTo-Json -InputObject $r.payload -Depth $r.json_depth))}
 [void]$all.Add($writer.ToString());$writer.Dispose()
}
[Console]::Out.WriteLine((ConvertTo-Json -InputObject @($all) -Depth 100 -Compress))
'''

if __name__=="__main__":unittest.main()

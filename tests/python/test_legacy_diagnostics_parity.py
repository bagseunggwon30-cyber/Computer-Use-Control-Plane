"""Finite, captured-only diagnostic assembly qualification.

The accepted source retains the benchmark all-samples-success safety correction.
No process, model, desktop, cleanup, or user-document operation is executed.
"""
import copy
import hashlib
from functools import lru_cache
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
BASELINE_TREE = "bf895d3120dd5e145f360cb1c41e1d79a061d048"
ACCEPTED_TREE = "c0d15371b60ebf62be45bfa68b90282405f07273"
PROJECT = ROOT / "pcucp-next/dotnet/PcuCp.LegacyDiagnostics.ContractTests"
FILE_OPERATIONS = {"audit-summary", "log-tail", "release-notes"}
BODY_HASHES = {
    "Perf": (10249,"ff9b17550327cfeae75e047d388b78846a7142615c9195534c229fa9cd699d41"),
    "DiagnoseLag": (9513,"bd3b42f4601fc80cd783aaacabd56c6c0fa462d8a384e570ef8b8b615ba0c0d4"),
    "HealthQuick": (4713,"ee8b4ce78342737a7860a9af3ca39eb34fcc6a883088a42cdc598faa044a6b90"),
    "HealthDetail": (3146,"825f7d1eb36c7f0d6a5aa9938dccde46a2b784c90de6ea79b76918c79df6662d"),
    "LogTail": (6862,"efbec3d5647e6cbf4c3886d301794ae5cea5c901d07d92c5e2d25c1bcb9c6762"),
    "Benchmark": (5389,"dc9424001a488623f7ba7b7c7cd96bc794cc008ec94e0a3f8335c36435320dd7"),
    "SelfTest": (7094,"4d4249654b27111adb5b5c7c76755a3e6915c9fe4d514b5d12fbeac9f7714632"),
    "AuditSummary": (2728,"4450f8211f04b7b3c86cea782029e755b82c7568b0354cc923482a9a5a2caa05"),
    "ReleaseNotes": (4359,"17c09c39f14c78309fb9d2dda49c89e0cee6438459fce16e5bf06545fcfd4536"),
}


# One transparent compatibility display string is data, not an engine reference.
# This exact declaration is the sole exemption; all old dependency checks still
# scan the remainder and reflection/type-loading routes are denied separately.
DIAGNOSTIC_DISPLAY_DECLARATION = '    private const string CustomObjectDisplayType = "System.Management.Automation.PSCustomObject";'
DIAGNOSTIC_TYPE_LOADING_TOKENS = ('Type.GetType(', '.GetType(', 'Assembly.Load',
    'System.Reflection', 'Activator.CreateInstance', 'GetTypeInfo(', 'GetManifestResourceStream(')


def diagnostic_dependency_source(name, source):
    if name == 'LegacyDiagnosticJson.cs':
        if source.count(DIAGNOSTIC_DISPLAY_DECLARATION) != 1:
            raise AssertionError('Expected one exact inert diagnostic display-name declaration')
        source = source.replace(DIAGNOSTIC_DISPLAY_DECLARATION, '', 1)
    for token in DIAGNOSTIC_TYPE_LOADING_TOKENS:
        if token in source:
            raise AssertionError('Diagnostic type loading is forbidden: ' + token)
    return source


def reply(status="ok", exit=0, **fields):
    return dict(exit=exit, json=dict(status=status, **fields))


def cases():
    result=[]
    def add(operation, rest=(), replies=(), **kw):
        replies=copy.deepcopy(list(replies))
        if operation=="diagnose-lag":
            first,second=replies[:2];by_id={p["id"]:p for p in first};metrics=[]
            groups=[{"codex"},{"electron","code","cursor","windsurf"},{"node"},{"powershell","pwsh"},{"chrome","msedge","brave","whale"},{"cucp-helper","windows-mcp-helper"}]
            for group in groups:
                for current in second:
                    if current["name"].lower() not in group:continue
                    value={k:current[k] for k in ("private_bytes","started_at","priority") if k in current}
                    previous=by_id.get(current["id"])
                    if previous is not None and "cpu_ms" in current and "cpu_ms" in previous:value.update(current_cpu_ms=current["cpu_ms"],previous_cpu_ms=previous["cpu_ms"])
                    metrics.append(value)
            replies[:2]=[[{k:p[k] for k in ("id","name")} for p in snapshot] for snapshot in (first,second)]
            replies[3:3]=metrics
        result.append(dict(operation=operation,rest=list(rest),replies=replies,**kw))
    for quick in (True,False):
        for cold in (True,False):
            for iters in (1,2):
                targets=[("cli",0),("cli",0),("macro",0),("macro",1),("macro",0),("macro",2),("macro",2)]
                if not quick:targets += [("cli",0),("macro",0),("cli",0),("cli",0),("cli",2),("macro",2)]
                rs=[reply(exit=exit) if kind=="cli" else exit for kind,exit in targets for _ in range(iters)]
                if cold:rs += [None]+[reply() for _ in range(iters*2)]
                add("perf",["--iters",str(iters)]+(["--quick"] if quick else [])+(["--include-live-ish"] if cold else []),rs,clocks=[801,9001,5001,1001,999,501,802]*10)
    for iters in ("1","2","10","0","11","bad",""):
        count=3 if iters in ("bad","") else max(1,min(10,int(iters)))
        for mixed in (True,False):
            rs=[reply() for _ in range(count*4)]
            if mixed:rs[0]=reply(exit=1)
            add("benchmark",["--iters",iters],rs,clocks=[10,40,30,20,700,80,2,4,6,800]*4)
    for threshold in (536870911,536870912,2147483647):
        add("perf",["--iters","1","--quick","--warn-fast-ms",str(threshold)],
            [reply(),reply(),0,1,0,2,2],clocks=[17,18,19,20,21,22,23])
    base=dict(results=[dict(name="windows",p50_ms=100,p95_ms=200),dict(name="health",p50_ms=5,p95_ms=5),dict(name="focused",p50_ms=None)])
    for raw in (json.dumps(base),"{}","{broken"):
        add("benchmark",["--iters","1","--baseline","C:\\fixture\\baseline.json"],[reply()]*4+[True,raw])
    for node in (True,False):
        for optional in (True,False):
            add("health-detail",[],[dict(exit=0 if node else 1,output=" v22.0.0 "),True,reply(version="1.8.0"),optional,optional,"codex.cmd" if optional else None,None])
            add("health-quick",[],[dict(exit=0 if node else 1,output=" v22.0.0 "),True,None,True,True,[dict(length=1)]*(1001 if optional else 1),True,[],True,dict(length=67108865 if optional else 1),True,dict(text="TIMEOUT\n"*(6 if optional else 1))])
    add("health-quick",[],[dict(exit=0,output="v1"),None,True,False,False,False,False],context=dict(cli_path=""))
    add("health-quick",[],[dict(exit=0,output="v1"),None,True,False,False,False,False],context=dict(cli_path=None))
    add("health-detail",[],[dict(exit=0,output="v1"),reply(version="1"),False,False,None,None],context=dict(cli_path=None))
    for deep in (True,False):
        for strict in (True,False):
            for helper in (True,False):
                rs=[dict(throw="blocked gate"),dict(throw="missing observation"),reply(version="1"),reply() if helper else reply(status="partial",exit=2)]
                if helper:rs += [reply(),{},"key",True,dict(FromCache=True)]
                if deep:rs += [[dict(name="button")]]+([dict(ObservationId="o1",Affordances=[dict(name="button")])] if helper else [])
                add("self-test",(["--deep"] if deep else [])+(["--strict"] if strict else []),rs)
    for blocked in (True,False):
        add("self-test",[],[blocked,blocked,reply(version="1"),reply(status="partial",exit=2)])
    for sample in ("0","1","3000","9000"):
        first=[dict(id=1,name="Code",private_bytes=100,started_at="2026-10-01T23:59:00Z",cpu_ms=100,priority="Normal"),dict(id=2,name="node",cpu_ms=400)]
        second=[dict(id=1,name="Code",private_bytes=9*1024**3,started_at="2026-10-01T23:59:00Z",cpu_ms=10000,priority="Normal"),dict(id=2,name="node",private_bytes=200,cpu_ms=200,priority=""),dict(id=3,name="node",private_bytes=300,priority="Idle")]
        add("diagnose-lag",["--sample-ms",sample],[first,second,4,[dict(foreground=True,title="fixture 한국어")],True,[dict(length=1)]*1001,True,[],True,dict(length=67108865),True,dict(text="TIMEOUT Timeout TIMEOUT")])
    add("diagnose-lag",[],[[],[],0,[],False,False])
    add("diagnose-lag",[],[[],[dict(id=9,name="node",started_at="2026-10-01T23:00:00-07:00",private_bytes=None,priority="")],1,[],False,False])
    add("diagnose-lag",["--sample-ms","1000"],[[dict(id=5,name="node",cpu_ms=None)],[dict(id=5,name="node",cpu_ms=100,priority="Normal")],1,[],False,False])
    add("diagnose-lag",[],[[],[dict(id=i,name="chrome",private_bytes=1,priority="Normal") for i in range(26)],1,[],False,False])
    audit_lines=[json.dumps(dict(ts="2026-10-01T23:59:00Z",macro="click",exit_code=0,sensitive=True)),json.dumps(dict(ts="2026-10-01T20:00:00Z",macro="CLICK",exit_code=3,status="blocked")),"malformed",json.dumps(dict(ts="invalid",action="type",reason="not-sensitive")),"",json.dumps(dict(action="windows"))]
    for rest in ([],["--since-minutes","30"],["--since-minutes","bad"],["--since-minutes","-10"]):
        add("audit-summary",rest,[True,[dict(full_name="a",last_write_time="2026-10-02T00:00:00Z")],audit_lines])
    add("audit-summary",[],[False]);add("audit-summary",[],[True,[]])
    add("audit-summary",[],[True,[dict(full_name="a",last_write_time="2026-10-02T00:00:00Z")],['{"macro":"one","Macro":"two"}','{"macro":"one","macro":"two"}']])
    tails=["", "INFO one\nERROR password=not-real token=not-real\nTIMEOUT\n", "a\rb\r\nc\n", "ERROR secret=x\ninfo\n", "throw a\nexit 124\nerror lower\n"]
    for text in tails:
        for extra in ([],["--errors-only"],["--lines","1"],["--max-bytes","5"]):
            limit=5 if "--max-bytes" in extra else 262144; data=text.encode()[-limit:].decode(errors="replace")
            add("log-tail",extra,[True,dict(total_bytes=len(text.encode()),tail_bytes=min(limit,len(text.encode())),text=data)])
    add("log-tail",[],[False]);add("log-tail",["--path","C:\\fixture\\missing.log"],[False])
    changelog=["# ignored","## v2.0.0","### Added","- Alpha","- token sk-"+"a"*24,"### Improved","- Faster","### Fixed","- Bug","## 1.0.0","### added","- lowercase","### Limits","- hidden","## v0.9.0","### Added","- Old"]
    for opts in ([],["--version","1.0.0"],["--version","9.9.9"],["--since","1.0.0"],["--since","1"],["--since","x.y.z"]):
        add("release-notes",opts,["C:\\fixture\\CHANGELOG.md",changelog])
    add("release-notes",[],[None]);add("release-notes",[],["C:\\fixture\\CHANGELOG.md",[]])
    # Every declared throw is injected at a reached reply in an otherwise coherent
    # seed, so swallowed acquisition failure and terminal error branches are tested.
    for operation in ("perf","benchmark","health-quick","health-detail","self-test","diagnose-lag","audit-summary","log-tail","release-notes"):
        seed=next(f for f in result if f["operation"]==operation)
        for index in range(min(8,len(seed["replies"]))):
            f=copy.deepcopy(seed);f["replies"][index]=dict(throw="captured diagnostic failure");f["failure_index"]=index;result.append(f)
    for operation,option in (("perf","--iters"),("diagnose-lag","--sample-ms"),("log-tail","--lines")):
        for value in ("bad","2147483648","1.5","0x10"):
            seed=copy.deepcopy(next(f for f in result if f["operation"]==operation));seed["rest"]=[option,value]+(["--quick"] if operation=="perf" else []);seed["replies"]*=20;result.append(seed)
    original=copy.deepcopy(result)
    for f in original:f["brief"]=True;result.append(f)
    for operation in ("perf","health-quick","health-detail","diagnose-lag","audit-summary","log-tail","self-test","benchmark","release-notes"):
        f=copy.deepcopy(next(f for f in result if f["operation"]==operation));f["brief"]=True;f["rest"] += ["--json-only"];result.append(f)
    # Append source-derived boundary characterizations without changing any of
    # the original 321 case identities or assertions.
    add("audit-summary",[],[True,[dict(full_name="date-fixture",last_write_time="2026-10-02T00:00:00Z")],
        [r'{"ts":"\/Date(0)\/","macro":"date"}']])
    metadata=dict(__type="inert-fixture",__Type="retained-member",results=[dict(name="windows",p50_ms=100,p95_ms=200)])
    add("benchmark",["--iters","1","--baseline",r"C:\fixture\baseline.json"],[reply()]*4+[True,json.dumps(metadata)])
    return result

@lru_cache(maxsize=1)
def built_candidate():
    dotnet=os.environ.get("DOTNET") or shutil.which("dotnet")
    if not dotnet:raise unittest.SkipTest("dotnet SDK not available")
    subprocess.run([dotnet,"build",str(PROJECT),"-c","Release"],check=True,capture_output=True,timeout=180)
    return dotnet,PROJECT/"bin/Release/net8.0/PcuCp.LegacyDiagnostics.ContractTests.dll"

def run_candidate(fixtures):
    dotnet,dll=built_candidate()
    p=subprocess.run([dotnet,str(dll),"--fixtures"],input=json.dumps(fixtures).encode(),capture_output=True,timeout=120)
    if p.returncode:raise AssertionError(p.stderr.decode(errors="replace"))
    return json.loads(p.stdout)

def decode_wire(value):
    if value["kind"]=="scalar":return value["value"]
    if value["kind"]=="array":return [decode_wire(v) for v in value["items"]]
    return {v["name"]:decode_wire(v["value"]) for v in value["properties"]}

class DiagnosticPortableTests(unittest.TestCase):
    def test_windows_observed_json_error_and_duplicate_semantics(self):
        # Exact PS5 results observed at d8bde03d in run 37048150884. Keep the
        # unchanged Windows differential cases as the independent oracle too.
        fixtures=cases()
        malformed,duplicates=run_candidate([fixtures[27],fixtures[63]])
        self.assertEqual(malformed['state'],'complete')
        self.assertEqual(malformed['payload']['baseline_compare']['detail'],
            "Invalid object passed in, ':' or '}' expected. (7): {broken")
        self.assertEqual(duplicates['state'],'complete')
        self.assertEqual(duplicates['payload']['event_count'],1)
        self.assertEqual(duplicates['payload']['by_macro'],{'two':1})
    def test_pinned_accepted_body_footprint(self):
        source=subprocess.check_output(["git","show",f"{ACCEPTED_TREE}:scripts/cucp.ps1"],cwd=ROOT).decode("utf-8")
        for name,(size,digest) in BODY_HASHES.items():
            start=re.search(r"^function Invoke-Macro"+name+r" \{",source,re.M).start()
            end=source.index("\n}",start)+2;body=source[start:end].encode("utf-8")
            self.assertEqual(len(body),size,name);self.assertEqual(hashlib.sha256(body).hexdigest(),digest,name)
        self.assertEqual(sum(size for size,_ in BODY_HASHES.values()),54053)
    def test_closed_nine_operation_corpus(self):
        fixtures=cases();self.assertGreater(len(fixtures),200)
        self.assertEqual({f["operation"] for f in fixtures},{"perf","benchmark","health-quick","health-detail","self-test","diagnose-lag","audit-summary","log-tail","release-notes"})
        for source in (PROJECT.parent/"PcuCp.LegacyDiagnostics").glob("*.cs"):
            text = diagnostic_dependency_source(source.name, source.read_text(encoding="utf-8-sig"))
            for token in ("Process.Start(","ProcessStartInfo","File.Read","File.Write","DllImport","SendKeys","Management.Automation"):
                self.assertNotIn(token,text,str(source))
    def test_portable_corpus_and_failure_reachability(self):
        fixtures=cases();actual=run_candidate(fixtures)
        self.assertEqual(len(actual),len(fixtures))
        for index,(f,r) in enumerate(zip(fixtures,actual)):
            with self.subTest(index=index,operation=f["operation"],rest=f["rest"]):
                self.assertNotIn("Fixture exhausted",r.get("error",""))
                if "failure_index" in f:self.assertGreater(r["consumed"],f["failure_index"])
                if r["state"]=="complete":self.assertIn(r["exit"],(0,1,2))
    def test_owned_maintenance_descriptors(self):
        for f,r in zip(cases(),run_candidate(cases())):
            for e in r["effects"]:
                if e["kind"]=="ClearAppshotCache":
                    self.assertEqual(f["operation"],"perf");self.assertIn("--include-live-ish",f["rest"])
                    self.assertEqual(e["name"],"appshot-*.json");self.assertEqual(e["data"],"C:\\fixture\\cache")
                if e["kind"]=="AuditProbe":
                    self.assertIn(f["operation"],("health-quick","health-detail"));self.assertEqual(e["data"],"C:\\fixture\\audit")
    def test_managed_contracts(self):
        dotnet,dll=built_candidate();p=subprocess.run([dotnet,str(dll),"--self-test"],capture_output=True,timeout=120)
        self.assertEqual(p.returncode,0,p.stderr.decode(errors="replace"));self.assertIn("diagnostic managed contracts",p.stdout.decode())
    def test_sample_math_advisory_status_and_historical_quirks(self):
        fixtures=cases();actual=run_candidate(fixtures)
        pairs=list(zip(fixtures,actual))
        cold=next(r for f,r in pairs if f["operation"]=="perf" and f["rest"]==["--iters","2","--quick","--include-live-ish"] and not f.get("brief"))
        self.assertEqual([t["iters"] for t in cold["payload"]["targets"][-2:]],[2,2])
        self.assertEqual(sum(e["kind"]=="ClearAppshotCache" for e in cold["effects"]),1)
        lag=next(r for f,r in pairs if f["operation"]=="diagnose-lag" and f["rest"]==["--sample-ms","1"] and not f.get("brief"))
        process=lag["payload"]["processes"]
        self.assertEqual(process[0]["cpu_delta_pct"],247500)
        self.assertEqual(process[1]["cpu_delta_pct"],0)
        self.assertEqual(process[0]["pids"],1);self.assertEqual(process[1]["pids"],[2,3])
        self.assertEqual([e["kind"] for e in lag["effects"][:5]],["Clock","Processes","Sleep","Processes","Timestamp"])
        health=next(r for f,r in pairs if f["operation"]=="health-quick" and not f.get("brief") and r["state"]=="complete" and r["payload"]["components"]["recent_timeouts"]["count"]==6)
        self.assertEqual(health["exit"],0);self.assertFalse(health["payload"]["components"]["temp_pressure"]["ok"])
        strict=next(r for f,r in pairs if f["operation"]=="self-test" and f["rest"]==["--strict"] and not f.get("brief") and r["payload"]["skipped"]>0)
        self.assertEqual(strict["exit"],1);self.assertEqual(strict["payload"]["failed"],0)
        age=next(r for f,r in pairs if f["operation"]=="diagnose-lag" and any(isinstance(v,dict) and v.get("started_at")=="2026-10-01T23:00:00-07:00" for v in f["replies"]) and not f.get("brief"))
        self.assertEqual(age["payload"]["processes"][0]["oldest_age_sec"],3600)
        nullable=next(r for f,r in pairs if f["operation"]=="diagnose-lag" and f["rest"]==["--sample-ms","1000"] and not f.get("brief"))
        self.assertEqual(nullable["payload"]["processes"][0]["cpu_delta_pct"],10)
        for f,r in pairs:
            if f["operation"] in ("health-quick","health-detail") and f.get("context",{}).get("cli_path","sentinel") is None and r["state"]=="complete":
                self.assertIsNone(r["payload"]["components"]["cli"]["path"])
    def test_slo_fail_threshold_conversion_follows_all_samples(self):
        selected=[f for f in cases() if f["operation"]=="perf" and "--warn-fast-ms" in f["rest"] and not f.get("brief")]
        self.assertEqual(len(selected),3)
        for fixture,result in zip(selected,run_candidate(selected)):
            threshold=int(fixture["rest"][-1])
            self.assertEqual(result["consumed"],7)
            self.assertEqual(sum(e["kind"]=="Clock" and e["name"]=="stop" for e in result["effects"]),7)
            if threshold==536870911:
                self.assertEqual(result["state"],"complete")
                self.assertEqual(result["payload"]["slo"][0]["fail_ms"],2147483644)
            else:
                self.assertEqual(result["state"],"error")
                self.assertEqual(result["effects"][-1]["kind"],"Clock")
                self.assertEqual(result["error"],f'Cannot process argument transformation on parameter \'FailMs\'. Cannot convert value "{threshold*4}" to type "System.Int32". Error: "Value was either too large or too small for an Int32."')

@unittest.skipUnless(sys.platform=="win32","Windows PowerShell 5.1 pinned differential qualification")
class DiagnosticWindowsParityTests(unittest.TestCase):
    maxDiff=1500
    def test_all_nine_payload_effect_order_console_errors_and_exits(self):
        fixtures=cases();actual=run_candidate(fixtures)
        with tempfile.TemporaryDirectory(prefix="CUCP diagnostics 한국어 ") as temporary:
            temp=Path(temporary);source=temp/"original.ps1";inputs=temp/"cases.json"
            source.write_bytes(subprocess.check_output(["git","show",f"{ACCEPTED_TREE}:scripts/cucp.ps1"],cwd=ROOT))
            inputs.write_text(json.dumps(fixtures),encoding="utf-8-sig")
            original=[None]*len(fixtures)
            for file_group in (True,False):
                selected=[(i,f) for i,f in enumerate(fixtures) if (f["operation"] in FILE_OPERATIONS)==file_group]
                inputs.write_text(json.dumps([f for _,f in selected]),encoding="utf-8-sig")
                runner=ROOT/("tests/fixtures/legacy-diagnostics-file-oracle.ps1" if file_group else "tests/fixtures/legacy-diagnostics-runtime-oracle.ps1")
                process=subprocess.run([shutil.which("powershell.exe"),"-NoProfile","-NonInteractive","-File",str(runner),"-Source",str(source),"-InputPath",str(inputs)],capture_output=True,timeout=240)
                self.assertEqual(process.returncode,0,process.stderr.decode(errors="replace"));group=json.loads(process.stdout.decode("utf-8-sig"))
                self.assertEqual(len(group),len(selected))
                for (index,_),record in zip(selected,group):original[index]=record
            self.assertEqual(len(original),len(fixtures));render=[]
            for index,(fixture,before,after) in enumerate(zip(fixtures,original,actual)):
                with self.subTest(index=index,operation=fixture["operation"],rest=fixture["rest"]):
                    self.assertEqual(after["state"],before["state"])
                    self.assertEqual(after["effects"],decode_wire(before["effects"]))
                    self.assertEqual(after["consumed"],before["consumed"])
                    if after["state"]=="error":self.assertEqual(after["error"],before["error"])
                    else:
                        self.assertEqual(after["exit"],before["exit"])
                        if before["payload"] is not None:self.assertEqual(after["payload"],decode_wire(before["payload"]))
                        render.append(dict(result={**after,"console":([after["brief"]] if after["brief"] is not None else [])},expected=before["console"]))
            # Use the same PS Console serializer to retain its raw formatting.
            from test_legacy_execution_parity import PS_RENDER
            PS_RENDER=PS_RENDER.replace('if($r.emit_json){', '''if(@($r.hashtable_paths).Count -eq 2 -and $r.hashtable_paths[0] -eq "by_macro" -and $r.hashtable_paths[1] -eq "by_exit_code") {
 foreach($field in @("by_macro","by_exit_code")) { $map=@{};foreach($p in $r.payload.$field.PSObject.Properties){$map[$p.Name]=0;$map[$p.Name]=$p.Value};$r.payload.$field=$map }
}
if(@($r.hashtable_paths).Count -eq 1 -and $r.hashtable_paths[0] -eq "processes.*.priority_classes") {
 foreach($process in @($r.payload.processes)) { $map=@{};foreach($p in $process.priority_classes.PSObject.Properties){$map[$p.Name]=$p.Value};$process.priority_classes=$map }
}
if($r.emit_json){''')
            path=temp/"render.json";script=temp/"render.ps1";path.write_text(json.dumps(render),encoding="utf-8-sig");script.write_text(PS_RENDER,encoding="utf-8-sig")
            process=subprocess.run([shutil.which("powershell.exe"),"-NoProfile","-NonInteractive","-File",str(script),"-InputPath",str(path)],capture_output=True,timeout=120)
            self.assertEqual(process.returncode,0,process.stderr.decode(errors="replace"))
            for rendered,expected in zip(json.loads(process.stdout.decode("utf-8-sig")),render):self.assertEqual(rendered,expected["expected"])

if __name__=="__main__":unittest.main()

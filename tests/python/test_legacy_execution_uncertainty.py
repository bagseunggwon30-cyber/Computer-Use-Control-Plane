"""Intentional safety correction: uncertain mutation never starts another action."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from test_legacy_execution_parity import ROOT, BASELINE_TREE, PS_CAPTURE, reply, workflow, form_plan, run_candidate, decode_wire


def uncertain(status="partial", exit=2):
    return reply(dict(status=status,reason="cdp_bridge_failed",mutation_may_have_occurred=True),exit=exit)


class ExecutionUncertaintyTests(unittest.TestCase):
    def test_smart_cdp_uncertainty_stops_before_uia_fallback(self):
        f=dict(operation="smart-click",rest=["--label","Name","--allow-cdp"],allow_live=True,
               replies=[None,True,uncertain(),reply(dict(status="ok",method="Invoke"))])
        r=run_candidate([f])[0]
        self.assertEqual(r["exit"],2);self.assertEqual(r["consumed"],3)
        self.assertTrue(r["payload"]["mutation_may_have_occurred"])
        self.assertEqual([e["argv"][1] for e in r["effects"] if e["kind"]=="Native"],["cdp-smart-click"])
        self.assertFalse(any(e["kind"]=="HistoryAppend" for e in r["effects"]))
    def test_uncertain_success_status_cannot_hide_native_mutation(self):
        r=run_candidate([dict(operation="smart-click",rest=["--label","Name","--allow-mouse-fallback"],allow_live=True,
                            replies=[None,uncertain("ok",0)])])[0]
        self.assertEqual(r["exit"],2);self.assertEqual(r["consumed"],2)
        self.assertEqual(r["payload"]["reason"],"mutation_may_have_occurred")
    def test_post_dispatch_native_exception_stops_without_fallback(self):
        r=run_candidate([dict(operation="smart-click",rest=["--label","Name","--allow-mouse-fallback"],allow_live=True,
                            replies=[None,dict(throw="transport closed after input",mutation_may_have_occurred=True)])])[0]
        self.assertEqual(r["exit"],2);self.assertEqual(r["consumed"],2)
        self.assertEqual(r["payload"]["result"]["detail"],"transport closed after input")
    def test_workflow_does_not_retry_uncertain_action_or_continue_to_next_step(self):
        f=dict(operation="workflow-run",rest=["--retry-failed-step","5","--retry-live-steps","--continue-on-error","--verify-after-step","--settle-ms","50"],
               allow_live=True,replies=[workflow(2,live=True),uncertain("ok",0)])
        r=run_candidate([f])[0];p=r["payload"]
        self.assertEqual(r["exit"],2);self.assertEqual(r["consumed"],2)
        self.assertEqual(p["executed_count"],1);self.assertEqual(p["failed_count"],1);self.assertEqual(p["retry_count"],0)
        self.assertEqual(p["failure_summary"]["failure_kind"],"mutation_may_have_occurred")
        self.assertEqual(len([e for e in r["effects"] if e["kind"]=="Child"]),1)
        self.assertFalse(any(e["kind"]=="Sleep" for e in r["effects"]))
    def test_form_uncertainty_stops_continue_on_error(self):
        r=run_candidate([dict(operation="form-run",rest=["--continue-on-error"],allow_live=True,
                            replies=[reply(form_plan()),uncertain("ok",0)])])[0]
        self.assertEqual(r["exit"],2);self.assertEqual(r["payload"]["executed_count"],1)
        self.assertEqual(r["payload"]["failed_count"],1);self.assertEqual(r["consumed"],2)
        self.assertEqual(r["payload"]["steps"][0]["reason"],"mutation_may_have_occurred")
    def test_task_uncertain_child_is_partial_even_with_ok_exit_and_status(self):
        plan=dict(safe_to_run=True,live_step_count=1,recommended_command=["macro","workflow-run"])
        r=run_candidate([dict(operation="task-run",rest=[],allow_live=True,replies=[reply(plan),uncertain("ok",0)])])[0]
        self.assertEqual(r["exit"],2);self.assertEqual(r["payload"]["status"],"partial")
        self.assertTrue(r["payload"]["workflow_result"]["mutation_may_have_occurred"])


@unittest.skipUnless(sys.platform=="win32","Windows original-defect characterization")
class ExecutionOriginalUncertaintyTests(unittest.TestCase):
    def test_original_cdp_uncertainty_fell_through_to_second_mutation(self):
        fixture=dict(operation="smart-click",rest=["--label","Name","--allow-cdp"],allow_live=True,
                     replies=[None,True,uncertain(),reply(dict(status="ok",method="Invoke"))])
        with tempfile.TemporaryDirectory(prefix="CUCP original uncertainty ") as temp:
            d=Path(temp);source=d/"original.ps1";inputs=d/"input.json";runner=d/"capture.ps1"
            source.write_bytes(subprocess.check_output(["git","show",f"{BASELINE_TREE}:scripts/cucp.ps1"],cwd=ROOT))
            inputs.write_text(json.dumps([fixture]),encoding="utf-8-sig");runner.write_text(PS_CAPTURE,encoding="utf-8-sig")
            p=subprocess.run([shutil.which("powershell.exe"),"-NoProfile","-NonInteractive","-File",str(runner),"-Source",str(source),"-InputPath",str(inputs)],capture_output=True,timeout=30)
            self.assertEqual(p.returncode,0,p.stderr.decode(errors="replace"));original=json.loads(p.stdout.decode("utf-8-sig"))[0]
            self.assertEqual(original["exit"],0);self.assertEqual(original["consumed"],4)
            self.assertEqual([e["argv"][1] for e in decode_wire(original["effects"]) if e["kind"]=="Native"],["cdp-smart-click","uia-invoke"])


class ExecutionSessionUncertaintyTests(unittest.TestCase):
    def test_lost_or_malformed_live_reply_is_terminal_with_explicit_uncertainty(self):
        import base64
        from test_legacy_execution_parity import PROJECT
        from test_legacy_execution_transport import wire
        run_candidate([])
        dotnet=shutil.which("dotnet") or __import__("os").environ.get("DOTNET")
        dll=PROJECT/"bin/Release/net8.0/PcuCp.LegacyExecution.ContractTests.dll"
        def frames(identifier,value):
            data=json.dumps(dict(state="ok",value=wire(value))).encode()
            return json.dumps(dict(kind="part",id=identifier,data=base64.b64encode(data).decode()))+"\n"+json.dumps(dict(kind="end",id=identifier))+"\n"
        for tail in ("",'{"kind":"end","id":999}\n','{"kind":"end","id":"5"}\n','not json\n',"x"*66001+"\n"):
            # Clock start then workflow-plan; reply for first live child is lost.
            startup=dict(operation="workflow-run",rest=[],allow_live=True,confirm_sensitive=False)
            data=json.dumps(startup)+"\n"+frames(1,0)+frames(2,workflow(live=True))+frames(3,0)+frames(4,0)+tail
            p=subprocess.run([dotnet,str(dll),"--session-fixture"],input=data.encode(),capture_output=True,timeout=30)
            self.assertEqual(p.returncode,1,p.stderr.decode(errors="replace"))
            parts={};completed=[]
            for line in p.stdout.splitlines():
                frame=json.loads(line);key=(frame["target"],frame["id"])
                if frame["kind"]=="part":parts.setdefault(key,bytearray()).extend(base64.b64decode(frame["data"]))
                else:completed.append((key,json.loads(parts[key])))
            errors=[value for (kind,_),value in completed if kind=="error"]
            self.assertEqual(len(errors),1);self.assertTrue(errors[0]["mutation_may_have_occurred"])
            self.assertFalse(errors[0]["automatic_retry"])
            actions=[value for (kind,_),value in completed if kind=="effect" and value["live"]]
            self.assertEqual(len(actions),1)

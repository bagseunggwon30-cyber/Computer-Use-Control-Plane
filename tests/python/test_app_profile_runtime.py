"""Independent acquisition/write gates, cancellation, and fixed entry protocol."""
import base64
import copy
import json
from pathlib import Path
import subprocess
import sys
import threading
import unittest

from pcucp_cli.legacy_app_profile_runtime import AppProfileRuntime
from pcucp_cli.legacy_host_protocol import LegacyHostError

ROOT = Path(__file__).resolve().parents[2]
DESTINATION = 'Z:\\owned fixture\\app-strategy.jsonl'


def completion(queries):
    return dict(state='complete', queries=copy.deepcopy(queries), exit=0, json_depth=14,
                brief='ok app-profile type=fixture strategy=uia_pattern labels=0 elapsed_ms=0',
                payload=dict(schema='cucp.app-profile/v1', elapsed_ms=0,
                             strategy_persistence=dict(record=None, recorded=False)))


def recording_state():
    query = dict(kind='record', argv=['fixture', 'desktop', 'uia_pattern', 'high', '75', 'fixture', 'main', 'title'])
    state = dict(facade='cucp.app-profile-controller/v1', kernel_evaluations=2,
                 state='query', queries=[query], query=query, record_completion=completion([query]),
                 record_authorization=dict(schema='cucp.app-profile-record-authorization/v1', query=query,
                 history_file=DESTINATION, strategy_score=dict(total_score=75, confidence='high')))
    return state


class AppProfileRuntimeTests(unittest.TestCase):
    def runtime(self, acquire, state, **kwargs):
        return AppProfileRuntime(acquire, history_file=DESTINATION, kernel=lambda args:copy.deepcopy(state),
                                 clock=lambda:0, **kwargs)

    def test_only_explicit_flags_valid_preflight_and_fixed_destination_allow_single_append(self):
        state=recording_state()
        calls=[]
        runtime=self.runtime(lambda query:calls.append(query) or dict(result={'success':True}), state)
        result=runtime.run(['--remember-strategy'])
        self.assertEqual(len(calls),1)
        self.assertEqual(runtime.calls,1)
        self.assertEqual(runtime.evaluations,2)
        self.assertTrue(result['payload']['strategy_persistence']['recorded'])
        with self.assertRaises(LegacyHostError):runtime.run(['--record-strategy'])
        self.assertEqual(len(calls),1)
        for words in ([],['--record-strategy','--no-strategy-history']):
            with self.assertRaises(LegacyHostError):self.runtime(lambda query:self.fail('Unexpected write'),state).run(words)
        for field,value in (('history_file','Z:\\other.jsonl'),('schema','other')):
            bad=copy.deepcopy(state);bad['record_authorization'][field]=value
            with self.assertRaises(LegacyHostError):self.runtime(lambda query:self.fail('Unexpected write'),bad).run(['--record-strategy'])
        for value in (49,101,True,75.0):
            bad=copy.deepcopy(state);bad['record_authorization']['strategy_score']['total_score']=value
            with self.assertRaises(LegacyHostError):self.runtime(lambda query:self.fail('Unexpected write'),bad).run(['--record-strategy'])
        for change in ('argv','trace','preflight','evaluations'):
            bad=copy.deepcopy(state)
            if change=='argv':bad['record_authorization']['query']['argv'][0]='other'
            elif change=='trace':bad['queries']=[]
            elif change=='preflight':bad['record_completion']['payload']['schema']='other'
            else:bad['kernel_evaluations']=1
            with self.subTest(change=change),self.assertRaises(LegacyHostError):
                self.runtime(lambda query:self.fail('Unexpected write'),bad).run(['--record-strategy'])

    def test_actual_record_shapes_truth_and_exception_never_replay_or_call_kernel_after_append(self):
        for raw,expected in ((None,False),({},True),({'error':'failed'},False),({'error':''},True),
                             ({'error':False},True),({'success':False},True),([],False),(['recorded'],True),
                             ([{'error':'failed'}],False),([{'error':False},{'error':False}],False),
                             ({'Error':'failed'},False),([{'ERROR':None},{'error':False}],False),
                             ([{'error':[False,False]}],False)):
            with self.subTest(raw=raw):
                runtime=self.runtime(lambda query:dict(result=raw),recording_state())
                result=runtime.run(['--record-strategy'])
                persistence=result['payload']['strategy_persistence']
                self.assertEqual(persistence['record'],raw)
                self.assertIs(persistence['recorded'],expected)
                self.assertEqual(runtime.calls,1)
        runtime=self.runtime(lambda query:dict(error='fixture_record'),recording_state())
        with self.assertRaisesRegex(LegacyHostError,'fixture_record'):runtime.run(['--record-strategy'])
        self.assertTrue(runtime.record_attempted)
        self.assertEqual(runtime.calls,1)

    def test_shell_record_truth_fact_preserves_runtime_array_metadata_without_unwrapping_literal_objects(self):
        raw={'value':[],'Count':0}
        result=self.runtime(lambda query:dict(result=raw,recorded=False),recording_state()).run(['--record-strategy'])
        self.assertEqual(result['payload']['strategy_persistence']['record'],raw)
        self.assertFalse(result['payload']['strategy_persistence']['recorded'])
        result=self.runtime(lambda query:dict(result=raw),recording_state()).run(['--record-strategy'])
        self.assertTrue(result['payload']['strategy_persistence']['recorded'])
        with self.assertRaises(LegacyHostError):
            self.runtime(lambda query:dict(result=raw,recorded='false'),recording_state()).run(['--record-strategy'])

    def test_cancelled_expired_and_unsupported_queries_never_acquire(self):
        cancelled=threading.Event();cancelled.set()
        for kwargs in ({'cancelled':cancelled},{'parent_deadline':-1}):
            with self.assertRaises(LegacyHostError):
                self.runtime(lambda query:self.fail('Unexpected acquisition'),recording_state(),**kwargs).run(['--record-strategy'])
        query=dict(kind='native',argv=['-Action','type-native','-Text','other'])
        state=dict(facade='cucp.app-profile-controller/v1',kernel_evaluations=1,state='query',query=query,queries=[query])
        with self.assertRaises(LegacyHostError):self.runtime(lambda query:self.fail('Unexpected action'),state).run([])

    def test_fixed_entry_keeps_history_and_culture_in_startup_and_does_not_replay(self):
        entry=ROOT/'pcucp-next/python/legacy_app_profile.py'
        encode=lambda value:base64.b64encode(value.encode()).decode()
        command=[sys.executable,str(entry),'--history-file-base64',encode(json.dumps(DESTINATION)),
                 '--culture-base64',encode('en-US'),'--timeout-s','5']
        state=dict(completion([]),facade='cucp.app-profile-controller/v1',kernel_evaluations=1)
        frames='\n'.join(json.dumps(value) for value in (dict(rest=[],brief=False),dict(state=state,score_is_integer=True)))+'\n'
        result=subprocess.run(command,input=frames.encode(),capture_output=True,timeout=8)
        self.assertEqual(result.returncode,0,result.stderr.decode())
        replies=[json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual([reply['kind'] for reply in replies],['kernel','complete'])
        self.assertEqual(replies[0]['args']['history_file'],DESTINATION)
        result=subprocess.run(command,input=json.dumps(dict(rest=[],brief=False,history_file='other')).encode()+b'\n',
                              capture_output=True,timeout=8)
        self.assertNotEqual(result.returncode,0)
        self.assertEqual(json.loads(result.stdout)['kind'],'error')


if __name__=='__main__':
    unittest.main()
